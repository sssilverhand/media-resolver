from media_resolver.app import _policy_for_intent, _policy_from_sources
from media_resolver.core.models import MediaIntent, SourcePolicy
from media_resolver.metadata.public import _large_artwork_url
from media_resolver.providers.ytdlp_provider import _targets_for_query


def test_primary_policy_keeps_alternatives_off():
    policy = _policy_from_sources("primary")

    assert policy.spotify
    assert policy.tidal
    assert policy.youtube
    assert not policy.soundcloud
    assert policy.audius
    assert policy.bandcamp
    assert policy.direct
    assert policy.local
    assert not policy.archive
    assert not policy.telegram
    assert not policy.torrents


def test_allow_alternatives_enables_public_and_custom_sources():
    policy = _policy_from_sources("primary", allow_alternatives=True)

    assert policy.spotify
    assert policy.tidal
    assert policy.soundcloud
    assert policy.archive
    assert policy.telegram
    assert policy.custom
    assert not policy.torrents


def test_explicit_archive_source_does_not_enable_soundcloud():
    policy = _policy_from_sources("archive", allow_alternatives=True)

    assert policy.archive
    assert not policy.soundcloud
    assert not policy.youtube


def test_large_artwork_url_uses_album_art_resolution():
    url = "https://is1-ssl.mzstatic.com/image/thumb/Music126/v4/example/100x100bb.jpg"

    assert _large_artwork_url(url).endswith("/1200x1200bb.jpg")


def test_audio_search_prefers_youtube_music_before_regular_youtube():
    targets = _targets_for_query(
        "the weeknd starboy",
        SourcePolicy(soundcloud=True),
        MediaIntent.AUDIO,
    )

    assert targets[0].startswith("https://music.youtube.com/search?q=")
    assert targets[1].startswith("ytsearch5:")
    assert targets[2].startswith("scsearch5:")


def test_video_and_text_search_are_youtube_only_targets():
    policy = SourcePolicy(youtube=True, soundcloud=True)

    assert _targets_for_query("starboy video", policy, MediaIntent.VIDEO) == [
        "ytsearch10:starboy video"
    ]
    assert _targets_for_query("starboy subtitles", policy, MediaIntent.TEXT) == [
        "ytsearch10:starboy subtitles"
    ]


def test_video_and_text_cli_policy_ignore_alternative_sources():
    for intent in (MediaIntent.VIDEO, MediaIntent.TEXT):
        policy = _policy_for_intent(intent, "all", allow_alternatives=True, allow_torrents=True)

        assert policy.youtube
        assert not policy.soundcloud
        assert not policy.archive
        assert not policy.direct
        assert not policy.local
        assert not policy.torrents
