from __future__ import annotations

import re
from dataclasses import asdict
from string import Formatter
from typing import TYPE_CHECKING, Iterable

from media_resolver.core.display import safe_text
from media_resolver.core.models import MediaMetadata

if TYPE_CHECKING:
    from rich.console import Console

WINDOWS_RESERVED = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    "COM1",
    "COM2",
    "COM3",
    "COM4",
    "COM5",
    "COM6",
    "COM7",
    "COM8",
    "COM9",
    "LPT1",
    "LPT2",
    "LPT3",
    "LPT4",
    "LPT5",
    "LPT6",
    "LPT7",
    "LPT8",
    "LPT9",
}


class NamingTemplate:
    def __init__(self, template: str) -> None:
        self.template = template
        self._validate()

    def render(self, metadata: MediaMetadata) -> str:
        data = {
            key: _sanitize_template_value(value)
            for key, value in asdict(metadata).items()
        }
        rendered = self.template.format(**data)
        return sanitize_path(rendered)

    def _validate(self) -> None:
        valid_fields = set(MediaMetadata.__dataclass_fields__.keys())
        for _, field_name, _, _ in Formatter().parse(self.template):
            if field_name is None:
                continue
            base = field_name.split(":", 1)[0]
            if base and base not in valid_fields:
                raise ValueError(f"Unknown naming field: {base}")


def sanitize_path(value: str) -> str:
    parts = re.split(r"[\\/]+", value)
    sanitized = [_sanitize_part(part) for part in parts if part.strip()]
    return "/".join(sanitized)


def _sanitize_part(value: str) -> str:
    value = re.sub(r'[<>:"|?*\x00-\x1f]', "_", value).strip()
    value = re.sub(r"\s+", " ", value)
    value = value.rstrip(". ")
    if not value:
        return "_"
    if value.upper() in WINDOWS_RESERVED:
        return f"_{value}"
    return value


def _sanitize_template_value(value):
    if not isinstance(value, str):
        return value
    value = re.sub(r'[<>:"|?*\x00-\x1f\\/]+', "_", value).strip()
    value = re.sub(r"\s+", " ", value)
    return value.rstrip(". ") or "_"


def render_preview_table(
    console: "Console", metadata_items: Iterable[MediaMetadata], naming: NamingTemplate
) -> None:
    from rich.table import Table

    table = Table(title="Filename preview")
    table.add_column("#", justify="right")
    table.add_column("Output path")
    for idx, metadata in enumerate(metadata_items, start=1):
        table.add_row(str(idx), safe_text(naming.render(metadata)))
    console.print(table)
