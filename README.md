# Media Resolver

Media Resolver is an interactive Windows-first CLI for finding, downloading, verifying, tagging,
and naming media files without pretending that lossy sources are lossless.

The project is built around one rule: quality labels must be honest. A file is presented as
lossless only when the source and post-download inspection support that claim. Transcodes and
best-effort candidates stay labeled as what they really are.

## What It Does

- Runs as an interactive terminal wizard or as regular CLI commands.
- Resolves audio, video, and text/subtitle candidates from supported providers.
- Uses public metadata sources to normalize track identity before naming and tagging.
- Checks local media quality with `ffprobe`.
- Downloads YouTube/YouTube Music candidates through `yt-dlp`.
- Supports direct media URLs and local files/folders.
- Supports optional Archive.org, SoundCloud, Audius, Bandcamp, Tidal, and torrent/magnet flows
  when enabled by the user.
- Builds a portable Windows package with the executable and helper binaries.

## Non-Goals And Legal Boundaries

Media Resolver is a resolver/downloader framework. It does not include DRM bypass logic, stream
ripping logic, account bypasses, or hidden provider behavior.

Some providers or media URLs can expose content that you do not have the right to download. Use the
tool only with content you are allowed to access, archive, or transform. Torrent/magnet input and
alternative/public sources are opt-in.

Spotify is used only as an authoritative metadata/catalog source. Spotify audio is not downloaded
or ripped by this project.

## Project Status

This repository is an early `0.1.0` project. The core CLI, ranking model, metadata merging,
quality checks, naming, tests, and Windows portable build path exist, but provider behavior depends
on external services and local helper binaries.

## Requirements

For development:

- Windows 10 or newer is the primary target.
- Python 3.11 or newer.
- PowerShell 5.1 or newer.
- Network access for fetching helper binaries and provider metadata.

For portable usage:

- No Python installation is required.
- Run the packaged `media-resolver.exe` from the portable folder.
- Helper tools are loaded from the local `bin/` folder first.

## Quick Start From Source

```powershell
git clone https://github.com/sssilverhand/media-resolver.git
cd media-resolver

python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e .[dev]

media-resolver doctor
media-resolver
```

To run the source tree with locally vendored Python dependencies, if you keep any in
`vendor/python`, use:

```powershell
.\scripts\run_dev.ps1
```

## CLI Examples

Open the interactive wizard:

```powershell
media-resolver
```

Check helper tools:

```powershell
media-resolver doctor
```

Inspect candidates without downloading:

```powershell
media-resolver inspect "Artist Track" --intent audio --quality best_available
```

Download the first compatible candidate:

```powershell
media-resolver download "Artist Track" --intent audio --quality best_available --output downloads
```

Show public release versions:

```powershell
media-resolver versions "Artist Album"
```

Plan latest/original archive candidates:

```powershell
media-resolver archive "Artist Track"
```

Allow alternative public sources:

```powershell
media-resolver inspect "Artist Track" --allow-alternatives
```

Allow a user-provided magnet or `.torrent` input:

```powershell
media-resolver inspect "magnet:?..." --allow-torrents
```

## Metadata Credentials

Spotify metadata lookup uses the Client Credentials flow. Set these environment variables before
running commands that need Spotify metadata:

```powershell
$env:SPOTIPY_CLIENT_ID = "..."
$env:SPOTIPY_CLIENT_SECRET = "..."
```

Tidal metadata/download support uses `tiddl` in the packaged Python environment. Authorize once:

```powershell
media-resolver tidal-login
```

## Portable Windows Build

Fetch helper binaries and build the portable package:

```powershell
.\scripts\build_windows.ps1
```

The build script creates:

```text
portable/
  media-resolver-windows-x64/
    media-resolver.exe
    README.md
    LICENSE
    bin/
      ffmpeg.exe
      ffprobe.exe
      yt-dlp.exe
      fpcalc.exe
      aria2c.exe
      deno.exe
      *.dll
    cache/
    downloads/
    licenses/
      THIRD_PARTY_NOTICES.txt
  media-resolver-windows-x64.zip
```

The `portable/`, `dist/`, `build/`, `vendor/bin`, and `vendor/python` outputs are intentionally
ignored by Git. Commit the source code and upload the zip as a GitHub Release asset.

## Repository Layout

