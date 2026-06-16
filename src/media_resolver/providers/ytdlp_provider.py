from __future__ import annotations

import subprocess
from pathlib import Path
from urllib.parse import quote_plus, urlparse

import yt_dlp

from media_resolver.core.models import (
    MediaCandidate,
    MediaIntent,
    MediaMetadata,
    QualityClaim,
    QualityMode,
    SourcePolicy,
)
from media_resolver.core.matching import version_flags, version_note
from media_resolver.core.naming import NamingTemplate
from media_resolver.core.quality import quality_satisfies
from media_resolver.core.tools import ToolRegistry
from media_resolver.processing.ffprobe import inspect_audio, inspect_duration
from media_resolver.processing.sidecars import write_lyrics_sidecars
from media_resolver.processing.tagger import write_basic_tags, write_cover_art


IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
AUDIO_OUTPUT_EXTENSIONS = {".mp3", ".m4a", ".flac", ".opus", ".ogg", ".webm", ".wav", ".aiff"}
VIDEO_OUTPUT_EXTENSIONS = {".mp4", ".mkv", ".mov", ".webm", ".m4v"}
MEDIA_OUTPUT_EXTENSIONS = AUDIO_OUTPUT_EXTENSIONS | VIDEO_OUTPUT_EXTENSIONS


