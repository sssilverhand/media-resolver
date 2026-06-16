from __future__ import annotations

import shutil
from pathlib import Path

import requests

from media_resolver.core.models import (
    MediaCandidate,
    MediaIntent,
    MediaMetadata,
    QualityClaim,
    QualityMode,
    SourcePolicy,
)
from media_resolver.core.matching import version_flags, version_note
from media_resolver.core.naming import NamingTemplate
from media_resolver.core.quality import quality_satisfies
from media_resolver.core.tools import ToolRegistry
from media_resolver.processing.ffprobe import inspect_audio
from media_resolver.processing.sidecars import write_lyrics_sidecars
from media_resolver.processing.tagger import write_basic_tags, write_cover_art


class AudiusProvider:
    def __init__(self, registry: ToolRegistry) -> None:
        self.registry = registry

    def inspect(
        self,
        query: str,
        intent: MediaIntent,
        quality: QualityMode,
        policy: SourcePolicy,
    ) -> list[MediaCandidate]:
        if not policy.audius or intent != MediaIntent.AUDIO:
            return []
        if query.startswith(("http://", "https://")):
            return []
        if quality not in {
            QualityMode.BEST_AVAILABLE,
            QualityMode.METADATA_ONLY,
            QualityMode.MP3_320_REAL,
            QualityMode.FLAC_REAL,
            QualityMode.HI_RES_REAL,
        }:
            return []

        try:
            response = requests.get(
                "https://discoveryprovider.audius.co/v1/tracks/search",
                params={"query": query, "app_name": "media-resolver"},
                timeout=12,
            )
            response.raise_for_status()
            tracks = response.json().get("data", [])
        except Exception:
            return []

        candidates: list[MediaCandidate] = []
        for track in tracks[:10]:
            stream_url = _stream_url(track)
            if not stream_url:
                continue
            user = track.get("user") or {}
            artist = user.get("name") or user.get("handle") or "Unknown Artist"
            ext = _extension_from_original(track.get("orig_filename")) or "mp3"
            if not _extension_allowed(ext, quality):
                continue
            metadata = MediaMetadata(
                title=track.get("title") or "Audius track",
                artist=artist,
                album_artist=artist,
                album="Audius",
                year=str(track.get("release_date") or track.get("created_at") or "")[:4],
                source="Audius",
                ext=ext,
                duration_seconds=_duration_seconds(track.get("duration")),
                extra={
                    "audius_id": track.get("id"),
                    "audius_permalink": track.get("permalink"),
                    "artwork_url": _artwork_url(track),
                    "version_flags": version_flags(track.get("title") or ""),
                },
            )
            claim = QualityClaim(
                codec=ext,
                container=ext,
                is_lossless=ext in {"flac", "wav", "aiff", "aif", "alac"},
                is_real=False,
                notes=("Audius API claim; exact quality is verified after download.",),
            )
            note = version_note(metadata.extra["version_flags"])
            if note:
                claim = claim.with_notes(note)
            candidates.append(
                MediaCandidate(
                    source="Audius",
                    url=stream_url,
                    metadata=metadata,
                    quality=claim,
                    confidence=_confidence(query, metadata),
                    provider_payload={"provider": self, "quality_mode": quality.value},
                )
            )
        return candidates

    def download(
        self,
        candidate: MediaCandidate,
        output_dir: Path,
        naming: NamingTemplate,
    ) -> Path:
        relative = naming.render(candidate.metadata)
        target = output_dir / relative
        if not target.suffix:
            target = target.with_suffix(f".{candidate.metadata.ext or 'mp3'}")
        target.parent.mkdir(parents=True, exist_ok=True)

        with requests.get(candidate.url, stream=True, timeout=60) as response:
            response.raise_for_status()
            with target.open("wb") as file:
                shutil.copyfileobj(response.raw, file)

        try:
            verified = inspect_audio(target, self.registry)
            requested_quality = QualityMode(
                candidate.provider_payload.get("quality_mode", QualityMode.BEST_AVAILABLE)
            )
            if not _quality_allowed(verified, requested_quality):
                target.unlink(missing_ok=True)
                raise RuntimeError(
                    f"Downloaded file is {verified.summary()}, not {requested_quality.value}."
                )
            candidate.quality = verified
        except RuntimeError:
            raise
        except Exception:
            if candidate.provider_payload.get("quality_mode") in {
                QualityMode.MP3_320_REAL.value,
                QualityMode.FLAC_REAL.value,
                QualityMode.HI_RES_REAL.value,
            }:
                target.unlink(missing_ok=True)
                raise
            pass
        try:
            write_basic_tags(target, candidate.metadata)
            write_cover_art(target, candidate.metadata, self.registry)
            write_lyrics_sidecars(target, candidate.metadata)
        except Exception:
            pass
        return target


def _stream_url(track: dict) -> str:
    stream = track.get("stream")
    if isinstance(stream, dict) and stream.get("url"):
        return stream["url"]
    track_id = track.get("id")
    if track_id:
        return f"https://discoveryprovider.audius.co/v1/tracks/{track_id}/stream?app_name=media-resolver"
    return ""


def _extension_from_original(filename: str | None) -> str:
    if not filename:
        return ""
    suffix = Path(filename).suffix.lower().lstrip(".")
    if suffix in {"mp3", "wav", "flac", "aiff", "aif", "alac", "m4a", "ogg", "opus"}:
        return suffix
    return ""


def _duration_seconds(value) -> int | None:
    try:
        seconds = round(float(value))
    except (TypeError, ValueError):
        return None
    return seconds if seconds > 0 else None


def _extension_allowed(ext: str, mode: QualityMode) -> bool:
    if mode in {QualityMode.BEST_AVAILABLE, QualityMode.METADATA_ONLY}:
        return True
    if mode == QualityMode.MP3_320_REAL:
        return ext == "mp3"
    if mode == QualityMode.FLAC_REAL:
        return ext in {"flac", "wav", "aiff", "aif", "alac"}
    if mode == QualityMode.HI_RES_REAL:
        return ext in {"flac", "wav", "aiff", "aif", "alac"}
    return False


def _quality_allowed(claim: QualityClaim, mode: QualityMode) -> bool:
    return quality_satisfies(claim, mode)


def _artwork_url(track: dict) -> str:
    artwork = track.get("artwork") or {}
    for key in ["1000x1000", "480x480", "150x150"]:
        if artwork.get(key):
            return artwork[key]
    return ""


def _confidence(query: str, metadata: MediaMetadata) -> float:
    query_tokens = set(query.lower().split())
    haystack = f"{metadata.artist} {metadata.title}".lower()
    if not query_tokens:
        return 0.5
    hits = sum(1 for token in query_tokens if token in haystack)
    return min(0.95, 0.45 + hits / len(query_tokens) * 0.45)