```text
src/media_resolver/      Application code
  app.py                 Click CLI entry point
  wizard.py              Interactive terminal wizard
  core/                  Models, ranking, naming, tool discovery
  metadata/              Public metadata lookup and merging
  processing/            ffprobe, tagging, sidecar helpers
  providers/             Source/provider integrations
  versions/              Release/version comparison and archive planning
tests/                   Pytest suite
scripts/                 Development and release scripts
vendor/bin/.gitkeep      Placeholder for downloaded helper binaries
vendor/python/.gitkeep   Placeholder for optional local Python vendor dir
```

## Development Workflow

Install development dependencies:

```powershell
python -m pip install -e .[dev]
```

Run tests:

```powershell
python -m pytest
```

Run Ruff:

```powershell
python -m ruff check .
```

Fetch helper binaries only:

```powershell
python scripts/fetch_binaries.py
```

## Publishing To GitHub

Create an empty repository at:

```text
https://github.com/sssilverhand/media-resolver
```

Then push the source repository:

```powershell
git status
git add -A
git commit -m "Prepare Media Resolver for GitHub"
git branch -M main
git remote add origin https://github.com/sssilverhand/media-resolver.git
git push -u origin main
```

Create a version tag:

```powershell
git tag v0.1.0
git push origin v0.1.0
```

Build and publish the portable archive:

```powershell
.\scripts\build_windows.ps1
```

Upload `portable/media-resolver-windows-x64.zip` to a GitHub Release for `v0.1.0`. With GitHub CLI:

```powershell
gh release create v0.1.0 .\portable\media-resolver-windows-x64.zip `
  --repo sssilverhand/media-resolver `
  --title "Media Resolver v0.1.0" `
  --notes "Initial Windows portable build."
```

## Acknowledgements

Media Resolver stands on the work of many open-source projects and public metadata services.
Thank you to the maintainers and contributors of:

- [FFmpeg](https://ffmpeg.org/) and the [BtbN FFmpeg Builds](https://github.com/BtbN/FFmpeg-Builds)
  project for media probing, conversion, and Windows binaries.
- [yt-dlp](https://github.com/yt-dlp/yt-dlp) for media extraction support.
- [Chromaprint/fpcalc](https://github.com/acoustid/chromaprint) for acoustic fingerprinting.
- [aria2](https://github.com/aria2/aria2) for optional torrent/magnet downloads.
- [Deno](https://github.com/denoland/deno) for JavaScript runtime support used by modern extractors.
- [Click](https://github.com/pallets/click), [Rich](https://github.com/Textualize/rich), and
  [Questionary](https://github.com/tmbo/questionary) for the terminal interface.
- [PyInstaller](https://github.com/pyinstaller/pyinstaller) for the Windows executable build.
- [Mutagen](https://github.com/quodlibet/mutagen) for audio tag writing.
- [MusicBrainz](https://musicbrainz.org/) and
  [musicbrainzngs](https://github.com/alastair/python-musicbrainzngs) for public release metadata.
- [Spotipy](https://github.com/spotipy-dev/spotipy) and the
  [Spotify Web API](https://developer.spotify.com/documentation/web-api/) for catalog metadata.
- [tidalapi](https://github.com/tamland/python-tidal) and
  [tiddl](https://github.com/yaronzz/Tidal-Media-Downloader) for Tidal integration.
- [Requests](https://github.com/psf/requests), [certifi](https://github.com/certifi/python-certifi),
  [charset-normalizer](https://github.com/jawah/charset_normalizer),
  [idna](https://github.com/kjd/idna), and [urllib3](https://github.com/urllib3/urllib3)
  for HTTP and TLS plumbing.
- [pytest](https://github.com/pytest-dev/pytest) and [Ruff](https://github.com/astral-sh/ruff)
  for testing and linting.
- [Archive.org](https://archive.org/), [Bandcamp](https://bandcamp.com/),
  [Audius](https://audius.co/), [SoundCloud](https://soundcloud.com/), and
  [LRCLIB](https://lrclib.net/) for public media and metadata surfaces that the resolver can use
  when the user enables the relevant source.

## License

Media Resolver is licensed under the GNU Affero General Public License v3.0 only. See
[`LICENSE`](LICENSE).

Bundled third-party helper tools keep their own licenses. The portable build includes a
`licenses/THIRD_PARTY_NOTICES.txt` file with upstream references.