class YtDlpProvider:
    def __init__(self, registry: ToolRegistry) -> None:
        self.registry = registry

    def inspect(
        self,
        query: str,
        intent: MediaIntent,
        quality: QualityMode,
        policy: SourcePolicy,
    ) -> list[MediaCandidate]:
        if not policy.youtube and not policy.soundcloud and not policy.bandcamp and not policy.archive:
            return []

        targets = _targets_for_query(query, policy, intent)
        options = {
            "quiet": True,
            "no_warnings": True,
            "skip_download": True,
            "extract_flat": False,
            "ignoreerrors": True,
            "logger": _QuietLogger(),
        }
        if self.registry.ffmpeg.available and self.registry.ffmpeg.path:
            options["ffmpeg_location"] = str(self.registry.ffmpeg.path.parent)
        if self.registry.deno.available and self.registry.deno.path:
            options["js_runtimes"] = {"deno": {"path": str(self.registry.deno.path)}}

        candidates: list[MediaCandidate] = []
        for target in targets:
            target_options = dict(options)
            if _is_search_target(target):
                target_options["playlistend"] = 5
            with yt_dlp.YoutubeDL(target_options) as ydl:
                try:
                    info = ydl.extract_info(target, download=False)
                except Exception:
                    continue

                entries = info.get("entries") if isinstance(info, dict) else None
                if entries:
                    is_search = _is_search_collection(target, info)
                    entry_candidates = self._candidates_from_entries(
                        entries,
                        intent,
                        quality,
                        policy,
                        include_nested_items=not is_search,
                    )
                    if not is_search:
                        collection = self._collection_candidate_from_info(
                            info, entry_candidates, intent, quality
                        )
                    else:
                        collection = None
                    if collection:
                        candidates.append(collection)
                    candidates.extend(entry_candidates)
                    continue

                if not info or not _source_allowed(info, policy):
                    continue
                candidate = self._candidate_from_info(info, intent, quality)
                if candidate:
                    candidates.append(candidate)
        return candidates

    def download(
        self,
        candidate: MediaCandidate,
        output_dir: Path,
        naming: NamingTemplate,
    ) -> list[Path]:
        collection_entries = candidate.provider_payload.get("collection_entries")
        if collection_entries:
            paths: list[Path] = []
            for entry in collection_entries:
                paths.extend(self.download(entry, output_dir, naming))
            return paths

        output_dir.mkdir(parents=True, exist_ok=True)
        relative = naming.render(candidate.metadata)
        output_template = str(output_dir / relative)
        output_template = str(Path(output_template).with_suffix(".%(ext)s"))
        Path(output_template).parent.mkdir(parents=True, exist_ok=True)

        ydl_format = candidate.provider_payload.get("format_selector", "bestaudio/best")
        download_mode = candidate.provider_payload.get("download_mode", "media")
        audio_postprocess = candidate.provider_payload.get("audio_postprocess")
        before = _snapshot(output_dir)

        if self.registry.yt_dlp.available and self.registry.yt_dlp.path:
            command = [str(self.registry.yt_dlp.path), "-o", output_template]
            if download_mode == "subtitles":
                command.extend(
                    [
                        "--skip-download",
                        "--write-subs",
                        "--write-auto-subs",
                        "--sub-langs",
                        "all",
                        "--convert-subs",
                        "srt",
                    ]
                )
            elif download_mode == "metadata":
                command.extend(["--skip-download", "--write-info-json", "--write-thumbnail"])
            else:
                command.extend(
                    [
                        "-f",
                        ydl_format,
                        "--embed-metadata",
                        "--continue",
                        "--retries",
                        "10",
                        "--fragment-retries",
                        "10",
                        "--ignore-errors",
                        "--no-abort-on-error",
                    ]
                )
                if candidate.quality.codec != "video+audio":
                    command.extend(["--embed-thumbnail", "--convert-thumbnails", "jpg"])
                if audio_postprocess:
                    command.extend(["--extract-audio", "--audio-format", audio_postprocess])
                    if audio_postprocess == "opus":
                        command.extend(["--audio-quality", "0"])
                elif candidate.metadata.ext == "opus":
                    command.extend(["--extract-audio", "--audio-format", "opus", "--audio-quality", "0"])
            if self.registry.ffmpeg.available and self.registry.ffmpeg.path:
                command.extend(["--ffmpeg-location", str(self.registry.ffmpeg.path.parent)])
            if self.registry.deno.available and self.registry.deno.path:
                command.extend(["--js-runtimes", f"deno:{self.registry.deno.path}"])
            command.append(candidate.url)
            subprocess.run(command, check=True)
        else:
            options = {
                "format": ydl_format,
                "outtmpl": output_template,
                "noplaylist": False,
                "writethumbnail": True,
                "continuedl": True,
                "retries": 10,
                "fragment_retries": 10,
                "ignoreerrors": True,
                "postprocessors": [],
            }
            if download_mode == "subtitles":
                options.update(
                    {
                        "skip_download": True,
                        "writesubtitles": True,
                        "writeautomaticsub": True,
                        "subtitleslangs": ["all"],
                    }
                )
            elif download_mode == "metadata":
                options.update({"skip_download": True, "writeinfojson": True})
            else:
                options.update({"embedmetadata": True})
                if audio_postprocess:
                    options["postprocessors"] = [
                        {
                            "key": "FFmpegExtractAudio",
                            "preferredcodec": audio_postprocess,
                            "preferredquality": "0" if audio_postprocess == "opus" else "best",
                        }
                    ]
            if self.registry.ffmpeg.available and self.registry.ffmpeg.path:
                options["ffmpeg_location"] = str(self.registry.ffmpeg.path.parent)
            if self.registry.deno.available and self.registry.deno.path:
                options["js_runtimes"] = {"deno": {"path": str(self.registry.deno.path)}}
            with yt_dlp.YoutubeDL(options) as ydl:
                ydl.download([candidate.url])

        created = sorted(_snapshot(output_dir) - before)
        if download_mode == "subtitles" and not created:
            raise RuntimeError("No subtitles or lyrics were found for this YouTube item.")
        if download_mode == "media":
            for path in created:
                if path.suffix.lower() in IMAGE_EXTENSIONS:
                    try:
                        path.unlink()
                    except OSError:
                        pass
            created = [path for path in created if path.exists()]
            created = _normalize_expected_audio_files(created, candidate, self.registry)
            if not any(path.suffix.lower() in MEDIA_OUTPUT_EXTENSIONS for path in created):
                raise RuntimeError("Download finished without producing a media file.")
        for path in created:
            if path.suffix.lower() in AUDIO_OUTPUT_EXTENSIONS:
                try:
                    _verify_downloaded_quality(path, candidate, self.registry)
                except RuntimeError:
                    raise
                except Exception:
                    if candidate.provider_payload.get("quality_mode") in {
                        QualityMode.MP3_320_REAL.value,
                        QualityMode.FLAC_REAL.value,
                        QualityMode.HI_RES_REAL.value,
                    }:
                        raise
                try:
                    write_basic_tags(path, candidate.metadata)
                    write_cover_art(path, candidate.metadata, self.registry)
                    write_lyrics_sidecars(path, candidate.metadata)
                except Exception:
                    pass
        return created or [output_dir / relative]

    def _candidate_from_info(
        self, info: dict, intent: MediaIntent, quality_mode: QualityMode
    ) -> MediaCandidate | None:
        formats = info.get("formats") or []
        title = info.get("title") or "Unknown title"
        artist = info.get("artist") or info.get("uploader") or info.get("channel") or "Unknown Artist"
        ext = "webm" if intent == MediaIntent.AUDIO else "mp4"
        if intent == MediaIntent.TEXT:
            ext = "srt"

        quality, selector = _select_quality(formats, intent, quality_mode)
        if quality is None:
            return None
        if intent == MediaIntent.AUDIO and quality_mode == QualityMode.OPUS_NATIVE:
            ext = "opus"
        elif intent == MediaIntent.AUDIO and quality_mode == QualityMode.BEST_AVAILABLE:
            ext = _audio_extension_from_quality(quality)

        playlist_index = _info_int(info, "playlist_index") or 1
        track_number = _info_int(info, "track_number") or playlist_index

        metadata = MediaMetadata(
            title=title,
            artist=artist,
            album_artist=artist,
            album=info.get("album") or "Unknown Album",
            channel=info.get("channel") or info.get("uploader") or "Unknown Channel",
            year=str(info.get("release_year") or info.get("upload_date") or "")[:4],
            track_number=track_number,
            playlist_index=playlist_index,
            playlist_title=info.get("playlist_title") or "Playlist",
            source=_source_name_from_info(info),
            ext=ext,
            duration_seconds=_duration_seconds(info.get("duration")),
            extra={
                "webpage_url": info.get("webpage_url"),
                "thumbnail": info.get("thumbnail"),
                "version_flags": version_flags(title),
            },
        )
        note = version_note(metadata.extra["version_flags"])
        if note:
            quality = quality.with_notes(note)
        return MediaCandidate(
            source=metadata.source,
            url=info.get("webpage_url") or info.get("original_url") or info.get("url"),
            metadata=metadata,
            quality=quality,
            confidence=0.75 if info.get("_type") == "url" else 0.9,
            provider_payload={
                "provider": self,
                "format_selector": selector,
                "download_mode": _download_mode(intent, quality_mode),
                "audio_postprocess": _audio_postprocess(intent, quality_mode, ext),
                "quality_mode": quality_mode.value,
                "raw": info,
            },
        )

    def _candidates_from_entries(
        self,
        entries,
        intent: MediaIntent,
        quality_mode: QualityMode,
        policy: SourcePolicy,
        include_nested_items: bool = True,
    ) -> list[MediaCandidate]:
        candidates: list[MediaCandidate] = []
        for item in entries:
            if not item or not _source_allowed(item, policy):
                continue

            nested_entries = item.get("entries") if isinstance(item, dict) else None
            if nested_entries:
                nested_candidates = self._candidates_from_entries(
                    nested_entries,
                    intent,
                    quality_mode,
                    policy,
                    include_nested_items=include_nested_items,
                )
                collection = self._collection_candidate_from_info(
                    item, nested_candidates, intent, quality_mode
                )
                if collection:
                    candidates.append(collection)
                if include_nested_items:
                    candidates.extend(nested_candidates)
                continue

            candidate = self._candidate_from_info(item, intent, quality_mode)
            if candidate:
                candidates.append(candidate)
        return candidates

    def _collection_candidate_from_info(
        self,
        info: dict,
        entries: list[MediaCandidate],
        intent: MediaIntent,
        quality_mode: QualityMode,
    ) -> MediaCandidate | None:
        if not entries:
            return None

        title = info.get("title") or info.get("playlist_title") or "Collection"
        source = _collection_source(info, intent)
        ext = "srt" if intent == MediaIntent.TEXT else "playlist"
        quality = QualityClaim(
            codec=f"{len(entries)} item{'s' if len(entries) != 1 else ''}",
            container="playlist",
            is_real=True,
            transcoded=False,
        )
        metadata = MediaMetadata(
            title=title,
            artist=info.get("uploader") or info.get("channel") or "Various Artists",
            album_artist=info.get("uploader") or info.get("channel") or "Various Artists",
            album=title,
            channel=info.get("channel") or info.get("uploader") or "Unknown Channel",
            playlist_title=title,
            source=source,
            ext=ext,
            extra={
                "webpage_url": info.get("webpage_url") or info.get("original_url"),
                "thumbnail": info.get("thumbnail"),
                "version_flags": (),
                "collection_size": len(entries),
            },
        )
        return MediaCandidate(
            source=source,
            url=info.get("webpage_url") or info.get("original_url") or entries[0].url,
            metadata=metadata,
            quality=quality,
            confidence=0.95,
            provider_payload={
                "provider": self,
                "download_mode": "collection",
                "collection_entries": entries,
                "quality_mode": quality_mode.value,
                "raw": info,
            },
        )


