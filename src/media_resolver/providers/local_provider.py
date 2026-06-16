from __future__ import annotations

import shutil
from pathlib import Path

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
from media_resolver.versions.fingerprint import fingerprint_audio

AUDIO_EXTENSIONS = {".flac", ".wav", ".aiff", ".aif", ".alac", ".m4a", ".mp3", ".opus", ".ogg", ".webm"}
VIDEO_EXTENSIONS = {".mp4", ".mkv", ".webm", ".mov", ".avi"}


class LocalProvider:
    def __init__(self, registry: ToolRegistry) -> None:
        self.registry = registry

    def inspect(
        self,
        query: str,
        intent: MediaIntent,
        quality: QualityMode,
        policy: SourcePolicy,
    ) -> list[MediaCandidate]:
        if not policy.local:
            return []

        path = Path(query).expanduser()
        if not path.exists():
            return []

        files = list(_iter_files(path, intent))
        candidates = []
        for index, file in enumerate(files, start=1):
            candidate = self._candidate_from_file(file, index=index, intent=intent, quality=quality)
            if candidate:
                candidates.append(candidate)
        return candidates

    def download(
        self,
        candidate: MediaCandidate,
        output_dir: Path,
        naming: NamingTemplate,
    ) -> Path:
        source = Path(candidate.url)
        relative = naming.render(candidate.metadata)
        target = output_dir / relative
        if target.suffix.lower() != source.suffix.lower():
            target = target.with_suffix(source.suffix)
        target.parent.mkdir(parents=True, exist_ok=True)
        if source.resolve() != target.resolve():
            shutil.copy2(source, target)
        if candidate.metadata.extra.get("tag_after_copy", True):
            write_basic_tags(target, candidate.metadata)
            write_cover_art(target, candidate.metadata, self.registry)
            write_lyrics_sidecars(target, candidate.metadata)
        return target

    def _candidate_from_file(
        self,
        file: Path,
        index: int,
        intent: MediaIntent,
        quality: QualityMode,
    ) -> MediaCandidate | None:
        duration_seconds = None
        if intent == MediaIntent.TEXT:
            if file.suffix.lower() not in {".srt", ".vtt", ".lrc", ".txt"}:
                return None
            claim = QualityClaim(codec="text", container=file.suffix.lstrip("."), is_real=True)
        elif file.suffix.lower() in AUDIO_EXTENSIONS:
            try:
                claim = inspect_audio(file, self.registry)
                duration_seconds = inspect_duration(file, self.registry)
            except Exception:
                claim = QualityClaim(codec=file.suffix.lstrip(".") or "audio", container=file.suffix.lstrip("."))
                duration_seconds = None
            if not _quality_allowed(claim, quality):
                return None
        elif intent == MediaIntent.VIDEO and file.suffix.lower() in VIDEO_EXTENSIONS:
            claim = QualityClaim(codec="video", container=file.suffix.lstrip("."), is_real=True)
        else:
            return None

        metadata = MediaMetadata(
            title=file.stem,
            artist="Unknown Artist",
            album_artist="Unknown Artist",
            album=file.parent.name or "Unknown Album",
            track_number=index,
            playlist_index=index,
            source="Local",
            ext=file.suffix.lstrip("."),
            duration_seconds=duration_seconds if file.suffix.lower() in AUDIO_EXTENSIONS else None,
            extra={
                "tag_after_copy": intent == MediaIntent.AUDIO,
                "fingerprint": fingerprint_audio(file, self.registry)
                if file.suffix.lower() in AUDIO_EXTENSIONS
                else {},
            },
        )
        return MediaCandidate(
            source="Local",
            url=str(file),
            metadata=metadata,
            quality=claim,
            confidence=0.8,
            provider_payload={"provider": self},
        )


def _iter_files(path: Path, intent: MediaIntent):
    if path.is_file():
        yield path
        return

    allowed = AUDIO_EXTENSIONS | VIDEO_EXTENSIONS | {".srt", ".vtt", ".lrc", ".txt"}
    for file in sorted(path.rglob("*")):
        if file.is_file() and file.suffix.lower() in allowed:
            if intent == MediaIntent.AUDIO and file.suffix.lower() not in AUDIO_EXTENSIONS:
                continue
            if intent == MediaIntent.VIDEO and file.suffix.lower() not in VIDEO_EXTENSIONS:
                continue
            yield file


def _quality_allowed(claim: QualityClaim, mode: QualityMode) -> bool:
    return quality_satisfies(claim, mode)
