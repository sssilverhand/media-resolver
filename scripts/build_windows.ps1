$ErrorActionPreference = "Stop"

function Get-PythonCommand {
    if ($env:MEDIA_RESOLVER_PYTHON) {
        return $env:MEDIA_RESOLVER_PYTHON
    }

    $python = Get-Command python -ErrorAction SilentlyContinue
    if ($python) {
        return $python.Source
    }

    $py = Get-Command py -ErrorAction SilentlyContinue
    if ($py) {
        return $py.Source
    }

    throw "Python was not found. Set MEDIA_RESOLVER_PYTHON to a Python executable."
}

$Python = Get-PythonCommand
$Root = Split-Path -Parent $PSScriptRoot
$PortableRoot = Join-Path $Root "portable"
$Portable = Join-Path $PortableRoot "media-resolver-windows-x64"
$PortableZip = Join-Path $PortableRoot "media-resolver-windows-x64.zip"

& $Python -m pip install -e ".[dev]"
& $Python scripts/fetch_binaries.py
& $Python -m PyInstaller `
    --noconfirm `
    --clean `
    --name media-resolver `
    --onefile `
    --collect-all spotipy `
    --collect-all tidalapi `
    --collect-all tiddl `
    --collect-all yt_dlp `
    src/media_resolver/app.py

New-Item -ItemType Directory -Force -Path $PortableRoot | Out-Null

if (Test-Path $Portable) {
    $resolvedPortable = (Resolve-Path -LiteralPath $Portable).Path
    if (-not $resolvedPortable.StartsWith($Root, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to remove path outside project root: $resolvedPortable"
    }
    Remove-Item -LiteralPath $resolvedPortable -Recurse -Force
}

if (Test-Path $PortableZip) {
    Remove-Item -LiteralPath $PortableZip -Force
}

New-Item -ItemType Directory -Force -Path "$Portable\bin" | Out-Null
New-Item -ItemType Directory -Force -Path "$Portable\cache" | Out-Null
New-Item -ItemType Directory -Force -Path "$Portable\downloads" | Out-Null
New-Item -ItemType Directory -Force -Path "$Portable\licenses" | Out-Null

Copy-Item dist\media-resolver.exe "$Portable\media-resolver.exe"
Copy-Item vendor\bin\* "$Portable\bin\" -Exclude ".gitkeep"
Copy-Item README.md "$Portable\README.md"
Copy-Item LICENSE "$Portable\LICENSE"

$ThirdPartyNotice = @"
Media Resolver portable helper tools
====================================

This portable package may include third-party command-line tools downloaded by
scripts/fetch_binaries.py. They are distributed under their own licenses:

- FFmpeg Windows GPL build: https://github.com/BtbN/FFmpeg-Builds
- yt-dlp: https://github.com/yt-dlp/yt-dlp
- Chromaprint/fpcalc: https://github.com/acoustid/chromaprint
- aria2: https://github.com/aria2/aria2
- Deno: https://github.com/denoland/deno

Check each upstream project for the exact license text that applies to the
binary version included in this package.
"@

Set-Content -LiteralPath "$Portable\licenses\THIRD_PARTY_NOTICES.txt" -Value $ThirdPartyNotice -Encoding UTF8
Compress-Archive -Path "$Portable\*" -DestinationPath $PortableZip -Force

Write-Host "Portable build: $Portable"
Write-Host "Release archive: $PortableZip"