def _select_quality(
    formats: list[dict], intent: MediaIntent, quality_mode: QualityMode
) -> tuple[QualityClaim | None, str]:
    if intent == MediaIntent.VIDEO:
        return (
            QualityClaim(codec="video+audio", container="mp4", is_real=True, transcoded=False),
            "bv*+ba/best",
        )

    if intent == MediaIntent.TEXT or quality_mode == QualityMode.SUBTITLES_ONLY:
        return (
            QualityClaim(codec="subtitles", container="srt", is_real=True, transcoded=False),
            "",
        )

    if intent == MediaIntent.METADATA or quality_mode == QualityMode.METADATA_ONLY:
        return (
            QualityClaim(codec="metadata", container="json", is_real=True, transcoded=False),
            "",
        )

    audio_formats = [
        fmt
        for fmt in formats
        if fmt.get("acodec") not in (None, "none") and fmt.get("vcodec") in (None, "none")
    ]
    if not audio_formats:
        audio_formats = [fmt for fmt in formats if fmt.get("acodec") not in (None, "none")]
    if quality_mode == QualityMode.OPUS_NATIVE:
        opus = _best_audio(audio_formats, codec_contains="opus")
        if not opus:
            return None, ""
        return _claim_from_format(opus, is_real=True), opus["format_id"]

    if quality_mode in {QualityMode.FLAC_REAL, QualityMode.HI_RES_REAL, QualityMode.MP3_320_REAL}:
        real = _find_real_quality(audio_formats, quality_mode)
        if not real:
            return None, ""
        return _claim_from_format(real, is_real=True), real["format_id"]

    best = _best_audio(audio_formats)
    if not best:
        return None, ""
    return _claim_from_format(best, is_real=True), best["format_id"]


