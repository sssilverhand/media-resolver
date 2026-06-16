from __future__ import annotations

from urllib.parse import urlparse

from media_resolver.core.matching import CLEAN_OR_EDITED_FLAGS
from media_resolver.core.models import MediaCandidate, MediaIntent, QualityMode, SourcePolicy
from media_resolver.core.tools import ToolRegistry
from media_resolver.metadata.public import PublicMetadataResolver
from media_resolver.providers.archive_provider import ArchiveProvider
from media_resolver.providers.audius_provider import AudiusProvider
from media_resolver.providers.bandcamp_provider import BandcampProvider
from media_resolver.providers.direct_provider import DirectProvider
from media_resolver.providers.local_provider import LocalProvider
from media_resolver.providers.tidal_provider import TidalProvider
from media_resolver.providers.torrent_provider import TorrentProvider
from media_resolver.providers.ytdlp_provider import YtDlpProvider


def resolve_candidates(
    query: str,
    intent: MediaIntent,
    quality: QualityMode,
    policy: SourcePolicy,
    registry: ToolRegistry,
    enrich_metadata: bool = True,
) -> list[MediaCandidate]:
    resolver = PublicMetadataResolver()
    metadata_matches = resolver.search(query, intent)
    provider_queries = _provider_queries(query, metadata_matches)

    candidates: list[MediaCandidate] = []
    for provider in [
        LocalProvider(registry),
        DirectProvider(registry),
        TidalProvider(registry),
        TorrentProvider(registry),
        ArchiveProvider(registry),
        AudiusProvider(registry),
        BandcampProvider(registry),
        YtDlpProvider(registry),
    ]:
        for provider_query in provider_queries:
            candidates.extend(provider.inspect(provider_query, intent, quality, policy))

    if candidates and metadata_matches:
        for candidate in candidates:
            if enrich_metadata:
                candidate.metadata = resolver.enrich(candidate.metadata, metadata_matches)
            else:
                _attach_official_hints(candidate, metadata_matches[0])
    return sorted(candidates, key=_candidate_rank, reverse=True)


def _candidate_rank(candidate: MediaCandidate) -> tuple[float, int, int]:
    quality = candidate.quality
    if quality.is_lossless:
        quality_rank = 10_000 + (quality.bit_depth or 0) * 100 + (quality.sample_rate_hz or 0)
    else:
        codec = quality.codec.lower()
        codec_rank = 0
        if "opus" in codec:
            codec_rank = 5_000
        elif "mp4a" in codec or "aac" in codec:
            codec_rank = 4_000
        elif "ogg" in codec or "vorbis" in codec:
            codec_rank = 3_500
        elif "mp3" in codec:
            codec_rank = 3_000
        quality_rank = codec_rank + (quality.bitrate_kbps or 0)
    verified = 1 if quality.is_real else 0
    original_fit = _original_fit_score(candidate)
    return (candidate.confidence + original_fit, verified, quality_rank)


def _original_fit_score(candidate: MediaCandidate) -> float:
    flags = set(candidate.metadata.extra.get("version_flags") or ())
    score = 0.0
    if flags:
        score -= 0.35
    if flags.intersection(CLEAN_OR_EDITED_FLAGS):
        score -= 0.6

    official_duration = _to_int(candidate.metadata.extra.get("official_duration_seconds"))
    candidate_duration = _to_int(candidate.metadata.duration_seconds)
    if official_duration and candidate_duration:
        diff = abs(candidate_duration - official_duration)
        if diff <= 2:
            score += 0.15
        elif diff <= 5:
            score += 0.08
        elif diff >= 20:
            score -= 0.25
        elif diff >= 10:
            score -= 0.12

    if candidate.metadata.extra.get("official_explicit") and flags.intersection(
        CLEAN_OR_EDITED_FLAGS
    ):
        score -= 0.25
    return score


def _to_int(value) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _provider_queries(query: str, metadata_matches) -> list[str]:
    queries = [query]
    if not _looks_like_metadata_url(query) or not metadata_matches:
        return queries

    for item in metadata_matches[:10]:
        search_query = " ".join(part for part in [item.artist, item.title] if part).strip()
        if search_query and search_query not in queries:
            queries.append(search_query)
    return queries


def _attach_official_hints(candidate: MediaCandidate, official) -> None:
    if official.duration_seconds:
        candidate.metadata.extra["official_duration_seconds"] = official.duration_seconds
    if "is_explicit" in official.extra:
        candidate.metadata.extra["official_explicit"] = official.extra["is_explicit"]
    if official.isrc:
        candidate.metadata.extra["official_isrc"] = official.isrc


def _looks_like_metadata_url(value: str) -> bool:
    parsed = urlparse(value)
    if not parsed.scheme or not parsed.netloc:
        return False
    host = parsed.netloc.lower()
    return "spotify.com" in host
