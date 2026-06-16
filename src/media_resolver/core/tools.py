from __future__ import annotations

import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from media_resolver.core.display import safe_text

if TYPE_CHECKING:
    from rich.console import Console


SOURCE_PROJECT_ROOT = Path(__file__).resolve().parents[3]


@dataclass(frozen=True)
class Tool:
    name: str
    path: Path | None
    required_for_basic: bool = False

    @property
    def available(self) -> bool:
        return self.path is not None


@dataclass(frozen=True)
class ToolRegistry:
    yt_dlp: Tool
    ffmpeg: Tool
    ffprobe: Tool
    fpcalc: Tool
    aria2c: Tool
    deno: Tool

    @classmethod
    def discover(cls) -> "ToolRegistry":
        return cls(
            yt_dlp=_find_tool("yt-dlp", "yt-dlp.exe", required=True),
            ffmpeg=_find_tool("ffmpeg", "ffmpeg.exe", required=True),
            ffprobe=_find_tool("ffprobe", "ffprobe.exe", required=True),
            fpcalc=_find_tool("fpcalc", "fpcalc.exe"),
            aria2c=_find_tool("aria2c", "aria2c.exe"),
            deno=_find_tool("deno", "deno.exe"),
        )

    def missing_for_basic_downloads(self) -> list[str]:
        return [
            tool.name
            for tool in [self.yt_dlp, self.ffmpeg, self.ffprobe]
            if tool.required_for_basic and not tool.available
        ]

    def render(self, console: "Console") -> None:
        from rich.table import Table

        table = Table(title="Helper tools")
        table.add_column("Tool")
        table.add_column("Status")
        table.add_column("Path")
        for tool in [
            self.yt_dlp,
            self.ffmpeg,
            self.ffprobe,
            self.fpcalc,
            self.aria2c,
            self.deno,
        ]:
            table.add_row(
                tool.name,
                "[green]available[/green]" if tool.available else "[red]missing[/red]",
                safe_text(tool.path or ""),
            )
        console.print(table)


def _find_tool(name: str, exe_name: str, required: bool = False) -> Tool:
    for local_root in _candidate_vendor_bins():
        local = local_root / exe_name
        if local.exists():
            return Tool(name=name, path=local, required_for_basic=required)

    found = shutil.which(exe_name) or shutil.which(name)
    return Tool(name=name, path=Path(found) if found else None, required_for_basic=required)


def _candidate_vendor_bins() -> list[Path]:
    exe_dir = Path(sys.executable).resolve().parent
    cwd_direct_bin = Path.cwd() / "bin"
    cwd_bin = Path.cwd() / "vendor" / "bin"
    exe_direct_bin = exe_dir / "bin"
    exe_vendor_bin = exe_dir / "vendor" / "bin"
    exe_parent_vendor_bin = exe_dir.parent / "vendor" / "bin"
    source_bin = SOURCE_PROJECT_ROOT / "vendor" / "bin"
    candidates = [
        cwd_direct_bin,
        cwd_bin,
        exe_direct_bin,
        exe_vendor_bin,
        exe_parent_vendor_bin,
        source_bin,
    ]
    deduped: list[Path] = []
    for candidate in candidates:
        if candidate not in deduped:
            deduped.append(candidate)
    return deduped
