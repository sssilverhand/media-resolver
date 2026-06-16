from __future__ import annotations

from dataclasses import replace
import os
from pathlib import Path
import re
from urllib.parse import urlparse

import musicbrainzngs
import requests

from media_resolver.core.models import MediaIntent, MediaMetadata

IDENTITY_AUTHORITY_SOURCES = {"Spotify", "Tidal", "Apple Search", "Genius", "MusicBrainz"}


class PublicMetadataResolver:
    def __init__(self) -> None:
        musicbrainzngs.set_useragent(
            "media-resolver",
            "0.1.0",
            "https://github.com/local/media-resolver",
        )

    def search(self, query: str, intent: MediaIntent, limit: int = 5) -> list[MediaMetadata]:
        if intent == MediaIntent.VIDEO or Path(query).expanduser().exists():
            return []

        fetch_limit = max(limit * 5, 25)
        results: list[MediaMetadata] = []
        if intent in {MediaIntent.AUDIO, MediaIntent.METADATA, MediaIntent.TEXT}:
            if _looks_like_url(query):
                results.extend(self._metadata_from_spotify_url(query, limit=fetch_limit))
                return results[:limit]
            results.extend(self._search_spotify(query, limit=fetch_limit))
            results.extend(self._search_tidal(query, limit=fetch_limit))
            results.extend(self._search_itunes(query, limit=fetch_limit))
            results.extend(self._search_genius(query, limit=fetch_limit))
            results.extend(self._search_musicbrainz(query, limit=fetch_limit))
            results.extend(self._search_lrclib(query, limit=fetch_limit))
        return _rank(query, _dedupe(results))[:limit]

    def enrich(self, metadata: MediaMetadata, matches: list[MediaMetadata]) -> MediaMetadata:
        if not matches:
            return metadata

        best = _best_metadata_match(metadata, matches)
        authoritative_identity = best.source in IDENTITY_AUTHORITY_SOURCES
        extra = {**best.extra, **metadata.extra}
        extra["metadata_authority"] = best.source
        if best.duration_seconds:
            extra["official_duration_seconds"] = best.duration_seconds
        if "is_explicit" in best.extra:
            extra["official_explicit"] = best.extra["is_explicit"]

        if authoritative_identity:
            return replace(
                metadata,
                title=_authoritative(best.title, metadata.title),
                artist=_authoritative(best.artist, metadata.artist),
                album=_authoritative(best.album, metadata.album),
                album_artist=_authoritative(best.album_artist, metadata.album_artist),
                year=_authoritative(best.year, metadata.year),
                track_number=best.track_number or metadata.track_number,
                disc_number=best.disc_number or metadata.disc_number,
                source=metadata.source,
                isrc=_authoritative(best.isrc, metadata.isrc),
                duration_seconds=metadata.duration_seconds,
                extra=extra,
            )

        return replace(
            metadata,
            title=_prefer(metadata.title, best.title),
            artist=_prefer(metadata.artist, best.artist),
            album=_prefer(metadata.album, best.album),
            album_artist=_prefer(metadata.album_artist, best.album_artist),
            year=_prefer(metadata.year, best.year),
            track_number=metadata.track_number or best.track_number,
            source=metadata.source,
            isrc=_prefer(metadata.isrc, best.isrc),
            duration_seconds=metadata.duration_seconds,
            extra=extra,
        )

    def _search_spotify(self, query: str, limit: int) -> list[MediaMetadata]:
        client = _spotify_client()
        if client is None:
            return []

        try:
            payload = client.search(q=query, type="track", limit=min(limit, 50))
        except Exception:
            return []

        items: list[MediaMetadata] = []
        tracks = payload.get("tracks", {}).get("items", [])
        for track in tracks:
            album = track.get("album") or {}
            artists = track.get("artists") or []
            album_artists = album.get("artists") or artists
            artist = _spotify_artists(artists) or "Unknown Artist"
            album_artist = _spotify_artists(album_artists) or artist
            images = album.get("images") or []
            release_date = str(album.get("release_date") or "")
            external_ids = track.get("external_ids") or {}
            external_urls = track.get("external_urls") or {}
            items.append(
                _metadata_from_spotify_track(
                    track,
                    fallback_title=query,
                    album_artist=album_artist,
                    artist=artist,
                    release_date=release_date,
                    images=images,
                    external_ids=external_ids,
                    external_urls=external_urls,
                )
            )
        return items

    def _metadata_from_spotify_url(self, query: str, limit: int) -> list[MediaMetadata]:
        client = _spotify_client()
        if client is None:
            return []

        kind, spotify_id = _spotify_url_parts(query)
        if not kind or not spotify_id:
            return []

        try:
            if kind == "track":
                return [_metadata_from_spotify_track(client.track(spotify_id), fallback_title=query)]
            if kind == "album":
                album = client.album(spotify_id)
                tracks = client.album_tracks(spotify_id, limit=min(limit, 50)).get("items", [])
                return [
                    _metadata_from_spotify_track({**track, "album": album}, fallback_title=query)
                    for track in tracks[:limit]
                ]
            if kind == "playlist":
                payload = client.playlist_tracks(
                    spotify_id,
                    limit=min(limit, 50),
                    fields="items(track(id,name,artists,album,external_ids,external_urls,track_number,disc_number))",
                )
                tracks = [
                    item.get("track")
                    for item in payload.get("items", [])
                    if item.get("track") is not None
                ]
                return [
                    _metadata_from_spotify_track(track, fallback_title=query)
                    for track in tracks[:limit]
                ]
        except Exception:
            return []
        return []

    def _search_tidal(self, query: str, limit: int) -> list[MediaMetadata]:
        api = _tiddl_api()
        if api is None:
            return []

        try:
            payload = api.getSearch(query)
        except Exception:
            return []

        items: list[MediaMetadata] = []
        for track in payload.tracks.items[:limit]:
            items.append(_metadata_from_tiddl_track(track))
        return items

    def _search_musicbrainz(self, query: str, limit: int) -> list[MediaMetadata]:
        try:
            payload = musicbrainzngs.search_recordings(query=query, limit=limit)
        except Exception:
            return []

        items: list[MediaMetadata] = []
        for recording in payload.get("recording-list", []):
            artist = _artist_credit(recording.get("artist-credit", []))
            release = (recording.get("release-list") or [{}])[0]
            year = str(release.get("date", ""))[:4]
            items.append(
                MediaMetadata(
                    title=recording.get("title") or query,
                    artist=artist or "Unknown Artist",
                    album_artist=artist or "Unknown Artist",
                    album=release.get("title") or "Unknown Album",
                    year=year,
                    source="MusicBrainz",
                    isrc=(recording.get("isrc-list") or [""])[0],
                    extra={
                        "musicbrainz_recording_id": recording.get("id", ""),
                        "musicbrainz_release_id": release.get("id", ""),
                    },
                )
            )
        return items

    def _search_itunes(self, query: str, limit: int) -> list[MediaMetadata]:
        try:
            response = requests.get(
                "https://itunes.apple.com/search",
                params={"term": query, "entity": "song", "limit": limit},
                timeout=8,
            )
            response.raise_for_status()
            payload = response.json()
        except Exception:
            return []

        items: list[MediaMetadata] = []
        for item in payload.get("results", [])[:limit]:
            artist = item.get("artistName") or "Unknown Artist"
            year = str(item.get("releaseDate", ""))[:4]
            items.append(
                MediaMetadata(
                    title=item.get("trackName") or query,
                    artist=artist,
                    album_artist=artist,
                    album=item.get("collectionName") or "Unknown Album",
                    year=year,
                    source="Apple Search",
                    ext="m4a",
                    duration_seconds=_duration_from_ms(item.get("trackTimeMillis")),
                    extra={
                        "apple_track_id": item.get("trackId"),
                        "apple_collection_id": item.get("collectionId"),
                        "artwork_url": _large_artwork_url(item.get("artworkUrl100", "")),
                        "is_explicit": item.get("trackExplicitness") == "explicit",
                    },
                )
            )
        return items

    def _search_genius(self, query: str, limit: int) -> list[MediaMetadata]:
        token = os.getenv("GENIUS_ACCESS_TOKEN") or os.getenv("GENIUS_API_TOKEN")
        if not token:
            return []

        try:
            response = requests.get(
                "https://api.genius.com/search",
                params={"q": query},
                headers={"Authorization": f"Bearer {token}"},
                timeout=8,
            )
            response.raise_for_status()
            payload = response.json()
        except Exception:
            return []

        items: list[MediaMetadata] = []
        for hit in payload.get("response", {}).get("hits", [])[:limit]:
            result = hit.get("result") or {}
            artist = (result.get("primary_artist") or {}).get("name") or "Unknown Artist"
            title = result.get("title") or query
            items.append(
                MediaMetadata(
                    title=title,
                    artist=artist,
                    album_artist=artist,
                    album="Unknown Album",
                    source="Genius",
                    duration_seconds=_duration_seconds(result.get("duration")),
                    extra={
                        "genius_id": result.get("id"),
                        "genius_url": result.get("url", ""),
                        "artwork_url": result.get("song_art_image_url")
                        or result.get("header_image_url")
                        or "",
                    },
                )
            )
        return items

    def _search_lrclib(self, query: str, limit: int) -> list[MediaMetadata]:
        try:
            response = requests.get(
                "https://lrclib.net/api/search",
                params={"q": query},
                timeout=8,
            )
            response.raise_for_status()
            payload = response.json()
        except Exception:
            return []

        items: list[MediaMetadata] = []
        for item in payload[:limit]:
            artist = item.get("artistName") or "Unknown Artist"
            items.append(
                MediaMetadata(
                    title=item.get("trackName") or query,
                    artist=artist,
                    album_artist=artist,
                    album=item.get("albumName") or "Unknown Album",
                    source="LRCLIB",
                    extra={
                        "lrclib_id": item.get("id"),
                        "lyrics_plain": item.get("plainLyrics") or "",
                        "lyrics_synced": item.get("syncedLyrics") or "",
                    },
                )
            )
        return items


