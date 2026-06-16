from __future__ import annotations

import re
from html import unescape

import requests

from media_resolver.core.models import MediaCandidate, MediaIntent, QualityMode, SourcePolicy
from media_resolver.core.tools import ToolRegistry
from media_resolver.providers.ytdlp_provider import YtDlpProvider


class BandcampProvider:
    def __init__(self, registry: ToolRegistry) -> None:
        self.ytdlp = YtDlpProvider(registry)

    def inspect(
        self,
        query: str,
        intent: MediaIntent,
        quality: QualityMode,
        policy: SourcePolicy,
    ) -> list[MediaCandidate]:
        if not policy.bandcamp or intent not in {MediaIntent.AUDIO, MediaIntent.METADATA}:
            return []
        if query.startswith(("http://", "https://")):
            return []

        urls = _bandcamp_search(query)
        candidates: list[MediaCandidate] = []
        bandcamp_only = SourcePolicy(
            youtube=False,
            soundcloud=False,
            bandcamp=True,
            archive=False,
            direct=False,
            local=False,
        )
        for url in urls[:5]:
            candidates.extend(self.ytdlp.inspect(url, intent, quality, bandcamp_only))
        for candidate in candidates:
            candidate.source = "Bandcamp"
            candidate.metadata.source = "Bandcamp"
        return candidates[:10]


def _bandcamp_search(query: str) -> list[str]:
    try:
        response = requests.get(
            "https://bandcamp.com/search",
            params={"q": query, "item_type": "t"},
            headers={"User-Agent": "media-resolver/0.1"},
            timeout=12,
        )
        response.raise_for_status()
    except Exception:
        return []

    urls = []
    for match in re.finditer(r'<a[^>]+href="([^"]+)"[^>]*>', response.text):
        url = unescape(match.group(1))
        if ".bandcamp.com/track/" in url and url not in urls:
            urls.append(url.split("?")[0])
    return urls
