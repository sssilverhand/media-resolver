from __future__ import annotations

from dataclasses import replace
from typing import Iterable

from media_resolver.core.models import MediaMetadata


def merge_metadata(items: Iterable[MediaMetadata]) -> MediaMetadata | None:
    values = list(items)
    if not values:
        return None

    base = values[0]
    merged = base
    for item in values[1:]:
        merged = replace(
            merged,
            title=_prefer(merged.title, item.title),
            artist=_prefer(merged.artist, item.artist),
            album=_prefer(merged.album, item.album),
            album_artist=_prefer(merged.album_artist, item.album_artist),
            year=_prefer(merged.year, item.year),
            isrc=_prefer(merged.isrc, item.isrc),
        )
    return merged


def _prefer(current: str, candidate: str) -> str:
    if not current or current.startswith("Unknown"):
        return candidate
    return current
