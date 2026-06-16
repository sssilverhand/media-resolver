from __future__ import annotations

import click
from pathlib import Path
from time import sleep, time
from rich.console import Console
from rich.table import Table

from media_resolver.core.display import format_duration, safe_text
from media_resolver.core.models import MediaIntent, QualityMode, SourcePolicy
from media_resolver.core.naming import NamingTemplate
from media_resolver.core.resolver import resolve_candidates
from media_resolver.core.tools import ToolRegistry
from media_resolver.metadata.public import PublicMetadataResolver
from media_resolver.versions.archive_plan import build_archive_plan
from media_resolver.versions.release_resolver import ReleaseResolver
from media_resolver.wizard import run_wizard

console = Console(legacy_windows=False)


@click.group(invoke_without_command=True)
@click.pass_context
def cli(ctx: click.Context) -> None:
    """Interactive media resolver."""
    if ctx.invoked_subcommand is None:
        try:
            run_wizard()
        except Exception as exc:
            if exc.__class__.__name__ == "NoConsoleScreenBufferError":
                raise click.ClickException(
                    "Interactive mode needs a real Windows terminal. "
                    "Use `media-resolver.exe inspect ...` or `media-resolver.exe download ...` "
                    "for non-interactive runs."
                ) from exc
            raise


@cli.command()
def doctor() -> None:
    """Show local helper binary status."""
    registry = ToolRegistry.discover()
    registry.render(console)


@cli.command("tidal-login")
def tidal_login_command() -> None:
    """Authorize Tidal access for metadata and Tidal downloads."""
    try:
        from tiddl.auth import AuthError, getDeviceAuth, getToken
        from tiddl.config import AuthConfig, Config
    except Exception as exc:
        raise click.ClickException("Tidal support is not installed in this build.") from exc

    config = Config.fromFile()
    if config.auth.token:
        console.print("[green]Tidal is already logged in.[/green]")
        return

    auth = getDeviceAuth()
    uri = f"https://{auth.verificationUriComplete}"
    console.print(f"Open this URL and complete Tidal authentication:\n{uri}")
    click.launch(uri)

    auth_end_at = time() + auth.expiresIn
    while time() < auth_end_at:
        sleep(auth.interval)
        try:
            token = getToken(auth.deviceCode)
        except AuthError as exc:
            if exc.error == "authorization_pending":
                continue
            if exc.error == "expired_token":
                break
            raise click.ClickException(str(exc)) from exc

        config.auth = AuthConfig(
            token=token.access_token,
            refresh_token=token.refresh_token,
            expires=token.expires_in + int(time()),
            user_id=str(token.user.userId),
            country_code=token.user.countryCode,
        )
        config.save()
        console.print("[green]Tidal login saved.[/green]")
        return

    raise click.ClickException("Tidal authentication timed out.")


@cli.command("inspect")
@click.argument("query")
@click.option(
    "--intent",
    type=click.Choice([item.value for item in MediaIntent]),
    default=MediaIntent.AUDIO.value,
    show_default=True,
)
@click.option(
    "--quality",
    type=click.Choice([item.value for item in QualityMode]),
    default=QualityMode.BEST_AVAILABLE.value,
    show_default=True,
)
@click.option("--allow-torrents", is_flag=True, help="Allow user-provided magnet/.torrent input.")
@click.option(
    "--allow-alternatives",
    is_flag=True,
    help="Allow Archive.org/custom alternative sources in addition to primary sources.",
)
@click.option(
    "--sources",
    default="primary",
    show_default=True,
    help="Comma-separated advanced override, or primary/all.",
)
def inspect_command(
    query: str,
    intent: str,
    quality: str,
    allow_torrents: bool,
    allow_alternatives: bool,
    sources: str,
) -> None:
    """Inspect metadata and downloadable candidates for a query or URL."""
    registry = ToolRegistry.discover()
    media_intent = MediaIntent(intent)
    quality_mode = QualityMode(quality)
    policy = _policy_for_intent(media_intent, sources, allow_alternatives, allow_torrents)

    metadata = PublicMetadataResolver().search(query, media_intent)
    if metadata:
        metadata_table = Table(title="Metadata")
        metadata_table.add_column("Title")
        metadata_table.add_column("Artist")
        metadata_table.add_column("Album")
        metadata_table.add_column("Length")
        metadata_table.add_column("Source")
        for item in metadata:
            metadata_table.add_row(
                safe_text(item.title),
                safe_text(item.artist),
                safe_text(item.album),
                format_duration(item.duration_seconds),
                safe_text(item.source),
            )
        console.print(metadata_table)

    candidates = resolve_candidates(
        query=query,
        intent=media_intent,
        quality=quality_mode,
        policy=policy,
        registry=registry,
        enrich_metadata=False,
    )

    table = Table(title="Candidates")
    table.add_column("#", justify="right")
    table.add_column("Title")
    table.add_column("Source")
    table.add_column("Length")
    table.add_column("Quality")
    table.add_column("Real")
    table.add_column("Notes")
    table.add_column("Confidence")
    for index, candidate in enumerate(candidates, start=1):
        table.add_row(
            str(index),
            safe_text(candidate.metadata.title),
            safe_text(candidate.source),
            format_duration(candidate.metadata.duration_seconds),
            safe_text(candidate.quality.summary()),
            "yes" if candidate.quality.is_real else "no",
            safe_text(_candidate_notes(candidate)),
            f"{candidate.confidence:.0%}",
        )
    console.print(table)


