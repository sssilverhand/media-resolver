from __future__ import annotations

import shutil
from pathlib import Path
from urllib.parse import unquote, urlparse

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
from media_resolver.processing.ffprobe import inspect_audio, inspect_duration
from media_resolver.processing.sidecars import write_lyrics_sidecars
from media_resolver.processing.tagger import write_basic_tags, write_cover_art


class DirectProvider:
    def __init__(self, registry: ToolRegistry) -> None:
        self.registry = registry

    def inspect(
        self,
        query: str,
        intent: MediaIntent,
        quality: QualityMode,
        policy: SourcePolicy,
    ) -> list[MediaCandidate]:
        if not policy.direct or not _looks_like_direct_url(query):
            return []

        filename = _filename_from_url(query)
        suffix = Path(filename).suffix.lower()
        if intent == MediaIntent.VIDEO and suffix not in {".mp4", ".mkv", ".webm", ".mov"}:
            return []
        if intent == MediaIntent.TEXT and suffix not in {".srt", ".vtt", ".lrc", ".txt"}:
            return []

        claim = _claim_from_suffix(suffix, quality)
        if claim is None:
            return []

        metadata = MediaMetadata(
            title=Path(filename).stem or "direct-download",
            source="Direct",
            ext=suffix.lstrip(".") or "bin",
        )
        return [
            MediaCandidate(
                source="Direct",
                url=query,
                metadata=metadata,
                quality=claim,
                confidence=0.65,
                provider_payload={"provider": self, "quality_mode": quality.value},
            )
        ]

    def download(
        self,
        candidate: MediaCandidate,
        output_dir: Path,
        naming: NamingTemplate,
    ) -> Path:
        relative = naming.render(candidate.metadata)
        target = output_dir / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        with requests.get(candidate.url, stream=True, timeout=30) as response:
            response.raise_for_status()
            with target.open("wb") as file:
                shutil.copyfileobj(response.raw, file)

        if candidate.metadata.ext.lower() not in {"srt", "vtt", "lrc", "txt"}:
            try:
                verified = inspect_audio(target, self.registry)
                requested_quality = QualityMode(
                    candidate.provider_payload.get("quality_mode", QualityMode.BEST_AVAILABLE)
                )
                if not quality_satisfies(verified, requested_quality):
                    target.unlink(missing_ok=True)
                    raise RuntimeError(
                        f"Downloaded file is {verified.summary()}, not {requested_quality.value}."
                )
                candidate.quality = verified
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
        return target


def _claim_from_suffix(suffix: str, mode: QualityMode) -> QualityClaim | None:
    ext = suffix.lstrip(".") or "bin"
    lossless = ext in {"flac", "wav", "aiff", "aif", "alac"}
    if mode == QualityMode.FLAC_REAL and ext != "flac":
        return None
    if mode == QualityMode.HI_RES_REAL and not lossless:
        return None
    if mode == QualityMode.OPUS_NATIVE and ext != "opus":
        return None
    if mode == QualityMode.MP3_320_REAL and ext != "mp3":
        return None
    return QualityClaim(codec=ext, container=ext, is_lossless=lossless, is_real=True)


def _looks_like_direct_url(value: str) -> bool:
    parsed = urlparse(value)
    if not (parsed.scheme in {"http", "https"} and parsed.netloc):
        return False
    return Path(parsed.path).suffix.lower() in {
        ".flac",
        ".wav",
        ".aiff",
        ".aif",
        ".alac",
        ".m4a",
        ".mp3",
        ".opus",
        ".ogg",
        ".webm",
        ".mp4",
        ".mkv",
        ".mov",
        ".srt",
        ".vtt",
        ".lrc",
        ".txt",
    }


def _filename_from_url(value: str) -> str:
    path = urlparse(value).path
    name = Path(unquote(path)).name
    return name or "download.bin"
