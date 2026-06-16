from __future__ import annotations

from pathlib import Path

from media_resolver.core.models import MediaMetadata


def write_lyrics_sidecars(media_path: Path, metadata: MediaMetadata) -> list[Path]:
    created: list[Path] = []
    synced = metadata.extra.get("lyrics_synced")
    plain = metadata.extra.get("lyrics_plain")

    if synced:
        target = media_path.with_suffix(".lrc")
        target.write_text(str(synced), encoding="utf-8")
        created.append(target)
    elif plain:
        target = media_path.with_suffix(".lyrics.txt")
        target.write_text(str(plain), encoding="utf-8")
        created.append(target)
    return created
