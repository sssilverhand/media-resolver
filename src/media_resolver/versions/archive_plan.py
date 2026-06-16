from __future__ import annotations

from dataclasses import dataclass
import re

from media_resolver.core.models import MediaCandidate, MediaIntent, QualityMode, SourcePolicy
from media_resolver.core.resolver import resolve_candidates
from media_resolver.core.tools import ToolRegistry
from media_resolver.versions.release_resolver import ReleaseResolver, ReleaseVersion


@dataclass(frozen=True)
class ArchivePlan:
    query: str
    original_query: str
    versions: list[ReleaseVersion]
    latest: list[MediaCandidate]
    original: list[MediaCandidate]

    @property
    def has_public_original(self) -> bool:
        return bool(self.original)

    @property
    def has_version_history(self) -> bool:
        dated_versions = {version.date for version in self.versions if version.date}
        return len(dated_versions) > 1 or len(self.versions) > 1


def build_archive_plan(
    query: str,
    quality: QualityMode,
    registry: ToolRegistry,
    latest: list[MediaCandidate] | None = None,
    version_limit: int = 10,
) -> ArchivePlan:
    versions = relevant_versions(query, ReleaseResolver().search_versions(query, limit=version_limit))
    if latest is None:
        latest = resolve_candidates(
            query=query,
            intent=MediaIntent.AUDIO,
            quality=quality,
            policy=latest_policy(),
            registry=registry,
        )

    original_search = original_query(query, versions)
    original = resolve_candidates(
        query=original_search,
        intent=MediaIntent.AUDIO,
        quality=quality,
        policy=original_policy(),
        registry=registry,
    )

    for candidate in original:
        candidate.metadata.version = "original"

    return ArchivePlan(
        query=query,
        original_query=original_search,
        versions=versions,
        latest=latest,
        original=original,
    )


def latest_policy() -> SourcePolicy:
    return SourcePolicy.for_interactive(allow_alternatives=False)


def original_policy() -> SourcePolicy:
    return SourcePolicy(
        spotify=True,
        tidal=False,
        youtube=False,
        soundcloud=False,
        audius=False,
        bandcamp=True,
        archive=True,
        direct=True,
        local=True,
    )


def original_query(query: str, versions: list[ReleaseVersion]) -> str:
    versions = relevant_versions(query, versions)
    dated = [version for version in versions if version.date]
    if not dated:
        return query
    earliest = sorted(dated, key=lambda version: version.date)[0]
    if earliest.artist and earliest.artist != "Unknown Artist":
        return f"{earliest.artist} {earliest.title}"
    return earliest.title or query


def relevant_versions(query: str, versions: list[ReleaseVersion]) -> list[ReleaseVersion]:
    query_tokens = _tokens(query)
    if not query_tokens:
        return versions

    relevant = [
        version
        for version in versions
        if query_tokens.issubset(_tokens(f"{version.artist} {version.title}"))
    ]
    return relevant


def _tokens(value: str) -> set[str]:
    return {token for token in re.findall(r"[a-z0-9]+", value.lower()) if len(token) > 1}
