from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class MediaIntent(str, Enum):
    AUDIO = "audio"
    VIDEO = "video"
    TEXT = "text"
    METADATA = "metadata"


class QualityMode(str, Enum):
    BEST_AVAILABLE = "best_available"
    OPUS_NATIVE = "opus_native"
    MP3_320_REAL = "mp3_320_real"
    FLAC_REAL = "flac_real"
    HI_RES_REAL = "hi_res_real"
    SUBTITLES_ONLY = "subtitles_only"
    METADATA_ONLY = "metadata_only"


@dataclass(frozen=True)
class SourcePolicy:
    spotify: bool = True
    tidal: bool = True
    youtube: bool = True
    soundcloud: bool = False
    audius: bool = True
    bandcamp: bool = False
    archive: bool = True
    direct: bool = True
    local: bool = True
    torrents: bool = False
    telegram: bool = False
    custom: bool = False

    @classmethod
    def for_interactive(
        cls, allow_alternatives: bool = False, allow_torrents: bool = False
    ) -> "SourcePolicy":
        return cls(
            spotify=True,
            tidal=True,
            youtube=True,
            soundcloud=allow_alternatives,
            audius=True,
            bandcamp=True,
            archive=allow_alternatives,
            direct=True,
            local=True,
            torrents=allow_torrents,
            telegram=allow_alternatives,
            custom=allow_alternatives,
        )

    @classmethod
    def from_labels(cls, labels: list[str]) -> "SourcePolicy":
        values = set(labels)
        return cls(
            spotify="Spotify metadata" in values,
            tidal="Tidal" in values,
            youtube="YouTube / YouTube Music" in values,
            soundcloud="SoundCloud" in values,
            audius="Audius" in values,
            bandcamp="Bandcamp / public downloads" in values,
            archive="Archive.org / public archives" in values,
            direct="Direct links" in values,
            local="Local files" in values,
            torrents="Torrents / magnet links" in values,
            telegram="Telegram links/files" in values,
            custom="Custom provider scripts" in values,
        )

    @classmethod
    def youtube_only(cls) -> "SourcePolicy":
        return cls(
            spotify=False,
            tidal=False,
            youtube=True,
            soundcloud=False,
            audius=False,
            bandcamp=False,
            archive=False,
            direct=False,
            local=False,
            torrents=False,
            telegram=False,
            custom=False,
        )


@dataclass
class MediaMetadata:
    title: str
    artist: str = "Unknown Artist"
    album_artist: str = "Unknown Artist"
    album: str = "Unknown Album"
    channel: str = "Unknown Channel"
    year: str = ""
    track_number: int = 1
    disc_number: int = 1
    playlist_index: int = 1
    playlist_title: str = "Playlist"
    version: str = "current"
    source: str = ""
    isrc: str = ""
    ext: str = "mka"
    duration_seconds: int | None = None
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class QualityClaim:
    codec: str
    container: str = ""
    bitrate_kbps: int | None = None
    sample_rate_hz: int | None = None
    bit_depth: int | None = None
    is_lossless: bool = False
    is_real: bool = True
    transcoded: bool = False
    notes: tuple[str, ...] = ()

    def summary(self) -> str:
        parts = [self.codec.upper()]
        if self.bitrate_kbps:
            parts.append(f"{self.bitrate_kbps} kbps")
        if self.bit_depth and self.sample_rate_hz:
            parts.append(f"{self.bit_depth}-bit/{self.sample_rate_hz / 1000:g} kHz")
        elif self.sample_rate_hz:
            parts.append(f"{self.sample_rate_hz / 1000:g} kHz")
        if self.is_lossless:
            parts.append("lossless")
        return " ".join(parts)

    def with_notes(self, *notes: str) -> "QualityClaim":
        return QualityClaim(
            codec=self.codec,
            container=self.container,
            bitrate_kbps=self.bitrate_kbps,
            sample_rate_hz=self.sample_rate_hz,
            bit_depth=self.bit_depth,
            is_lossless=self.is_lossless,
            is_real=self.is_real,
            transcoded=self.transcoded,
            notes=tuple([*self.notes, *notes]),
        )


@dataclass
class MediaCandidate:
    source: str
    url: str
    metadata: MediaMetadata
    quality: QualityClaim
    confidence: float
    provider_payload: dict[str, Any] = field(default_factory=dict)

    def display_label(self) -> str:
        duration = _format_duration(self.metadata.duration_seconds)
        duration_part = f" | {duration}" if duration else ""
        return (
            f"{self.metadata.title} | {self.source}{duration_part} | {self.quality.summary()} | "
            f"{self.confidence:.0%}"
        )


def _format_duration(seconds: int | float | None) -> str:
    if seconds is None:
        return ""
    try:
        total = int(round(float(seconds)))
    except (TypeError, ValueError):
        return ""
    if total <= 0:
        return ""
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}:{minutes:02}:{secs:02}"
    return f"{minutes}:{secs:02}"
