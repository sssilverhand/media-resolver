from __future__ import annotations

from dataclasses import dataclass

from media_resolver.core.models import MediaMetadata


@dataclass(frozen=True)
class AlbumDiff:
    removed: list[MediaMetadata]
    added: list[MediaMetadata]
    changed: list[tuple[MediaMetadata, MediaMetadata]]


def compare_tracklists(old: list[MediaMetadata], new: list[MediaMetadata]) -> AlbumDiff:
    old_by_key = {_track_key(track): track for track in old}
    new_by_key = {_track_key(track): track for track in new}

    removed = [track for key, track in old_by_key.items() if key not in new_by_key]
    added = [track for key, track in new_by_key.items() if key not in old_by_key]
    changed: list[tuple[MediaMetadata, MediaMetadata]] = []
    for key, old_track in old_by_key.items():
        new_track = new_by_key.get(key)
        if new_track and old_track.version != new_track.version:
            changed.append((old_track, new_track))
    return AlbumDiff(removed=removed, added=added, changed=changed)


def _track_key(track: MediaMetadata) -> tuple[str, str]:
    return (track.artist.lower().strip(), track.title.lower().strip())
