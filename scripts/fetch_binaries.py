from __future__ import annotations

import json
import shutil
import zipfile
from pathlib import Path
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
BIN = ROOT / "vendor" / "bin"

YTDLP_URL = "https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp.exe"
FFMPEG_RELEASE_API = "https://api.github.com/repos/BtbN/FFmpeg-Builds/releases/latest"
CHROMAPRINT_RELEASE_API = "https://api.github.com/repos/acoustid/chromaprint/releases/latest"
ARIA2_RELEASE_API = "https://api.github.com/repos/aria2/aria2/releases/latest"
DENO_RELEASE_API = "https://api.github.com/repos/denoland/deno/releases/latest"


def main() -> int:
    BIN.mkdir(parents=True, exist_ok=True)
    download(YTDLP_URL, BIN / "yt-dlp.exe")
    fetch_ffmpeg()
    fetch_chromaprint()
    fetch_aria2()
    fetch_deno()
    print(f"Downloaded helper binaries to {BIN}")
    return 0


def download(url: str, target: Path) -> None:
    print(f"Downloading {url}")
    with urlopen(url) as response, target.open("wb") as file:
        shutil.copyfileobj(response, file)


def fetch_ffmpeg() -> None:
    print("Resolving latest FFmpeg build")
    with urlopen(FFMPEG_RELEASE_API) as response:
        release = json.load(response)
    assets = release.get("assets", [])
    asset = next(
        (
            item
            for item in assets
            if "win64" in item.get("name", "")
            and "gpl" in item.get("name", "")
            and item.get("name", "").endswith(".zip")
        ),
        None,
    )
    if not asset:
        raise RuntimeError("Could not find a suitable Windows FFmpeg zip asset")

    archive = BIN / asset["name"]
    download(asset["browser_download_url"], archive)
    with zipfile.ZipFile(archive) as zip_file:
        members = []
        for member in zip_file.namelist():
            if "/bin/" not in member:
                continue
            name = Path(member).name.lower()
            if name in {"ffmpeg.exe", "ffprobe.exe"} or name.endswith(".dll"):
                members.append(member)
        for member in members:
            name = Path(member).name
            with zip_file.open(member) as source, (BIN / name).open("wb") as target:
                shutil.copyfileobj(source, target)
    archive.unlink()


def fetch_chromaprint() -> None:
    print("Resolving latest Chromaprint fpcalc build")
    with urlopen(CHROMAPRINT_RELEASE_API) as response:
        release = json.load(response)
    asset = _find_asset(release, ["windows", "x86_64"], ".zip")
    if not asset:
        raise RuntimeError("Could not find a suitable Windows Chromaprint zip asset")

    archive = BIN / asset["name"]
    download(asset["browser_download_url"], archive)
    with zipfile.ZipFile(archive) as zip_file:
        for member in zip_file.namelist():
            if Path(member).name.lower() == "fpcalc.exe":
                with zip_file.open(member) as source, (BIN / "fpcalc.exe").open("wb") as target:
                    shutil.copyfileobj(source, target)
                break
    archive.unlink()


def fetch_aria2() -> None:
    print("Resolving latest aria2 build")
    with urlopen(ARIA2_RELEASE_API) as response:
        release = json.load(response)
    asset = _find_asset(release, ["win", "64bit"], ".zip")
    if not asset:
        raise RuntimeError("Could not find a suitable Windows aria2 zip asset")

    archive = BIN / asset["name"]
    download(asset["browser_download_url"], archive)
    with zipfile.ZipFile(archive) as zip_file:
        for member in zip_file.namelist():
            if Path(member).name.lower() == "aria2c.exe":
                with zip_file.open(member) as source, (BIN / "aria2c.exe").open("wb") as target:
                    shutil.copyfileobj(source, target)
                break
    archive.unlink()


def fetch_deno() -> None:
    print("Resolving latest Deno build")
    with urlopen(DENO_RELEASE_API) as response:
        release = json.load(response)
    asset = _find_asset(release, ["x86_64", "pc-windows-msvc"], ".zip")
    if not asset:
        raise RuntimeError("Could not find a suitable Windows Deno zip asset")

    archive = BIN / asset["name"]
    download(asset["browser_download_url"], archive)
    with zipfile.ZipFile(archive) as zip_file:
        for member in zip_file.namelist():
            if Path(member).name.lower() == "deno.exe":
                with zip_file.open(member) as source, (BIN / "deno.exe").open("wb") as target:
                    shutil.copyfileobj(source, target)
                break
    archive.unlink()


def _find_asset(release: dict, name_parts: list[str], suffix: str) -> dict | None:
    for asset in release.get("assets", []):
        name = asset.get("name", "").lower()
        if all(part.lower() in name for part in name_parts) and name.endswith(suffix):
            return asset
    return None


if __name__ == "__main__":
    raise SystemExit(main())