@cli.command("download")
@click.argument("query")
@click.option(
    "--intent",
    type=click.Choice([item.value for item in MediaIntent]),
    default=MediaIntent.AUDIO.value,
    show_default=True,
)
@click.option(
    "--quality",
    type=click.Choice([item.value for item in QualityMode]),
    default=QualityMode.BEST_AVAILABLE.value,
    show_default=True,
)
@click.option("--output", "output_dir", default="downloads", show_default=True)
@click.option("--template", "template", default="{artist} - {title}.{ext}", show_default=True)
@click.option("--candidate", "candidate_index", default=1, show_default=True)
@click.option("--allow-torrents", is_flag=True, help="Allow user-provided magnet/.torrent input.")
@click.option(
    "--allow-alternatives",
    is_flag=True,
    help="Allow Archive.org/custom alternative sources in addition to primary sources.",
)
@click.option(
    "--sources",
    default="primary",
    show_default=True,
    help="Comma-separated advanced override, or primary/all.",
)
def download_command(
    query: str,
    intent: str,
    quality: str,
    output_dir: str,
    template: str,
    candidate_index: int,
    allow_torrents: bool,
    allow_alternatives: bool,
    sources: str,
) -> None:
    """Download a candidate without the interactive wizard."""
    registry = ToolRegistry.discover()
    media_intent = MediaIntent(intent)
    candidates = resolve_candidates(
        query=query,
        intent=media_intent,
        quality=QualityMode(quality),
        policy=_policy_for_intent(media_intent, sources, allow_alternatives, allow_torrents),
        registry=registry,
    )
    if not candidates:
        raise click.ClickException("No compatible candidates found.")
    if candidate_index < 1 or candidate_index > len(candidates):
        raise click.ClickException(f"Candidate must be between 1 and {len(candidates)}.")

    candidate = candidates[candidate_index - 1]
    provider = candidate.provider_payload.get("provider")
    if provider is None:
        raise click.ClickException("Selected candidate has no download provider.")

    try:
        result = provider.download(candidate, Path(output_dir), NamingTemplate(template))
    except Exception as exc:
        raise click.ClickException(
            f"Download failed from {safe_text(candidate.source)}: {exc}"
        ) from exc
    paths = result if isinstance(result, list) else [result]
    for path in paths:
        console.print(f"[green]Saved:[/green] {safe_text(path)}")


@cli.command("archive")
@click.argument("query")
@click.option(
    "--quality",
    type=click.Choice([item.value for item in QualityMode]),
    default=QualityMode.BEST_AVAILABLE.value,
    show_default=True,
)
@click.option("--output", "output_dir", default="archive-downloads", show_default=True)
@click.option(
    "--template",
    "template",
    default="{version}/{artist} - {title}.{ext}",
    show_default=True,
)
@click.option(
    "--download",
    type=click.Choice(["none", "latest", "original", "both"]),
    default="none",
    show_default=True,
    help="Download selected archive side after showing the plan.",
)
@click.option("--latest-candidate", default=1, show_default=True)
@click.option("--original-candidate", default=1, show_default=True)
def archive_command(
    query: str,
    quality: str,
    output_dir: str,
    template: str,
    download: str,
    latest_candidate: int,
    original_candidate: int,
) -> None:
    """Plan or download latest and original/public versions of a track or release."""
    registry = ToolRegistry.discover()
    quality_mode = QualityMode(quality)
    plan = build_archive_plan(query, quality_mode, registry)

    if plan.versions:
        table = Table(title="Known release versions")
        table.add_column("#", justify="right")
        table.add_column("Title")
        table.add_column("Artist")
        table.add_column("Date")
        table.add_column("Country")
        table.add_column("Format")
        for index, version in enumerate(plan.versions, start=1):
            table.add_row(
                str(index),
                safe_text(version.title),
                safe_text(version.artist),
                safe_text(version.date),
                safe_text(version.country),
                safe_text(version.format),
            )
        console.print(table)

    console.print(f"[dim]Original/public search query:[/dim] {safe_text(plan.original_query)}")
    _render_archive_candidates("Latest streaming candidates", plan.latest)
    _render_archive_candidates("Original/public candidates", plan.original)

    naming = NamingTemplate(template)
    if download in {"latest", "both"}:
        _download_archive_candidate(plan.latest, latest_candidate, Path(output_dir), naming, "latest")
    if download in {"original", "both"}:
        _download_archive_candidate(
            plan.original,
            original_candidate,
            Path(output_dir),
            naming,
            "original",
        )


