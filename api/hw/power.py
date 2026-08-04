"""System power management via systemd.

Wraps ``systemctl poweroff`` and ``systemctl suspend`` with flags that
skip interactive authentication prompts and wall messages, so they can be
triggered headlessly by a daemon process.
"""

import subprocess


def system_poweroff() -> str | None:
    """Initiate an immediate, non-interactive system power-off.

    systemd orchestrates the shutdown: every running process receives
    SIGTERM first, then SIGKILL after the timeout, before power is cut.

    Returns:
        ``None`` on success, or the stderr message from ``systemctl``
        if the command failed.
    """
    return _run_systemctl("poweroff")


def system_sleep() -> str | None:
    """Initiate an immediate, non-interactive S3 (suspend-to-RAM) sleep.

    ``systemctl suspend`` targets the ``mem`` sleep state by default,
    which is ACPI S3: system context is kept in RAM and everything
    else is powered down.

    Returns:
        ``None`` on success, or the stderr message from ``systemctl``
        if the command failed.
    """
    return _run_systemctl("suspend")


def _run_systemctl(verb: str) -> str | None:
    """Execute a ``systemctl`` power verb.

    Args:
        verb: The systemctl verb to run (``"poweroff"`` or ``"suspend"``).

    Returns:
        ``None`` on success, or the stripped stderr message on failure.
    """
    try:
        # --no-ask-password: Prevents Polkit/systemd from popping up authentication prompts
        # --no-wall: Suppresses warning messages sent to terminal sessions
        subprocess.run(
            ["systemctl", verb, "--no-ask-password", "--no-wall"],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
        )
        return None
    except subprocess.CalledProcessError as e:
        return e.stderr.strip()