def _best_metadata_match(metadata: MediaMetadata, matches: list[MediaMetadata]) -> MediaMetadata:
    if len(matches) == 1:
        return matches[0]

    wanted_index = metadata.track_number if metadata.track_number > 1 else metadata.playlist_index
    return max(matches, key=lambda item: _metadata_match_score(metadata, item, wanted_index))


def _metadata_match_score(
    metadata: MediaMetadata, candidate: MediaMetadata, wanted_index: int
) -> tuple[float, int]:
    score = 0.0
    if wanted_index > 0 and candidate.track_number == wanted_index:
        score += 8
    if _same_text(metadata.title, candidate.title):
        score += 10
    elif _contains_tokens(metadata.title, candidate.title):
        score += 4
    if _same_text(metadata.artist, candidate.artist):
        score += 5
    elif set(_tokens(metadata.artist)).intersection(_tokens(candidate.artist)):
        score += 2
    if _same_text(metadata.album, candidate.album):
        score += 2
    if metadata.duration_seconds and candidate.duration_seconds:
        diff = abs(metadata.duration_seconds - candidate.duration_seconds)
        if diff <= 2:
            score += 2
        elif diff <= 5:
            score += 1
    return score, -abs(candidate.track_number - wanted_index)


def _same_text(left: str, right: str) -> bool:
    return bool(left and right and _tokens(left) == _tokens(right))


