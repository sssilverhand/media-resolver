from __future__ import annotations

from media_resolver.core.models import QualityClaim, QualityMode


def quality_satisfies(claim: QualityClaim, mode: QualityMode) -> bool:
    codec = claim.codec.lower()
    container = claim.container.lower()
    if mode in {QualityMode.BEST_AVAILABLE, QualityMode.METADATA_ONLY}:
        return True
    if mode == QualityMode.OPUS_NATIVE:
        return "opus" in codec or container == "opus"
    if mode == QualityMode.MP3_320_REAL:
        return ("mp3" in codec or container == "mp3") and (claim.bitrate_kbps or 0) >= 300
    if mode == QualityMode.FLAC_REAL:
        return claim.is_lossless and (codec == "flac" or container == "flac")
    if mode == QualityMode.HI_RES_REAL:
        return claim.is_lossless and (claim.bit_depth or 0) >= 24 and (
            claim.sample_rate_hz or 0
        ) >= 48000
    return True