def _policy_from_sources(
    sources: str, allow_alternatives: bool = False, allow_torrents: bool = False
) -> SourcePolicy:
    values = {item.strip().lower() for item in sources.split(",") if item.strip()}
    if not values or values == {"primary"}:
        return SourcePolicy.for_interactive(
            allow_alternatives=allow_alternatives,
            allow_torrents=allow_torrents,
        )
    include_all = "all" in values
    if include_all:
        allow_alternatives = True
    return SourcePolicy(
        spotify=include_all or "spotify" in values,
        tidal=include_all or "tidal" in values,
        youtube=include_all or "youtube" in values or "yt" in values,
        soundcloud=include_all or "soundcloud" in values or "sc" in values,
        audius=include_all or "audius" in values,
        bandcamp=include_all or "bandcamp" in values,
        archive=allow_alternatives or "archive" in values or "archive.org" in values,
        direct=include_all or "direct" in values,
        local=include_all or "local" in values,
        torrents=allow_torrents and (include_all or "torrents" in values),
        telegram=allow_alternatives,
        custom=allow_alternatives,
    )


def _policy_for_intent(
    intent: MediaIntent,
    sources: str,
    allow_alternatives: bool = False,
    allow_torrents: bool = False,
) -> SourcePolicy:
    if intent in {MediaIntent.VIDEO, MediaIntent.TEXT}:
        return SourcePolicy.youtube_only()
    return _policy_from_sources(sources, allow_alternatives, allow_torrents)


def _render_archive_candidates(title: str, candidates) -> None:
    table = Table(title=title)
    table.add_column("#", justify="right")
    table.add_column("Title")
    table.add_column("Artist")
    table.add_column("Source")
    table.add_column("Length")
    table.add_column("Quality")
    table.add_column("Real")
    table.add_column("Notes")
    for index, candidate in enumerate(candidates[:10], start=1):
        table.add_row(
            str(index),
            safe_text(candidate.metadata.title),
            safe_text(candidate.metadata.artist),
            safe_text(candidate.source),
            format_duration(candidate.metadata.duration_seconds),
            safe_text(candidate.quality.summary()),
            "yes" if candidate.quality.is_real else "no",
            safe_text(_candidate_notes(candidate)),
        )
    console.print(table)


def _download_archive_candidate(
    candidates,
    index: int,
    output_dir: Path,
    naming: NamingTemplate,
    version: str,
) -> None:
    if not candidates:
        raise click.ClickException(f"No {version} candidates found.")
    if index < 1 or index > len(candidates):
        raise click.ClickException(f"{version} candidate must be between 1 and {len(candidates)}.")

    candidate = candidates[index - 1]
    candidate.metadata.version = version
    provider = candidate.provider_payload.get("provider")
    if provider is None:
        raise click.ClickException(f"Selected {version} candidate has no download provider.")
    try:
        result = provider.download(candidate, output_dir, naming)
    except Exception as exc:
        raise click.ClickException(
            f"{version} download failed from {safe_text(candidate.source)}: {exc}"
        ) from exc
    paths = result if isinstance(result, list) else [result]
    for path in paths:
        console.print(f"[green]Saved {version}:[/green] {safe_text(path)}")


@cli.command("versions")
@click.argument("query")
@click.option("--limit", default=20, show_default=True)
def versions_command(query: str, limit: int) -> None:
    """Show known release versions from public metadata."""
    versions = ReleaseResolver().search_versions(query, limit=limit)
    table = Table(title="Release versions")
    table.add_column("#", justify="right")
    table.add_column("Title")
    table.add_column("Artist")
    table.add_column("Date")
    table.add_column("Country")
    table.add_column("Tracks", justify="right")
    table.add_column("Format")
    for index, version in enumerate(versions, start=1):
        table.add_row(
            str(index),
            safe_text(version.title),
            safe_text(version.artist),
            safe_text(version.date),
            safe_text(version.country),
            str(version.track_count or ""),
            safe_text(version.format),
        )
    console.print(table)


def main() -> None:
    cli()


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


if __name__ == "__main__":
    main()