def _contains_tokens(left: str, right: str) -> bool:
    left_tokens = set(_tokens(left))
    right_tokens = set(_tokens(right))
    return bool(
        left_tokens
        and right_tokens
        and (left_tokens <= right_tokens or right_tokens <= left_tokens)
    )


def _artist_credit(credits: list) -> str:
    names = []
    for credit in credits:
        if isinstance(credit, dict):
            artist = credit.get("artist") or {}
            name = artist.get("name") or credit.get("name")
            if name:
                names.append(name)
    return ", ".join(names)


def _prefer(current: str, candidate: str) -> str:
    if not current or current.startswith("Unknown"):
        return candidate
    return current


def _authoritative(candidate: str, fallback: str) -> str:
    return candidate or fallback


def _spotify_client():
    client_id = os.getenv("SPOTIPY_CLIENT_ID") or os.getenv("SPOTIFY_CLIENT_ID")
    client_secret = os.getenv("SPOTIPY_CLIENT_SECRET") or os.getenv("SPOTIFY_CLIENT_SECRET")
    if not client_id or not client_secret:
        return None
    try:
        import spotipy
        from spotipy.oauth2 import SpotifyClientCredentials

        return spotipy.Spotify(
            auth_manager=SpotifyClientCredentials(
                client_id=client_id,
                client_secret=client_secret,
            ),
            requests_timeout=8,
            retries=1,
        )
    except Exception:
        return None


