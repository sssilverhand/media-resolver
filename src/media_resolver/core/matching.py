from __future__ import annotations

import re


VERSION_PATTERNS = {
    "cover": "cover",
    "remix": "remix",
    "live": "live",
    "instrumental": "instrumental",
    "karaoke": "karaoke",
    "tribute": "tribute",
    "parody": "parody",
    "slowed": "slowed",
    "reverb": "reverb",
    "8d": "8d",
    "16d": "16d",
    "128kbps": "128kbps",
    "bass boosted": "bass boosted",
    "censored": "censored",
    "censor": "censored",
    "clean": "clean",
    "clean version": "clean",
    "dancehall": "dancehall",
    "drum cover": "drum cover",
    "edited": "edited",
    "guitar cover": "guitar cover",
    "music video": "video edit",
    "nightcore": "nightcore",
    "official video": "video edit",
    "piano cover": "piano cover",
    "radio edit": "radio edit",
    "radio version": "radio edit",
    "refix": "refix",
    "sped up": "sped up",
    "video edit": "video edit",
    "youtube": "youtube",
}

CLEAN_OR_EDITED_FLAGS = {"censored", "clean", "edited", "radio edit", "video edit"}


def version_flags(value: str) -> tuple[str, ...]:
    normalized = re.sub(r"[^a-z0-9]+", " ", value.lower())
    flags = [flag for pattern, flag in VERSION_PATTERNS.items() if pattern in normalized]
    return tuple(sorted(flags))


def version_note(flags: tuple[str, ...]) -> str:
    if not flags:
        return ""
    return "alternate version: " + ", ".join(flags)
