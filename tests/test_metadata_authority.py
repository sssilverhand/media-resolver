from media_resolver.core.models import MediaMetadata
from media_resolver.metadata.public import PublicMetadataResolver, _rank, _spotify_url_parts


def test_authoritative_metadata_replaces_archive_identity_fields():
    resolver = PublicMetadataResolver()
    archive_metadata = MediaMetadata(
        title="Timeless (Audio)",
        artist="archive uploader",
        album_artist="archive uploader",
        album="archive item",
        source="Archive.org",
        ext="flac",
    )
    spotify_match = MediaMetadata(
        title="Timeless",
        artist="The Weeknd, Playboi Carti",
        album_artist="The Weeknd",
        album="Timeless",
        year="2024",
        track_number=1,
        source="Spotify",
        isrc="USUG12406536",
        extra={"artwork_url": "https://i.scdn.co/image/example"},
    )

    enriched = resolver.enrich(archive_metadata, [spotify_match])

    assert enriched.title == "Timeless"
    assert enriched.artist == "The Weeknd, Playboi Carti"
    assert enriched.album == "Timeless"
    assert enriched.source == "Archive.org"
    assert enriched.ext == "flac"
    assert enriched.isrc == "USUG12406536"
    assert enriched.extra["metadata_authority"] == "Spotify"


def test_album_metadata_enrichment_matches_by_playlist_index():
    resolver = PublicMetadataResolver()
    youtube_metadata = MediaMetadata(
        title="Second Song",
        artist="Album Artist",
        album="Album",
        source="YouTube Music",
        playlist_index=2,
    )
    first_spotify_match = MediaMetadata(
        title="First Song",
        artist="Album Artist",
        album="Album",
        track_number=1,
        source="Spotify",
    )
    second_spotify_match = MediaMetadata(
        title="Second Song",
        artist="Album Artist",
        album="Album",
        track_number=2,
        source="Spotify",
    )

    enriched = resolver.enrich(youtube_metadata, [first_spotify_match, second_spotify_match])

    assert enriched.title == "Second Song"
    assert enriched.track_number == 2


def test_spotify_url_parts_support_tracks_albums_and_playlists():
    assert _spotify_url_parts("https://open.spotify.com/track/abc123?si=x") == ("track", "abc123")
    assert _spotify_url_parts("https://open.spotify.com/album/album123") == ("album", "album123")
    assert _spotify_url_parts("https://open.spotify.com/playlist/pl123") == (
        "playlist",
        "pl123",
    )


def test_official_metadata_rejects_stopword_musicbrainz_false_positive():
    bad_musicbrainz = MediaMetadata(
        title="Starboy",
        artist="Tell The Wolves I'm Home",
        album="Now 2017 Vol. 1",
        year="2017",
        source="MusicBrainz",
    )
    apple = MediaMetadata(
        title="Starboy (feat. Daft Punk)",
        artist="The Weeknd",
        album="Starboy",
        year="2016",
        source="Apple Search",
    )

    ranked = _rank("the weeknd starboy", [bad_musicbrainz, apple])

    assert ranked == [apple]
