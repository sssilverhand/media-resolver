from __future__ import annotations

import base64
import subprocess
import tempfile
from pathlib import Path

import requests
from mutagen import File
from mutagen.flac import FLAC, Picture
from mutagen.id3 import APIC, ID3, ID3NoHeaderError
from mutagen.mp3 import MP3
from mutagen.mp4 import MP4, MP4Cover
from mutagen.oggopus import OggOpus
from mutagen.oggvorbis import OggVorbis

from media_resolver.core.models import MediaMetadata
from media_resolver.core.tools import ToolRegistry


def write_basic_tags(path: Path, metadata: MediaMetadata) -> None:
    audio = File(path, easy=True)
    if audio is None:
        return
    audio["title"] = metadata.title
    audio["artist"] = metadata.artist
    audio["album"] = metadata.album
    audio["albumartist"] = metadata.album_artist
    if metadata.year:
        audio["date"] = metadata.year
    audio["tracknumber"] = str(metadata.track_number)
    if metadata.isrc:
        audio["isrc"] = metadata.isrc
    audio.save()


def write_cover_art(path: Path, metadata: MediaMetadata, registry: ToolRegistry | None = None) -> None:
    artwork_url = str(metadata.extra.get("artwork_url") or metadata.extra.get("thumbnail") or "")
    if not artwork_url:
        return

    image = _download_image(artwork_url)
    if image is None:
        return
    data, mime = image
    data, mime = _ensure_supported_image(data, mime, registry)
    if not data or mime not in {"image/jpeg", "image/png"}:
        return

    suffix = path.suffix.lower()
    if suffix == ".mp3":
        _write_mp3_cover(path, data, mime)
    elif suffix in {".m4a", ".mp4"}:
        _write_mp4_cover(path, data, mime)
    elif suffix == ".flac":
        _write_flac_cover(path, data, mime)
    elif suffix in {".opus", ".ogg"}:
        _write_ogg_cover(path, data, mime)


def _download_image(url: str) -> tuple[bytes, str] | None:
    try:
        response = requests.get(url, timeout=20)
        response.raise_for_status()
    except Exception:
        return None

    data = response.content
    mime = response.headers.get("content-type", "").split(";")[0].lower()
    if not mime:
        mime = _guess_mime(data)
    return data, mime


def _ensure_supported_image(
    data: bytes, mime: str, registry: ToolRegistry | None
) -> tuple[bytes, str]:
    if mime in {"image/jpeg", "image/png"}:
        return data, mime
    if registry is None or not registry.ffmpeg.available or registry.ffmpeg.path is None:
        return b"", ""

    with tempfile.TemporaryDirectory() as temp_dir:
        source = Path(temp_dir) / "cover.input"
        target = Path(temp_dir) / "cover.jpg"
        source.write_bytes(data)
        command = [
            str(registry.ffmpeg.path),
            "-y",
            "-i",
            str(source),
            "-frames:v",
            "1",
            str(target),
        ]
        try:
            subprocess.run(command, check=True, capture_output=True)
        except Exception:
            return b"", ""
        return target.read_bytes(), "image/jpeg"


def _write_mp3_cover(path: Path, data: bytes, mime: str) -> None:
    audio = MP3(path)
    try:
        tags = ID3(path)
    except ID3NoHeaderError:
        tags = ID3()
    tags.delall("APIC")
    tags.add(APIC(encoding=3, mime=mime, type=3, desc="Cover", data=data))
    tags.save(path)
    audio.load()


def _write_mp4_cover(path: Path, data: bytes, mime: str) -> None:
    audio = MP4(path)
    cover_format = MP4Cover.FORMAT_PNG if mime == "image/png" else MP4Cover.FORMAT_JPEG
    audio["covr"] = [MP4Cover(data, imageformat=cover_format)]
    audio.save()


def _write_flac_cover(path: Path, data: bytes, mime: str) -> None:
    audio = FLAC(path)
    audio.clear_pictures()
    picture = _picture(data, mime)
    audio.add_picture(picture)
    audio.save()


def _write_ogg_cover(path: Path, data: bytes, mime: str) -> None:
    audio = OggOpus(path) if path.suffix.lower() == ".opus" else OggVorbis(path)
    picture = _picture(data, mime)
    encoded = base64.b64encode(picture.write()).decode("ascii")
    audio["metadata_block_picture"] = [encoded]
    audio.save()


def _picture(data: bytes, mime: str) -> Picture:
    picture = Picture()
    picture.type = 3
    picture.mime = mime
    picture.desc = "Cover"
    picture.data = data
    return picture


def _guess_mime(data: bytes) -> str:
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        return "image/webp"
    return ""
