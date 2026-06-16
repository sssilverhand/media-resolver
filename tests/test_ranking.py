from media_resolver.core.models import MediaCandidate, MediaMetadata, QualityClaim
from media_resolver.core.resolver import _candidate_rank
from media_resolver.providers.archive_provider import _confidence


def _candidate(codec: str, bitrate: int) -> MediaCandidate:
    return MediaCandidate(
        source="test",
        url="https://example.test/audio",
        metadata=MediaMetadata(title="Track"),
        quality=QualityClaim(codec=codec, bitrate_kbps=bitrate, is_real=True),
        confidence=0.9,
    )


def _version_candidate(flags: tuple[str, ...]) -> MediaCandidate:
    metadata = MediaMetadata(title="Track", extra={"version_flags": flags})
    return MediaCandidate(
        source="test",
        url="https://example.test/audio",
        metadata=metadata,
        quality=QualityClaim(codec="mp3", bitrate_kbps=320, is_real=True),
        confidence=0.9,
    )


def _duration_candidate(duration: int, flags: tuple[str, ...] = ()) -> MediaCandidate:
    metadata = MediaMetadata(
        title="Track",
        duration_seconds=duration,
        extra={"official_duration_seconds": 230, "version_flags": flags},
    )
    return MediaCandidate(
        source="test",
        url="https://example.test/audio",
        metadata=metadata,
        quality=QualityClaim(codec="opus", bitrate_kbps=147, is_real=True),
        confidence=0.9,
    )


def test_opus_ranks_above_aac_when_confidence_matches():
    assert _candidate_rank(_candidate("opus", 147)) > _candidate_rank(_candidate("mp4a", 160))


def test_archive_confidence_rejects_single_token_matches_for_specific_queries():
    assert _confidence("playboi carti magnolia", "Magnolia-only compilation") == 0.0
    assert _confidence("playboi carti magnolia", "23 Playboi Carti - Magnolia") > 0.0


def test_alternate_versions_rank_below_main_versions():
    assert _candidate_rank(_version_candidate(())) > _candidate_rank(
        _version_candidate(("cover",))
    )


def test_original_duration_ranks_above_video_edit():
    assert _candidate_rank(_duration_candidate(230)) > _candidate_rank(
        _duration_candidate(273, ("video edit",))
    )
