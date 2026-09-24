"""Duration parsing and formatting for watchdog windows.

Accepts compact human-friendly duration strings such as ``5h``, ``30m``,
or ``1h-30m`` and converts them to seconds, and vice versa. Shared by the
CLI (which parses user input before sending it to the API) and the server
(which validates it again, since client input is never trusted).

Functions
---------
parse_duration(text)
    Parse a duration string into a whole number of seconds.
format_duration(seconds)
    Format a number of seconds into a compact human-readable string.
"""

import re


_DURATION_RE = re.compile(r"^(?:(\d+)h)?-?(?:(\d+)m)?$")


def parse_duration(text: str) -> int:
    """Parse a compact duration string into seconds.

    Accepted formats: ``5h``, ``10h``, ``1h``, ``30m``, ``1m``, ``1h-30m``,
    ``1h30m``. Matching is case-insensitive and surrounding whitespace is
    stripped. At least one of the hour/minute parts must be present and the
    total duration must be greater than zero. A dash is only accepted
    between the hour and minute parts (e.g. not as a leading or trailing
    character).

    Parameters
    ----------
    text : str
        The duration string to parse.

    Returns
    -------
    int
        The parsed duration in seconds.

    Raises
    ------
    ValueError
        If ``text`` does not match a valid duration format, or the parsed
        total is zero.
    """
    cleaned = text.strip().lower()
    if not cleaned or cleaned == "-":
        raise ValueError(
            f"invalid duration '{text}': use formats like 5h, 30m, 1h-30m"
        )

    match = _DURATION_RE.match(cleaned)
    if not match:
        raise ValueError(
            f"invalid duration '{text}': use formats like 5h, 30m, 1h-30m"
        )

    hours_raw, minutes_raw = match.groups()
    if hours_raw is None and minutes_raw is None:
        raise ValueError(
            f"invalid duration '{text}': use formats like 5h, 30m, 1h-30m"
        )

    # The dash is only meaningful as a separator between an hour part and a
    # minute part (e.g. "1h-30m"). Reject a dangling dash such as "1h-" or
    # "-30m", which the bare regex above would otherwise accept.
    if "-" in cleaned and (hours_raw is None or minutes_raw is None):
        raise ValueError(
            f"invalid duration '{text}': use formats like 5h, 30m, 1h-30m"
        )

    hours = int(hours_raw) if hours_raw is not None else 0
    minutes = int(minutes_raw) if minutes_raw is not None else 0
    total_seconds = hours * 3600 + minutes * 60

    if total_seconds == 0:
        raise ValueError(
            f"invalid duration '{text}': use formats like 5h, 30m, 1h-30m"
        )

    return total_seconds


def format_duration(seconds: int) -> str:
    """Format a number of seconds into a compact human-readable string.

    Examples: ``5400`` -> ``"1h 30m"``, ``90`` -> ``"1m 30s"``, ``45`` ->
    ``"45s"``.

    Parameters
    ----------
    seconds : int
        The duration in seconds. Expected to be non-negative.

    Returns
    -------
    str
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
