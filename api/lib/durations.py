"""Duration parsing and formatting for watchdog windows.

Accepts compact human-friendly duration strings such as ``5h``, ``30m``,
or ``1h-30m`` and converts them to seconds, and vice versa. Shared by the
CLI (which parses user input before sending it to the API) and the server
(which validates it again, since client input is never trusted).
"""

import re


_DURATION_RE = re.compile(r"^(?:(\d+)h)?-?(?:(\d+)m)?$")
_USAGE = "use formats like 5h, 30m, 1h-30m"


def parse_duration(text: str) -> int:
    """Parse a compact duration string (``5h``, ``30m``, ``1h-30m``,
    ``1h30m``) into seconds. Case-insensitive; surrounding whitespace is
    stripped. A dash is only accepted between the hour and minute parts
    (not leading/trailing), and the total must be greater than zero.

    Raises:
        ValueError: If ``text`` is not a valid duration, or totals zero.
    """
    cleaned = text.strip().lower()
    match = _DURATION_RE.match(cleaned) if cleaned and cleaned != "-" else None
    hours_raw, minutes_raw = match.groups() if match else (None, None)
    dangling_dash = "-" in cleaned and (hours_raw is None or minutes_raw is None)

    if not match or (hours_raw is None and minutes_raw is None) or dangling_dash:
        raise ValueError(f"invalid duration '{text}': {_USAGE}")

    total_seconds = int(hours_raw or 0) * 3600 + int(minutes_raw or 0) * 60
    if total_seconds == 0:
        raise ValueError(f"invalid duration '{text}': {_USAGE}")
    return total_seconds


def format_duration(seconds: int) -> str:
    """Format a number of seconds into a compact human-readable string.

    Examples: ``5400`` -> ``"1h 30m"``, ``90`` -> ``"1m 30s"``, ``45`` ->
    ``"45s"``.

    Args:
        seconds: The duration in seconds. Expected to be non-negative.

    Returns:
        The formatted duration, using the two largest non-zero units
        (hours, minutes, seconds). Zero seconds formats as ``"0s"``.
    """
    seconds = int(seconds)
    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)

    parts: list[str] = []
    if hours:
        parts.append(f"{hours}h")
    if minutes:
        parts.append(f"{minutes}m")
    if secs and not hours:
        parts.append(f"{secs}s")

    if not parts:
        return "0s"

    return " ".join(parts[:2])
