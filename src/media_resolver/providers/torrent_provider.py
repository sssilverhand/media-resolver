from __future__ import annotations

import subprocess
from pathlib import Path

from media_resolver.core.models import (
    MediaCandidate,
    MediaIntent,
    MediaMetadata,
    QualityClaim,
    QualityMode,
    SourcePolicy,
)
from media_resolver.core.naming import NamingTemplate
from media_resolver.core.tools import ToolRegistry


class TorrentProvider:
    def __init__(self, registry: ToolRegistry) -> None:
        self.registry = registry

    def inspect(
        self,
        query: str,
        intent: MediaIntent,
        quality: QualityMode,
        policy: SourcePolicy,
    ) -> list[MediaCandidate]:
        if not policy.torrents or not self.registry.aria2c.available:
            return []
        if not _looks_like_torrent_input(query):
            return []

        title = "magnet-download" if query.startswith("magnet:") else Path(query).stem
        metadata = MediaMetadata(
            title=title,
            artist="Unknown Artist",
            album="Torrent",
            source="Torrent",
            ext="",
        )
        claim = QualityClaim(
            codec="torrent payload",
            container="multiple",
            is_real=True,
            notes=("Quality is verified after download per contained file.",),
        )
        return [
            MediaCandidate(
                source="Torrent",
                url=query,
                metadata=metadata,
                quality=claim,
                confidence=0.5,
                provider_payload={
                    "provider": self,
                    "quality_mode": quality.value,
                    "intent": intent.value,
                },
            )
        ]

    def download(
        self,
        candidate: MediaCandidate,
        output_dir: Path,
        naming: NamingTemplate,
    ) -> list[Path]:
        del naming
        output_dir.mkdir(parents=True, exist_ok=True)
        before = _snapshot(output_dir)
        command = [
            str(self.registry.aria2c.path),
            "--dir",
            str(output_dir),
            "--seed-time=0",
            "--summary-interval=5",
            candidate.url,
        ]
        subprocess.run(command, check=True)
        return sorted(_snapshot(output_dir) - before)


def _looks_like_torrent_input(value: str) -> bool:
    if value.startswith("magnet:?"):
        return True
    lowered = value.lower()
    return lowered.startswith(("http://", "https://")) and lowered.endswith(".torrent") or Path(value).suffix.lower() == ".torrent"


def _snapshot(root: Path) -> set[Path]:
    if not root.exists():
        return set()
    return {path for path in root.rglob("*") if path.is_file()}