def _spotify_artists(items: list[dict]) -> str:
    return ", ".join(item.get("name", "") for item in items if item.get("name"))


def _largest_spotify_image(images: list[dict]) -> str:
    if not images:
        return ""
    image = max(images, key=lambda item: int(item.get("height") or 0))
    return image.get("url") or ""


def _metadata_from_spotify_track(
    track: dict,
    fallback_title: str,
    album_artist: str = "",
    artist: str = "",
    release_date: str = "",
    images: list[dict] | None = None,
    external_ids: dict | None = None,
    external_urls: dict | None = None,
) -> MediaMetadata:
    album = track.get("album") or {}
    artists = track.get("artists") or []
    album_artists = album.get("artists") or artists
    artist = artist or _spotify_artists(artists) or "Unknown Artist"
    album_artist = album_artist or _spotify_artists(album_artists) or artist
    images = images if images is not None else album.get("images") or []
    release_date = release_date or str(album.get("release_date") or "")
    external_ids = external_ids if external_ids is not None else track.get("external_ids") or {}
    external_urls = external_urls if external_urls is not None else track.get("external_urls") or {}
    return MediaMetadata(
        title=track.get("name") or fallback_title,
        artist=artist,
        album_artist=album_artist,
        album=album.get("name") or "Unknown Album",
        year=release_date[:4],
        track_number=int(track.get("track_number") or 1),
        disc_number=int(track.get("disc_number") or 1),
        source="Spotify",
        isrc=external_ids.get("isrc") or "",
        duration_seconds=_duration_from_ms(track.get("duration_ms")),
        extra={
            "spotify_track_id": track.get("id"),
            "spotify_album_id": album.get("id"),
            "spotify_url": external_urls.get("spotify", ""),
            "artwork_url": _largest_spotify_image(images),
            "is_explicit": bool(track.get("explicit")),
        },
    )


def _spotify_url_parts(value: str) -> tuple[str, str]:
    parsed = urlparse(value)
    if "spotify.com" not in parsed.netloc.lower():
        return "", ""
    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) < 2:
        return "", ""
    if parts[0].startswith("intl-") and len(parts) >= 3:
        parts = parts[1:]
    if parts[0] not in {"track", "album", "playlist"}:
        return "", ""
    return parts[0], parts[1]


def _tiddl_api():
    try:
        from tiddl.api import TidalApi
        from tiddl.config import Config
    except Exception:
        return None

    try:
        config = Config.fromFile()
        auth = config.auth
        if not auth.token or not auth.user_id or not auth.country_code:
            return None
        return TidalApi(auth.token, auth.user_id, auth.country_code, omit_cache=config.omit_cache)
    except Exception:
        return None


def _metadata_from_tiddl_track(track) -> MediaMetadata:
    artist = _tiddl_artists(getattr(track, "artists", []))
    if not artist and getattr(track, "artist", None):
        artist = getattr(track.artist, "name", "")
    artist = artist or "Unknown Artist"
    album = getattr(track, "album", None)
    release_date = getattr(track, "streamStartDate", None)
    artwork_url = _tidal_artwork_url(getattr(album, "cover", "") if album else "")
    return MediaMetadata(
        title=getattr(track, "title", "") or "Tidal track",
        artist=artist,
        album_artist=artist,
        album=getattr(album, "title", "") if album else "Unknown Album",
        year=str(getattr(release_date, "year", "") or ""),
        track_number=int(getattr(track, "trackNumber", 1) or 1),
        disc_number=int(getattr(track, "volumeNumber", 1) or 1),
        source="Tidal",
        isrc=getattr(track, "isrc", "") or "",
        duration_seconds=_duration_seconds(
            getattr(track, "duration", None) or getattr(track, "durationInSeconds", None)
        ),
        extra={
            "tidal_track_id": getattr(track, "id", ""),
            "tidal_url": f"https://listen.tidal.com/track/{getattr(track, 'id', '')}",
            "artwork_url": artwork_url,
            "tidal_audio_quality": getattr(track, "audioQuality", ""),
            "is_explicit": bool(
                getattr(track, "explicit", False) or getattr(track, "explicitContent", False)
            ),
        },
    )


