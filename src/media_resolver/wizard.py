from __future__ import annotations

from pathlib import Path

import questionary
from questionary import Choice
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from media_resolver.core.display import format_duration, safe_text
from media_resolver.core.models import MediaIntent, QualityClaim, QualityMode, SourcePolicy
from media_resolver.core.naming import NamingTemplate, render_preview_table
from media_resolver.core.resolver import resolve_candidates
from media_resolver.core.tools import ToolRegistry
from media_resolver.metadata.public import PublicMetadataResolver
from media_resolver.versions.archive_plan import ArchivePlan, build_archive_plan

console = Console(legacy_windows=False)


def run_wizard() -> None:
    console.print(Panel.fit("Media Resolver", subtitle="interactive alpha"))

    registry = ToolRegistry.discover()
    missing_required = registry.missing_for_basic_downloads()
    if missing_required:
        console.print("[yellow]Some helper tools are missing. Run `media-resolver doctor`.[/yellow]")

    intent = questionary.select(
        "What do you want to resolve?",
        choices=[
            Choice("Track / album / playlist", value=MediaIntent.AUDIO),
            Choice("YouTube video", value=MediaIntent.VIDEO),
            Choice("Subtitles / lyrics", value=MediaIntent.TEXT),
            Choice("Metadata / tagging only", value=MediaIntent.METADATA),
        ],
    ).ask()
    if intent is None:
        return

    query = questionary.text("Paste a URL or type a search query:").ask()
    if not query:
        return

    quality = _ask_quality(intent)
    if quality is None:
        return

    policy = (
        SourcePolicy.youtube_only()
        if intent in {MediaIntent.VIDEO, MediaIntent.TEXT}
        else _ask_source_policy()
    )
    output_dir = _ask_output_dir()
    naming = _ask_naming_template(intent)

    metadata_resolver = PublicMetadataResolver()
    metadata_matches = metadata_resolver.search(query, intent=intent)
    if metadata_matches:
        _render_metadata(metadata_matches)

    candidates = resolve_candidates(
        query=query,
        intent=intent,
        quality=quality,
        policy=policy,
        registry=registry,
        enrich_metadata=False,
    )

    if metadata_matches:
        for candidate in candidates:
            candidate.metadata = metadata_resolver.enrich(candidate.metadata, metadata_matches)

    _render_candidates(candidates)

    if not candidates:
        console.print("[red]No compatible candidates found.[/red]")
        return

    if intent == MediaIntent.AUDIO:
        archive_plan = build_archive_plan(query, quality, registry, latest=candidates)
        candidates = _ask_archive_side(archive_plan) or candidates

    _download_with_retry(candidates, output_dir, naming, intent)


def _ask_quality(intent: MediaIntent) -> QualityMode | None:
    if intent == MediaIntent.VIDEO:
        return QualityMode.BEST_AVAILABLE
    if intent == MediaIntent.TEXT:
        return QualityMode.SUBTITLES_ONLY
    if intent == MediaIntent.METADATA:
        return QualityMode.METADATA_ONLY

    choices = [
        Choice("Best available, with honest labels", value=QualityMode.BEST_AVAILABLE),
        Choice("Native Opus only", value=QualityMode.OPUS_NATIVE),
        Choice("Real MP3 320 only", value=QualityMode.MP3_320_REAL),
        Choice("Real FLAC/lossless only", value=QualityMode.FLAC_REAL),
        Choice("Real Hi-Res only", value=QualityMode.HI_RES_REAL),
    ]
    return questionary.select("Quality policy:", choices=choices).ask()


def _ask_source_policy() -> SourcePolicy:
    allow_alternatives = questionary.confirm(
        "Allow alternative sources such as SoundCloud, Archive.org, direct links, local files, Telegram/custom providers?",
        default=False,
    ).ask()
    allow_torrents = questionary.confirm(
        "Allow torrents/magnet links? This can be legally restricted in some countries.",
        default=False,
    ).ask()
    if allow_torrents:
        console.print(
            "[yellow]Torrents can be legally restricted depending on jurisdiction and content.[/yellow]"
        )
        allow_torrents = bool(
            questionary.confirm("Confirm torrent/magnet support for this run?", default=False).ask()
        )

    return SourcePolicy.for_interactive(
        allow_alternatives=bool(allow_alternatives),
        allow_torrents=bool(allow_torrents),
    )


