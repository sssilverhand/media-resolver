from media_resolver.core.models import MediaMetadata
from media_resolver.core.naming import NamingTemplate


def test_naming_template_sanitizes_windows_characters():
    naming = NamingTemplate("{artist}/{track_number:02} - {title}.{ext}")
    metadata = MediaMetadata(artist="AC/DC", title='Bad <Title>?', ext="flac", track_number=3)

    assert naming.render(metadata) == "AC_DC/03 - Bad _Title_.flac"


def test_naming_template_keeps_template_folders_but_not_metadata_slashes():
    naming = NamingTemplate("{album_artist}/{album}/{track_number:02} - {artist} - {title}.{ext}")
    metadata = MediaMetadata(
        album_artist="AC/DC",
        album="Back/In Black",
        artist="A/B",
        title="Left/Right",
        ext="mp3",
        track_number=1,
    )

    assert naming.render(metadata) == "AC_DC/Back_In Black/01 - A_B - Left_Right.mp3"
