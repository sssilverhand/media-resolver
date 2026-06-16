from __future__ import annotations

from dataclasses import dataclass

import musicbrainzngs


@dataclass(frozen=True)
class ReleaseVersion:
    title: str
    artist: str
    date: str
    country: str
    status: str
    format: str
    track_count: int
    source_id: str


class ReleaseResolver:
    def __init__(self) -> None:
        musicbrainzngs.set_useragent(
            "media-resolver",
            "0.1.0",
            "https://github.com/local/media-resolver",
        )

    def search_versions(self, query: str, limit: int = 20) -> list[ReleaseVersion]:
        try:
            payload = musicbrainzngs.search_releases(query=query, limit=limit)
        except Exception:
            return []

        versions: list[ReleaseVersion] = []
        for release in payload.get("release-list", []):
            artist = _artist_credit(release.get("artist-credit", []))
            medium_list = release.get("medium-list") or []
            track_count = 0
            formats = []
            for medium in medium_list:
                track_count += int(medium.get("track-count") or 0)
                if medium.get("format"):
                    formats.append(medium["format"])
            versions.append(
                ReleaseVersion(
                    title=release.get("title") or query,
                    artist=artist or "Unknown Artist",
                    date=release.get("date", ""),
                    country=release.get("country", ""),
                    status=release.get("status", ""),
                    format=", ".join(formats),
                    track_count=track_count,
                    source_id=release.get("id", ""),
                )
            )
        return versions


def _artist_credit(credits: list) -> str:
    names = []
    for credit in credits:
        if isinstance(credit, dict):
            artist = credit.get("artist") or {}
            name = artist.get("name") or credit.get("name")
            if name:
                names.append(name)
    return ", ".join(names)
