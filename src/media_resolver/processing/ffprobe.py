from __future__ import annotations

import json
import subprocess
from pathlib import Path

from media_resolver.core.models import QualityClaim
from media_resolver.core.tools import ToolRegistry


LOSSLESS_CODECS = {"flac", "alac", "wavpack", "pcm_s16le", "pcm_s24le", "pcm_s32le"}


def inspect_audio(path: Path, registry: ToolRegistry) -> QualityClaim:
    if not registry.ffprobe.available or registry.ffprobe.path is None:
        raise RuntimeError("ffprobe is required for quality inspection")

    command = [
        str(registry.ffprobe.path),
        "-v",
        "error",
        "-select_streams",
        "a:0",
        "-show_entries",
        "stream=codec_name,bit_rate,sample_rate,bits_per_raw_sample,bits_per_sample",
        "-of",
        "json",
        str(path),
    ]
    result = subprocess.run(command, check=True, capture_output=True, text=True)
    payload = json.loads(result.stdout)
    stream = payload.get("streams", [{}])[0]
    codec = str(stream.get("codec_name") or "unknown").lower()
    bitrate = _to_int(stream.get("bit_rate"))
    sample_rate = _to_int(stream.get("sample_rate"))
    bit_depth = _to_int(stream.get("bits_per_raw_sample")) or _to_int(stream.get("bits_per_sample"))
    return QualityClaim(
        codec=codec,
        container=path.suffix.lstrip("."),
        bitrate_kbps=round(bitrate / 1000) if bitrate else None,
        sample_rate_hz=sample_rate,
        bit_depth=bit_depth,
        is_lossless=codec in LOSSLESS_CODECS,
        is_real=True,
        transcoded=False,
    )


def inspect_duration(path: Path, registry: ToolRegistry) -> int | None:
    if not registry.ffprobe.available or registry.ffprobe.path is None:
        raise RuntimeError("ffprobe is required for duration inspection")

    command = [
        str(registry.ffprobe.path),
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "json",
        str(path),
    ]
    result = subprocess.run(command, check=True, capture_output=True, text=True)
    payload = json.loads(result.stdout)
    duration = payload.get("format", {}).get("duration")
    try:
        return round(float(duration))
    except (TypeError, ValueError):
        return None


def _to_int(value: object) -> int | None:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