def _best_audio(formats: list[dict], codec_contains: str | None = None) -> dict | None:
    candidates = formats
    if codec_contains:
        candidates = [
            fmt for fmt in formats if codec_contains.lower() in str(fmt.get("acodec", "")).lower()
        ]
    if not candidates:
        return None
    return max(candidates, key=_audio_format_rank)


def _audio_format_rank(fmt: dict) -> tuple[int, float]:
    acodec = str(fmt.get("acodec") or "").lower()
    ext = str(fmt.get("ext") or "").lower()
    codec_rank = 0
    if "flac" in acodec or ext in {"flac", "wav", "aiff", "alac"}:
        codec_rank = 50
    elif "opus" in acodec:
        codec_rank = 40
    elif "mp4a" in acodec or "aac" in acodec or ext == "m4a":
        codec_rank = 30
    elif "vorbis" in acodec or ext == "ogg":
        codec_rank = 20
    elif "mp3" in acodec or ext == "mp3":
        codec_rank = 10
    return codec_rank, float(fmt.get("abr") or fmt.get("tbr") or 0)


def _find_real_quality(formats: list[dict], quality_mode: QualityMode) -> dict | None:
    for fmt in sorted(formats, key=lambda item: item.get("abr") or item.get("tbr") or 0, reverse=True):
        acodec = str(fmt.get("acodec") or "").lower()
        ext = str(fmt.get("ext") or "").lower()
        abr = fmt.get("abr") or fmt.get("tbr") or 0
        if quality_mode == QualityMode.FLAC_REAL and ("flac" in acodec or ext == "flac"):
            return fmt
        if quality_mode == QualityMode.HI_RES_REAL and ("flac" in acodec or ext in {"flac", "wav"}):
            if int(fmt.get("asr") or 0) >= 48000:
                return fmt
        if quality_mode == QualityMode.MP3_320_REAL and ("mp3" in acodec or ext == "mp3"):
            if abr >= 300:
                return fmt
    return None