def _tiddl_artists(items) -> str:
    names = [getattr(item, "name", "") for item in items or []]
    return ", ".join(name for name in names if name)


def _duration_from_ms(value) -> int | None:
    try:
        seconds = round(float(value) / 1000)
    except (TypeError, ValueError):
        return None
    return seconds if seconds > 0 else None


def _duration_seconds(value) -> int | None:
    try:
        seconds = round(float(value))
    except (TypeError, ValueError):
        return None
    return seconds if seconds > 0 else None


def _tidal_artwork_url(uid: str, size: int = 1280) -> str:
    if not uid:
        return ""
    return f"https://resources.tidal.com/images/{uid.replace('-', '/')}/{size}x{size}.jpg"


def _dedupe(items: list[MediaMetadata]) -> list[MediaMetadata]:
    seen = set()
    deduped = []
    for item in items:
        key = (item.title.lower(), item.artist.lower(), item.album.lower())
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


def _rank(query: str, items: list[MediaMetadata]) -> list[MediaMetadata]:
    ranked = [
        item
        for item in items
        if _passes_basic_match(query, item) and _score(query, item) >= _minimum_score(query)
    ]
    return sorted(ranked, key=lambda item: _score(query, item), reverse=True)


def _score(query: str, item: MediaMetadata) -> float:
    query_tokens = _tokens(query)
    title_tokens = _tokens(item.title)
    artist_tokens = _tokens(item.artist)
    album_tokens = _tokens(item.album)
    haystack_tokens = set(title_tokens + artist_tokens + album_tokens)

    if not query_tokens:
        return 0

    score = 0.0
    score += 6 * _coverage(query_tokens, artist_tokens)
    score += 5 * _coverage(query_tokens, title_tokens)
    score += 1.5 * _coverage(query_tokens, album_tokens)
    score += 2 * _coverage(query_tokens, list(haystack_tokens))

    title = item.title.lower()
    artist = item.artist.lower()
    query_lower = query.lower()

    if title in query_lower or query_lower in f"{artist} {title}".lower():
        score += 5

    if len(title_tokens) <= max(2, len(query_tokens)):
        score += 2
    else:
        score -= min(len(title_tokens) - len(query_tokens), 8) * 0.5

    unwanted = {
        "karaoke",
        "instrumental",
        "tribute",
        "parody",
        "remix",
        "cover",
        "slowed",
        "reverb",
        "live",
    }
    requested_unwanted = unwanted.intersection(query_tokens)
    for word in unwanted - requested_unwanted:
        if word in title_tokens or word in artist_tokens or word in album_tokens:
            score -= 8

    if item.source == "Apple Search":
        score += 4
    elif item.source == "Genius":
        score += 3.5
    elif item.source == "MusicBrainz":
        score += 1.5
    elif item.source == "Tidal":
        score += 4.5
    elif item.source == "Spotify":
        score += 5
    return score


def _passes_basic_match(query: str, item: MediaMetadata) -> bool:
    if len(_tokens(query)) < 3:
        return True
    query_tokens = _significant_tokens(query)
    if len(query_tokens) < 2:
        return True

    title_coverage = _coverage(query_tokens, _significant_tokens(item.title))
    artist_coverage = _coverage(query_tokens, _significant_tokens(item.artist))
    return title_coverage > 0 and artist_coverage > 0


def _minimum_score(query: str) -> float:
    token_count = len(_tokens(query))
    if token_count >= 3:
        return 5.0
    return 2.0


def _coverage(query_tokens: list[str], candidate_tokens: list[str]) -> float:
    if not query_tokens:
        return 0
    candidate = set(candidate_tokens)
    return sum(1 for token in query_tokens if token in candidate) / len(query_tokens)


def _tokens(value: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", value.lower())


def _significant_tokens(value: str) -> list[str]:
    stopwords = {"a", "an", "and", "feat", "ft", "the", "with"}
    return [token for token in _tokens(value) if token not in stopwords]


def _looks_like_url(value: str) -> bool:
    parsed = urlparse(value)
    return bool(parsed.scheme and parsed.netloc)


def _large_artwork_url(url: str) -> str:
    return re.sub(r"/\d+x\d+bb\.", "/1200x1200bb.", url or "")
