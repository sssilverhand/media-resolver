from __future__ import annotations

import subprocess
from pathlib import Path
from urllib.parse import urlparse

import requests

from media_resolver.core.models import (
    MediaCandidate,
    MediaIntent,
    MediaMetadata,
    QualityClaim,
    QualityMode,
    SourcePolicy,
)
from media_resolver.core.naming import NamingTemplate
from media_resolver.core.quality import quality_satisfies
from media_resolver.core.tools import ToolRegistry
from media_resolver.metadata.public import _metadata_from_tiddl_track
from media_resolver.processing.ffprobe import inspect_audio, inspect_duration
from media_resolver.processing.sidecars import write_lyrics_sidecars
from media_resolver.processing.tagger import write_basic_tags, write_cover_art


class TidalProvider:
    def __init__(self, registry: ToolRegistry) -> None:
        self.registry = registry

    def inspect(
        self,
        query: str,
        intent: MediaIntent,
        quality: QualityMode,
        policy: SourcePolicy,
    ) -> list[MediaCandidate]:
        if not policy.tidal or intent not in {MediaIntent.AUDIO, MediaIntent.METADATA}:
            return []

        api = _tiddl_api()
        if api is None:
            return []

        tracks = []
        try:
            tidal_track_id = _tidal_track_id(query)
            if tidal_track_id:
                tracks = [api.getTrack(tidal_track_id)]
            elif not _looks_like_url(query):
                tracks = list(api.getSearch(query).tracks.items[:10])
        except Exception:
            return []

        candidates = []
        for track in tracks:
            metadata = _metadata_from_tiddl_track(track)
            claim = _claim_from_tidal_quality(getattr(track, "audioQuality", ""))
            if not _quality_allowed(claim, quality):
                continue
            track_url = metadata.extra.get("tidal_url") or f"https://listen.tidal.com/track/{track.id}"
            candidates.append(
                MediaCandidate(
                    source="Tidal",
                    url=str(track_url),
                    metadata=metadata,
                    quality=claim,
                    confidence=_confidence(query, metadata),
                    provider_payload={
                        "provider": self,
                        "tidal_track_id": getattr(track, "id", ""),
                        "quality_mode": quality.value,
                    },
                )
            )
        return candidates

    def download(
        self,
        candidate: MediaCandidate,
        output_dir: Path,
        naming: NamingTemplate,
    ) -> list[Path]:
        api = _tiddl_api()
        if api is None:
            raise RuntimeError("Tidal downloads require a logged-in Tidal session.")

        try:
            from tiddl.download import parseTrackStream
        except Exception as exc:
            raise RuntimeError("Tidal support is not installed in this build.") from exc

        output_dir.mkdir(parents=True, exist_ok=True)
        track_id = str(
            candidate.provider_payload.get("tidal_track_id") or _tidal_track_id(candidate.url)
        )
        track_stream = api.getTrackStream(track_id, quality=_tiddl_track_quality(candidate.quality))
        urls, extension = parseTrackStream(track_stream)

        relative = Path(naming.render(candidate.metadata)).with_suffix(extension)
        target = output_dir / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        _download_segments(urls, target)

        if str(getattr(track_stream, "audioQuality", "")).upper() == "HI_RES_LOSSLESS":
            target = _extract_hires_flac(target, self.registry) or target

        candidate.metadata.ext = target.suffix.lower().lstrip(".")
        try:
            verified_quality = inspect_audio(target, self.registry)
            requested_quality = QualityMode(
                candidate.provider_payload.get("quality_mode", QualityMode.BEST_AVAILABLE)
            )
            if not quality_satisfies(verified_quality, requested_quality):
                target.unlink(missing_ok=True)
                raise RuntimeError(
                    f"Downloaded file is {verified_quality.summary()}, "
                    f"not {requested_quality.value}."
            )
            candidate.quality = verified_quality
            try:
                candidate.metadata.duration_seconds = inspect_duration(target, self.registry)
            except Exception:
                pass
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
        try:
            write_basic_tags(target, candidate.metadata)
            write_cover_art(target, candidate.metadata, self.registry)
            write_lyrics_sidecars(target, candidate.metadata)
        except Exception:
            pass
        return [target]