def _ask_output_dir() -> Path:
    default = str(Path.cwd() / "downloads")
    raw = questionary.text("Output folder:", default=default).ask()
    path = Path(raw or default)
    path.mkdir(parents=True, exist_ok=True)
    return path


def _ask_naming_template(intent: MediaIntent) -> NamingTemplate:
    choices = [
        Choice("01 - Artist - Title.ext", value="{track_number:02} - {artist} - {title}.{ext}"),
        Choice("Artist - Title.ext", value="{artist} - {title}.{ext}"),
        Choice("Album/01 - Title.ext", value="{album}/{track_number:02} - {title}.{ext}"),
        Choice(
            "Artist/Album/01 - Artist - Title.ext",
            value="{album_artist}/{album}/{track_number:02} - {artist} - {title}.{ext}",
        ),
        Choice(
            "Playlist/001 - Artist - Title.ext",
            value="{playlist_title}/{playlist_index:03} - {artist} - {title}.{ext}",
        ),
        Choice(
            "Year - Album/Disc 1/01 - Artist - Title.ext",
            value="{year} - {album}/Disc {disc_number}/{track_number:02} - {artist} - {title}.{ext}",
        ),
        Choice("Custom template", value="__custom__"),
    ]
    if intent == MediaIntent.VIDEO:
        choices.insert(0, Choice("Channel - Title.ext", value="{channel} - {title}.{ext}"))

    value = questionary.select("Output naming:", choices=choices).ask()
    if value == "__custom__":
        value = questionary.text(
            "Template:",
            default="{artist} - {title}.{ext}",
        ).ask()
    return NamingTemplate(value or "{artist} - {title}.{ext}")


def _render_candidates(candidates) -> None:
    table = Table(title="Candidates")
    table.add_column("#", justify="right")
    table.add_column("Title")
    table.add_column("Source")
    table.add_column("Length")
    table.add_column("Quality")
    table.add_column("Real")
    table.add_column("Transcode")
    table.add_column("Notes")
    table.add_column("Confidence")

    for idx, candidate in enumerate(candidates, start=1):
        table.add_row(
            str(idx),
            safe_text(candidate.metadata.title),
            safe_text(candidate.source),
            format_duration(candidate.metadata.duration_seconds),
            safe_text(candidate.quality.summary()),
            "yes" if candidate.quality.is_real else "no",
            "yes" if candidate.quality.transcoded else "no",
            safe_text(_candidate_notes(candidate)),
            f"{candidate.confidence:.0%}",
        )
    console.print(table)


def _ask_archive_side(plan: ArchivePlan) -> list | None:
    if not plan.has_version_history and not plan.has_public_original:
        return None

    if plan.has_version_history:
        table = Table(title="Known release/version history")
        table.add_column("#", justify="right")
        table.add_column("Title")
        table.add_column("Artist")
        table.add_column("Date")
        table.add_column("Country")
        table.add_column("Format")
        for idx, version in enumerate(plan.versions[:10], start=1):
            table.add_row(
                str(idx),
                safe_text(version.title),
                safe_text(version.artist),
                safe_text(version.date),
                safe_text(version.country),
                safe_text(version.format),
            )
        console.print(table)

    if not plan.has_public_original:
        console.print(
            "[yellow]Version history was found, but no downloadable public original was verified.[/yellow]"
        )
        return None

    console.print(f"[dim]Original/public search query:[/dim] {safe_text(plan.original_query)}")
    _render_candidates(plan.original[:10])

    choice = questionary.select(
        "Which version source should be used?",
        choices=[
            Choice("Latest/current streaming candidates", value="latest"),
            Choice("Original/public candidates found in archives or public downloads", value="original"),
        ],
    ).ask()
    if choice == "original":
        return plan.original
    return plan.latest


