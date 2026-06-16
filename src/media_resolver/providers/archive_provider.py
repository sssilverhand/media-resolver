from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import quote

import requests

from media_resolver.core.models import (
    MediaCandidate,
    MediaIntent,
    MediaMetadata,
    QualityClaim,
    QualityMode,
    SourcePolicy,
)
from media_resolver.core.naming import NamingTemplate
from media_resolver.core.quality import quality_satisfies
from media_resolver.core.tools import ToolRegistry
from media_resolver.providers.direct_provider import DirectProvider


class ArchiveProvider:
    def __init__(self, registry: ToolRegistry) -> None:
        self.registry = registry
        self.direct = DirectProvider(registry)

    def inspect(
        self,
        query: str,
        intent: MediaIntent,
        quality: QualityMode,
        policy: SourcePolicy,
    ) -> list[MediaCandidate]:
        if not policy.archive or intent not in {MediaIntent.AUDIO, MediaIntent.METADATA}:
            return []

        try:
            response = requests.get(
                "https://archive.org/advancedsearch.php",
                params={
                    "q": f'({query}) AND mediatype:"audio"',
                    "fl[]": ["identifier", "title", "creator", "year"],
                    "rows": 8,
                    "page": 1,
                    "output": "json",
                },
                timeout=12,
            )
            response.raise_for_status()
            docs = response.json().get("response", {}).get("docs", [])
        except Exception:
            return []

        candidates: list[MediaCandidate] = []
        for doc in docs:
            identifier = doc.get("identifier")
            if not identifier:
                continue
            candidates.extend(self._files_for_item(doc, query, quality))
        return candidates[:10]

    def download(
        self,
        candidate: MediaCandidate,
        output_dir: Path,
        naming: NamingTemplate,
    ) -> Path:
        return self.direct.download(candidate, output_dir, naming)

    def _files_for_item(self, doc: dict, query: str, quality: QualityMode) -> list[MediaCandidate]:
        identifier = doc["identifier"]
        try:
            metadata = requests.get(
                f"https://archive.org/metadata/{quote(identifier)}",
                timeout=12,
            )
            metadata.raise_for_status()
            files = metadata.json().get("files", [])
        except Exception:
            return []

        title = _first(doc.get("title")) or identifier
        artist = _first(doc.get("creator")) or "Unknown Artist"
        year = str(_first(doc.get("year")) or "")

        candidates: list[MediaCandidate] = []
        for file in files:
            name = file.get("name", "")
            confidence = _confidence(query, title, artist, identifier, name)
            if confidence < 0.5:
                continue
            ext = Path(name).suffix.lower().lstrip(".")
            claim = _claim_for_archive_file(file, ext)
            if claim is None or not _quality_allowed(claim, quality):
                continue
            url = f"https://archive.org/download/{quote(identifier)}/{quote(name)}"
            media_metadata = MediaMetadata(
                title=Path(name).stem or title,
                artist=artist,
                album_artist=artist,
                album=title,
                year=year[:4],
                source="Archive.org",
                ext=ext,
                duration_seconds=_duration_seconds(file.get("length")),
                extra={"archive_identifier": identifier},
            )
            candidates.append(
                MediaCandidate(
                    source="Archive.org",
                    url=url,
                    metadata=media_metadata,
                    quality=claim,
                    confidence=confidence,
                    provider_payload={"provider": self, "quality_mode": quality.value},
                )
            )
        return sorted(candidates, key=lambda item: _quality_rank(item.quality), reverse=True)


def _claim_for_archive_file(file: dict, ext: str) -> QualityClaim | None:
    if ext not in {"flac", "wav", "mp3", "ogg", "opus", "m4a"}:
        return None
    bitrate = _int_or_none(file.get("bitrate"))
    sample_rate = _int_or_none(file.get("sample_rate"))
    lossless = ext in {"flac", "wav"}
    return QualityClaim(
        codec=ext,
        container=ext,
        bitrate_kbps=bitrate,
        sample_rate_hz=sample_rate,
        is_lossless=lossless,
        is_real=True,
    )


def _quality_allowed(claim: QualityClaim, mode: QualityMode) -> bool:
    return quality_satisfies(claim, mode)


def _quality_rank(claim: QualityClaim) -> int:
    if claim.is_lossless:
        return 10_000 + (claim.sample_rate_hz or 0)
    return claim.bitrate_kbps or 0


def _first(value):
    if isinstance(value, list):
        return value[0] if value else None
    return value


def _confidence(query: str, *fields: str) -> float:
    tokens = _tokens(query)
    if not tokens:
        return 0.5
    haystack = " ".join(str(field or "") for field in fields).lower()
    hits = sum(1 for token in tokens if token in haystack)
    minimum_hits = min(2, len(tokens))
    if hits < minimum_hits:
        return 0.0
    exact_bonus = 0.1 if query.lower() in haystack else 0.0
    return min(0.95, 0.35 + (hits / len(tokens)) * 0.5 + exact_bonus)


def _tokens(value: str) -> list[str]:
    return [token for token in re.findall(r"[\w']+", value.lower()) if len(token) > 1]


def _int_or_none(value) -> int | None:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _duration_seconds(value) -> int | None:
    try:
        seconds = round(float(value))
    except (TypeError, ValueError):
        return None
    return seconds if seconds > 0 else None
