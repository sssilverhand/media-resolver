from __future__ import annotations

import json
import subprocess
from pathlib import Path

from media_resolver.core.tools import ToolRegistry


def fingerprint_audio(path: Path, registry: ToolRegistry) -> dict:
    if not registry.fpcalc.available or registry.fpcalc.path is None:
        return {}

    command = [str(registry.fpcalc.path), "-json", str(path)]
    try:
        result = subprocess.run(command, check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError:
        return {}
    return json.loads(result.stdout)