def _download_with_retry(
    candidates, output_dir: Path, naming: NamingTemplate, intent: MediaIntent
) -> None:
    remaining = list(candidates)
    while remaining:
        selected = questionary.select(
            "Choose candidate to download:",
            choices=[
                Choice(safe_text(candidate.display_label()), value=idx)
                for idx, candidate in enumerate(remaining)
            ],
        ).ask()
        if selected is None:
            return

        candidate = remaining[selected]
        if intent == MediaIntent.VIDEO:
            _configure_video_download(candidate)
        render_preview_table(console, [candidate.metadata], naming)

        if not questionary.confirm("Download this candidate?", default=True).ask():
            return

        provider = candidate.provider_payload.get("provider")
        if provider is None:
            console.print("[red]Selected candidate has no download provider.[/red]")
            remaining.pop(selected)
        else:
            try:
                result = provider.download(candidate=candidate, output_dir=output_dir, naming=naming)
            except Exception as exc:
                console.print(
                    f"[red]Download failed from {safe_text(candidate.source)}:[/red] {safe_text(exc)}"
                )
                remaining.pop(selected)
            else:
                if isinstance(result, list):
                    for path in result:
                        console.print(f"[green]Saved:[/green] {path}")
                else:
                    console.print(f"[green]Saved:[/green] {result}")
                return

        if not remaining:
            console.print("[red]No more candidates left to try.[/red]")
            return
        if not questionary.confirm("Try another candidate?", default=True).ask():
            return


def _render_metadata(items) -> None:
    table = Table(title="Metadata matches")
    table.add_column("#", justify="right")
    table.add_column("Title")
    table.add_column("Artist")
    table.add_column("Album")
    table.add_column("Year")
    table.add_column("Length")
    table.add_column("Source")

    for idx, item in enumerate(items, start=1):
        table.add_row(
            str(idx),
            safe_text(item.title),
            safe_text(item.artist),
            safe_text(item.album),
            safe_text(item.year),
            format_duration(item.duration_seconds),
            safe_text(item.source),
        )
    console.print(table)


def _candidate_notes(candidate) -> str:
    flags = candidate.metadata.extra.get("version_flags") or ()
    if flags:
        return ", ".join(flags)
    notes = [
        note
        for note in candidate.quality.notes
        if note.startswith("alternate version:")
    ]
    return "; ".join(notes)


def _configure_video_download(candidate) -> None:
    formats = _video_formats_for_candidate(candidate)
    choices = [
        Choice("Best video + audio", value=("bv*+ba/best", "mp4", "video+audio")),
    ]
    for height in _available_video_heights(formats):
        choices.append(
            Choice(
                f"{height}p video + audio",
                value=(
                    f"bv*[height<={height}]+ba/best[height<={height}]/best",
                    "mp4",
                    f"video+audio {height}p",
                ),
            )
        )
    choices.extend(
        [
            Choice("Audio only (best native)", value=("bestaudio/best", "mka", "audio")),
            Choice("Video only (no audio)", value=("bestvideo/best", "mp4", "video-only")),
        ]
    )

    selected = questionary.select("YouTube quality / stream:", choices=choices).ask()
    if not selected:
        return

    selector, ext, codec = selected
    _apply_video_download_choice(candidate, selector, ext, codec)


def _video_formats_for_candidate(candidate) -> list[dict]:
    collection_entries = candidate.provider_payload.get("collection_entries") or []
    if collection_entries:
        return collection_entries[0].provider_payload.get("raw", {}).get("formats") or []
    return candidate.provider_payload.get("raw", {}).get("formats") or []


def _apply_video_download_choice(candidate, selector: str, ext: str, codec: str) -> None:
    candidate.provider_payload["format_selector"] = selector
    candidate.metadata.ext = ext
    candidate.quality = QualityClaim(
        codec=codec,
        container=ext,
        is_real=True,
        transcoded=False,
    )
    for entry in candidate.provider_payload.get("collection_entries") or []:
        _apply_video_download_choice(entry, selector, ext, codec)


def _available_video_heights(formats) -> list[int]:
    heights = {
        int(fmt.get("height"))
        for fmt in formats
        if fmt.get("height")
        and fmt.get("vcodec") not in (None, "none")
        and int(fmt.get("height")) >= 144
    }
    return sorted(heights, reverse=True)[:8]