def _claim_from_format(fmt: dict, is_real: bool) -> QualityClaim:
    codec = str(fmt.get("acodec") or fmt.get("ext") or "audio").split(".")[0]
    abr = fmt.get("abr") or fmt.get("tbr")
    ext = str(fmt.get("ext") or "")
    sample_rate = fmt.get("asr")
    is_lossless = codec.lower() == "flac" or ext.lower() in {"flac", "wav", "aiff", "alac"}
    return QualityClaim(
        codec=codec,
        container=ext,
        bitrate_kbps=round(abr) if abr else None,
        sample_rate_hz=int(sample_rate) if sample_rate else None,
        is_lossless=is_lossless,
        is_real=is_real,
        transcoded=False,
        notes=tuple(str(note) for note in [fmt.get("format_note")] if note),
    )


def _verify_downloaded_quality(
    path: Path, candidate: MediaCandidate, registry: ToolRegistry
) -> None:
    verified_quality = inspect_audio(path, registry)
    requested_quality = QualityMode(
        candidate.provider_payload.get("quality_mode", QualityMode.BEST_AVAILABLE)
    )
    if not quality_satisfies(verified_quality, requested_quality):
        raise RuntimeError(
            f"Downloaded file is {verified_quality.summary()}, not {requested_quality.value}."
        )
    candidate.quality = verified_quality
    try:
        candidate.metadata.duration_seconds = inspect_duration(path, registry)
    except Exception:
        pass


def _looks_like_url(value: str) -> bool:
    parsed = urlparse(value)
    return bool(parsed.scheme and parsed.netloc)


def _duration_seconds(value) -> int | None:
    try:
        seconds = round(float(value))
    except (TypeError, ValueError):
        return None
    return seconds if seconds > 0 else None


def _info_int(info: dict, key: str) -> int | None:
    try:
        value = int(info.get(key) or 0)
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None


def _targets_for_query(query: str, policy: SourcePolicy, intent: MediaIntent) -> list[str]:
    if _looks_like_url(query):
        return [query]

    targets = []
    if policy.youtube:
        if intent == MediaIntent.AUDIO:
            targets.append(f"https://music.youtube.com/search?q={quote_plus(query)}")
            targets.append(f"ytsearch5:{query}")
        else:
            targets.append(f"ytsearch10:{query}")
    if intent == MediaIntent.AUDIO and policy.soundcloud:
        targets.append(f"scsearch5:{query}")
    return targets


def _collection_source(info: dict, intent: MediaIntent) -> str:
    extractor = str(info.get("extractor_key") or info.get("ie_key") or "").lower()
    if "youtube" in extractor:
        if intent == MediaIntent.AUDIO:
            return "YouTube Music collection"
        return "YouTube collection"
    if "soundcloud" in extractor:
        return "SoundCloud collection"
    if "bandcamp" in extractor:
        return "Bandcamp collection"
    if "archive" in extractor:
        return "Archive.org collection"
    return "yt-dlp collection"


