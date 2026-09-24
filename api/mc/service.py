"""systemd unit control for the Minecraft server watchdog.

Thin wrappers over ``systemctl`` to query and restart the Minecraft
systemd unit. Used by the watchdog's recovery policy (see
``IMPLEMENT_MC_WATCHDOG.md``) to detect a crashed or hung server and
restart it. Every call runs with an explicit timeout and never uses a
shell.
"""

import logging
import subprocess

log = logging.getLogger(__name__)


def is_active(unit: str) -> str:
    """Return the systemd active-state of a unit.

    Args:
        unit: The systemd unit name, e.g. ``"mc-server-create"``.

    Returns:
        The state reported by ``systemctl is-active`` (e.g.
        ``"active"``, ``"failed"``, ``"inactive"``), stripped of
        whitespace. Returns ``"unknown"`` if the command times out,
        cannot be run, or returns no output.
    """
    try:
        result = subprocess.run(
            ["systemctl", "is-active", unit],
            capture_output=True,
            text=True,
            timeout=10,
        )
        return result.stdout.strip() or "unknown"
    except (subprocess.TimeoutExpired, OSError) as exc:
        log.warning("systemctl is-active %s failed: %s", unit, exc)
        return "unknown"


def restart(unit: str) -> str | None:
    """Restart a systemd unit.

    Args:
        unit: The systemd unit name, e.g. ``"mc-server-create"``.

    Returns:
        ``None`` on success, or an error message describing the
        failure: the stderr of a failed ``systemctl restart``, or a
        timeout/OS error message.
    """
    try:
        subprocess.run(
            ["systemctl", "restart", unit, "--no-ask-password"],
            check=True,
            capture_output=True,
            text=True,
            timeout=60,
        )
        return None
    except subprocess.CalledProcessError as exc:
        error = exc.stderr.strip() if exc.stderr else str(exc)
        log.warning("systemctl restart %s failed: %s", unit, error)
        return error
    except (subprocess.TimeoutExpired, OSError) as exc:
        log.warning("systemctl restart %s failed: %s", unit, exc)
        return str(exc)
