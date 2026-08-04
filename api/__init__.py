"""Nexus API — FastAPI backend serving health, telemetry, and power management endpoints."""

import subprocess
from pathlib import Path

_PROJECT_DIR = Path(__file__).resolve().parents[1]

_FALLBACK_VERSION = "0.1.0"


def _git_version() -> str | None:
    """Return the nearest ``v*`` tag reachable from HEAD, if any.

    Run once at import time; falls back to ``None`` when the code is not
    inside a git checkout (e.g. a plain tarball deployment) or git fails.
    A ``-dirty`` suffix is appended when the working tree has uncommitted
    changes.
    """
    try:
        output = subprocess.run(
            ["git", "describe", "--tags", "--abbrev=0", "--dirty", "--match", "v*"],
            cwd=_PROJECT_DIR,
            capture_output=True,
            text=True,
            timeout=2,
            check=True,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return None
    return output.lstrip("v")


__version__ = _git_version() or _FALLBACK_VERSION