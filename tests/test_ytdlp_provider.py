from media_resolver.core.models import MediaIntent, QualityMode
from media_resolver.providers.ytdlp_provider import YtDlpProvider


def _audio_info(**overrides):
    info = {
        "title": "Second Song",
        "artist": "Album Artist",
        "album": "Album",
        "formats": [
            {
                "format_id": "251",
                "acodec": "opus",
                "vcodec": "none",
                "ext": "webm",
                "abr": 160,
            }
        ],
        "webpage_url": "https://music.youtube.com/watch?v=second",
    }
    info.update(overrides)
    return info


def test_ytdlp_album_entry_uses_playlist_index_as_track_number_fallback():
    provider = object.__new__(YtDlpProvider)

    candidate = provider._candidate_from_info(
        _audio_info(playlist_index=2),
        MediaIntent.AUDIO,
        QualityMode.BEST_AVAILABLE,
    )

    assert candidate is not None
    assert candidate.metadata.track_number == 2
    assert candidate.metadata.playlist_index == 2


def test_ytdlp_explicit_track_number_wins_over_playlist_index():
    provider = object.__new__(YtDlpProvider)

    candidate = provider._candidate_from_info(
        _audio_info(track_number=7, playlist_index=2),
        MediaIntent.AUDIO,
        QualityMode.BEST_AVAILABLE,
    )

    assert candidate is not None
    assert candidate.metadata.track_number == 7
    assert candidate.metadata.playlist_index == 2