def _source_allowed(info: dict, policy: SourcePolicy) -> bool:
    extractor = str(info.get("extractor_key") or info.get("ie_key") or "").lower()
    url = str(info.get("webpage_url") or info.get("original_url") or info.get("url") or "").lower()
    if "youtube" in extractor or "youtu" in url:
        return policy.youtube
    if "soundcloud" in extractor or "soundcloud.com" in url:
        return policy.soundcloud
    if "bandcamp" in extractor or "bandcamp.com" in url:
        return policy.bandcamp
    if "archive" in extractor or "archive.org" in url:
        return policy.archive
    return policy.direct


def _source_name_from_info(info: dict) -> str:
    url = str(info.get("webpage_url") or info.get("original_url") or info.get("url") or "").lower()
    if "music.youtube.com" in url:
        return "YouTube Music"
    extractor = str(info.get("extractor_key") or "yt-dlp")
    if extractor.lower() == "youtube":
        return "YouTube"
    return extractor


def _is_search_collection(target: str, info: dict) -> bool:
    if _is_search_target(target):
        return True
    url = str(info.get("webpage_url") or info.get("original_url") or target).lower()
    return "/search" in url or "search_query=" in url


def _is_search_target(target: str) -> bool:
    lowered = target.lower()
    return (
        lowered.startswith("ytsearch")
        or lowered.startswith("scsearch")
        or "/search?" in lowered
        or "search_query=" in lowered
    )


def _download_mode(intent: MediaIntent, quality_mode: QualityMode) -> str:
    if intent == MediaIntent.TEXT or quality_mode == QualityMode.SUBTITLES_ONLY:
        return "subtitles"
    if intent == MediaIntent.METADATA or quality_mode == QualityMode.METADATA_ONLY:
        return "metadata"
    return "media"


def _audio_postprocess(
    intent: MediaIntent, quality_mode: QualityMode, target_ext: str = ""
) -> str | None:
    if intent != MediaIntent.AUDIO:
        return None
    if quality_mode == QualityMode.OPUS_NATIVE:
        return "opus"
    if quality_mode == QualityMode.BEST_AVAILABLE and target_ext in {"opus", "m4a", "mp3", "flac"}:
        return target_ext
    return None


def _audio_extension_from_quality(quality: QualityClaim) -> str:
    codec = quality.codec.lower()
    container = quality.container.lower()
    if "opus" in codec:
        return "opus"
    if "mp4a" in codec or "aac" in codec:
        return "m4a"
    if "mp3" in codec:
        return "mp3"
    if container:
        return container
    return "mka"


def _normalize_expected_audio_files(
    paths: list[Path], candidate: MediaCandidate, registry: ToolRegistry
) -> list[Path]:
    if candidate.metadata.ext != "opus":
        return paths

    normalized: list[Path] = []
    for path in paths:
        if path.suffix.lower() == ".webm":
            normalized.append(_remux_webm_opus(path, registry))
        else:
            normalized.append(path)
    return normalized


def _remux_webm_opus(path: Path, registry: ToolRegistry) -> Path:
    if not registry.ffmpeg.available or not registry.ffmpeg.path:
        return path

    target = path.with_suffix(".opus")
    if target == path:
        return path
    if target.exists():
        target.unlink()

    command = [
        str(registry.ffmpeg.path),
        "-y",
        "-i",
        str(path),
        "-map",
        "0:a:0",
        "-c",
        "copy",
        str(target),
    ]
    subprocess.run(command, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if target.exists():
        try:
            path.unlink()
        except OSError:
            pass
        return target
    return path


def _snapshot(root: Path) -> set[Path]:
    if not root.exists():
        return set()
    return {path for path in root.rglob("*") if path.is_file()}


class _QuietLogger:
    def debug(self, message: str) -> None:
        pass

    def warning(self, message: str) -> None:
        pass

    def error(self, message: str) -> None:
        pass
