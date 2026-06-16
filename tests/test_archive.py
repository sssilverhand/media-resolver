from media_resolver.versions.archive_plan import original_query
from media_resolver.versions.release_resolver import ReleaseVersion


def test_original_query_uses_earliest_known_release():
    versions = [
        ReleaseVersion(
            title="Album Revised",
            artist="Artist",
            date="2024-01-01",
            country="US",
            status="Official",
            format="Digital Media",
            track_count=10,
            source_id="new",
        ),
        ReleaseVersion(
            title="Album",
            artist="Artist",
            date="1999-01-01",
            country="US",
            status="Official",
            format="CD",
            track_count=10,
            source_id="old",
        ),
    ]

    assert original_query("Artist Album", versions) == "Artist Album"


def test_original_query_falls_back_to_user_query_without_versions():
    assert original_query("Artist Track", []) == "Artist Track"


def test_original_query_ignores_irrelevant_earliest_release():
    versions = [
        ReleaseVersion(
            title="Test... Test...",
            artist="The Panics",
            date="1980",
            country="US",
            status="Official",
            format="Vinyl",
            track_count=2,
            source_id="partial",
        ),
        ReleaseVersion(
            title="Test Tone / Half Known",
            artist="Quadra",
            date="2001",
            country="CA",
            status="Official",
            format='12" Vinyl',
            track_count=2,
            source_id="relevant",
        ),
    ]

    assert original_query("test tone", versions) == "Quadra Test Tone / Half Known"