def _tiddl_api():
    try:
        from tiddl.api import TidalApi
        from tiddl.config import Config
    except Exception:
        return None

    try:
        config = Config.fromFile()
        auth = config.auth
        if not auth.token or not auth.user_id or not auth.country_code:
            return None
        return TidalApi(auth.token, auth.user_id, auth.country_code, omit_cache=config.omit_cache)
    except Exception:
        return None


def _tidal_track_id(value: str) -> str:
    parsed = urlparse(value)
    if parsed.netloc and "tidal.com" in parsed.netloc:
        parts = [part for part in parsed.path.split("/") if part]
        if "track" in parts:
            index = parts.index("track")
            if index + 1 < len(parts):
                return parts[index + 1]
    if value.startswith("track/"):
        return value.split("/", 1)[1]
    return ""


def _claim_from_tidal_quality(quality: str) -> QualityClaim:
    quality = str(quality or "").upper()
    if quality == "HI_RES_LOSSLESS":
        return QualityClaim(
            codec="flac",
            container="flac",
            sample_rate_hz=96000,
            bit_depth=24,
            is_lossless=True,
            is_real=True,
            notes=("Tidal catalog quality; exact stream is verified after download.",),
        )
    if quality == "LOSSLESS":
        return QualityClaim(
            codec="flac",
            container="flac",
            sample_rate_hz=44100,
            bit_depth=16,
            is_lossless=True,
            is_real=True,
            notes=("Tidal catalog quality; exact stream is verified after download.",),
        )
    return QualityClaim(
        codec="aac",
        container="m4a",
        bitrate_kbps=320,
        is_lossless=False,
        is_real=True,
        notes=("Tidal catalog quality; exact stream is verified after download.",),
    )


def _quality_allowed(claim: QualityClaim, mode: QualityMode) -> bool:
    return quality_satisfies(claim, mode)


def _tiddl_track_quality(claim: QualityClaim) -> str:
    if claim.is_lossless and (claim.bit_depth or 0) >= 24:
        return "HI_RES_LOSSLESS"
    if claim.is_lossless:
        return "LOSSLESS"
    return "HIGH"


def _download_segments(urls: list[str], target: Path) -> None:
    with requests.Session() as session, target.open("wb") as file:
        for url in urls:
            response = session.get(url, timeout=60)
            response.raise_for_status()
            file.write(response.content)


def _extract_hires_flac(source: Path, registry: ToolRegistry) -> Path | None:
    if source.suffix.lower() != ".m4a":
        return None
    if not registry.ffmpeg.available or registry.ffmpeg.path is None:
        return None

    target = source.with_suffix(".flac")
    command = [
        str(registry.ffmpeg.path),
        "-y",
        "-i",
        str(source),
        "-map",
        "0:a",
        "-c",
        "copy",
        str(target),
    ]
    try:
        subprocess.run(command, check=True, capture_output=True)
    except Exception:
        return None
    try:
        source.unlink()
    except OSError:
        pass
    return target


def _confidence(query: str, metadata: MediaMetadata) -> float:
    if _looks_like_url(query):
        return 0.95
    query_tokens = set(query.lower().split())
    haystack = f"{metadata.artist} {metadata.title} {metadata.album}".lower()
    if not query_tokens:
        return 0.5
    hits = sum(1 for token in query_tokens if token in haystack)
    return min(0.98, 0.5 + hits / len(query_tokens) * 0.45)


def _looks_like_url(value: str) -> bool:
    parsed = urlparse(value)
    return bool(parsed.scheme and parsed.netloc)
