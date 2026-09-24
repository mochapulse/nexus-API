"""CLI command handlers.

Non-TUI commands (config, wol, health, poweroff, sleep, mc-server) are
implemented here.  TUI commands (telemetry) live in their own modules
because they run a full-screen Textual app.

Every handler shares the same signature, ``handler(args:
argparse.Namespace) -> None``, so :func:`api.cli.main` can dispatch
uniformly; handlers that do not need any parsed arguments simply leave
``args`` unused.

Functions
---------
cmd_config(args)
    Open the ``.env`` file in VS Code.
cmd_wol(args)
    Send a Wake-on-LAN packet to the ESP32.
cmd_health(args)
    Print the Nexus API health status.
cmd_poweroff(args)
    Power off the Nexus API host.
cmd_sleep(args)
    Put the Nexus API host to sleep.
cmd_mc_server(args)
    Arm, disarm, or inspect the Minecraft server watchdog.
"""

import argparse
import shutil
import subprocess
import sys

import api.config.runtime as runtime
from api.config.paths import DOTENV_PATH
from api.cli.http_client import esp_post, nexus_delete, nexus_get, nexus_post
from api.lib.durations import format_duration, parse_duration

#: Human-readable text for each ``last_disarm_reason`` value in the
#: watchdog status payload (see ``templates/get-mc-server-watchdog.jsonc``).
_DISARM_REASONS = {
    None: "-",
    "manual": "manual",
    "expired": "window expired",
    "mc_unrecoverable": "MC unrecoverable after restarts",
    "poweroff_failed": "poweroff failed",
}


def cmd_config(args: argparse.Namespace) -> None:
    """Open the ``.env`` file in VS Code.

    Uses ``code`` (VS Code CLI) to open the file for editing.
    Exits with an error if the file does not exist or VS Code is not installed.

    Args:
        args: Parsed arguments (unused; ``config`` takes no options).
    """
    if not DOTENV_PATH.exists():
        print(f"Error: .env file not found at {DOTENV_PATH}", file=sys.stderr)
        sys.exit(1)
    code = shutil.which("code")
    if not code:
        print("Error: VS Code CLI ('code') not found on PATH.", file=sys.stderr)
        print("Install VS Code and ensure 'code' is available on PATH.", file=sys.stderr)
        sys.exit(1)
    print(f"Opening {DOTENV_PATH} in VS Code...")
    subprocess.run([code, str(DOTENV_PATH)], check=False)


def cmd_wol(args: argparse.Namespace) -> None:
    """Send a Wake-on-LAN packet to the ESP32.

    Posts to ``/api/wol`` on the ESP device.  Fails immediately if
    ``DEBUG`` is enabled to prevent accidental triggers during development.

    Args:
        args: Parsed arguments (unused; ``wol`` takes no options).
    """
    if runtime.DEBUG:
        print("Error: WOL is disabled in DEBUG mode.", file=sys.stderr)
        sys.exit(1)

    if not runtime.ESP_IP or not runtime.ESP_PORT:
        print(
            "Error: ESP_IP and ESP_PORT must be set in .env", file=sys.stderr
        )
        sys.exit(1)

    print(f"Sending WOL to ESP at {runtime.ESP_IP}:{runtime.ESP_PORT}...")
    try:
        resp = esp_post("api/wol")
        data = resp.json()
        if data.get("ok"):
            print("WOL packet sent successfully.")
        else:
            print(f"WOL failed: {data}", file=sys.stderr)
            sys.exit(1)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_health(args: argparse.Namespace) -> None:
    """Print the Nexus API health status.

    Fetches ``/api/v1/health`` and displays the response in a formatted
    table.

    Args:
        args: Parsed arguments (unused; ``health`` takes no options).
    """
    try:
        resp = nexus_get("health")
        data = resp.json()
        _print_health(data)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


def _print_health(data: dict) -> None:
    """Format and print health response data.

    Parameters
    ----------
    data : dict
        Parsed JSON response from ``/api/v1/health``.
    """
    print(f"  {'Status:':<20} {data.get('status', '?')}")
    print(f"  {'Version:':<20} {data.get('version', '?')}")
    print(f"  {'Uptime:':<20} {_format_uptime(data.get('uptime_seconds', 0))}")
    print(f"  {'Timestamp:':<20} {data.get('timestamp', '?')}")
    print(
        f"  {'Last DNS update:':<20} "
        f"{data.get('last_duckdns_update_ms') or 'never'}"
    )
    print(
        f"  {'Connectivity ms:':<20} "
        f"{data.get('connectivity_delay_ms') or 'n/a'}"
    )


def _format_uptime(seconds: int) -> str:
    """Convert seconds to a human-readable uptime string.

    Parameters
    ----------
    seconds : int
        Uptime in seconds.

    Returns:
        Formatted string (e.g. ``"2h 15m 30s"``).
    """
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}h {m}m {s}s"
    if m:
        return f"{m}m {s}s"
    return f"{s}s"


def cmd_poweroff(args: argparse.Namespace) -> None:
    """Power off the Nexus API host.

    Posts to ``/api/v1/power/poweroff``.  Fails immediately if ``DEBUG``
    is enabled to prevent accidental shutdowns during development.

    Args:
        args: Parsed arguments (unused; ``poweroff`` takes no options).
    """
    if runtime.DEBUG:
        print("Error: poweroff is disabled in DEBUG mode.", file=sys.stderr)
        sys.exit(1)

    confirm = input("Power off the server? [y/N] ").strip().lower()
    if confirm != "y":
        print("Aborted.")
        return

    print("Sending poweroff command...")
    try:
        resp = nexus_post("power/poweroff")
        if resp.status_code == 200:
            data = resp.json()
            print(f"Poweroff triggered: {data.get('poweroff_triggered')}")
        else:
            print(f"Poweroff failed: {resp.json()}", file=sys.stderr)
            sys.exit(1)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_sleep(args: argparse.Namespace) -> None:
    """Put the Nexus API host to sleep (S3 suspend-to-RAM).

    Posts to ``/api/v1/power/sleep``.  Fails immediately if ``DEBUG``
    is enabled to prevent accidental suspends during development.

    Args:
        args: Parsed arguments (unused; ``sleep`` takes no options).
    """
    if runtime.DEBUG:
        print("Error: sleep is disabled in DEBUG mode.", file=sys.stderr)
        sys.exit(1)

    confirm = input("Put the server to sleep? [y/N] ").strip().lower()
    if confirm != "y":
        print("Aborted.")
        return

    print("Sending sleep command...")
    try:
        resp = nexus_post("power/sleep")
        if resp.status_code == 200:
            data = resp.json()
            print(f"Sleep triggered: {data.get('sleep_triggered')}")
        else:
            print(f"Sleep failed: {resp.json()}", file=sys.stderr)
            sys.exit(1)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_mc_server(args: argparse.Namespace) -> None:
    """Arm, disarm, or inspect the Minecraft server watchdog.

    Dispatches to the ``active`` / ``disable`` / ``status`` subcommand
    handlers. With no subcommand, prints the ``mc-server`` help and exits
    with status 1.

    Args:
        args: Parsed arguments. ``args.mc_command`` selects the
            subcommand; ``active`` additionally uses ``args.duration``
            and the optional ``args.extra`` ``["threshold", "<duration>"]``
            pair (already validated by argparse).
    """
    if args.mc_command == "active":
        _cmd_mc_server_active(args)
    elif args.mc_command == "disable":
        _cmd_mc_server_disable()
    elif args.mc_command == "status":
        _cmd_mc_server_status()
    else:
        args.mc_parser.print_help()
        sys.exit(1)


def _cmd_mc_server_active(args: argparse.Namespace) -> None:
    """Handle ``mc-server active <duration> [threshold <duration>]``.

    Args:
        args: Parsed arguments — ``args.duration`` and ``args.extra``.
    """
    try:
        active_seconds = parse_duration(args.duration)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    threshold_seconds = None
    if args.extra:
        # Validated by _ThresholdAction: exactly ["threshold", "<duration>"].
        try:
            threshold_seconds = parse_duration(args.extra[1])
        except ValueError as e:
            print(f"Error: {e}", file=sys.stderr)
            sys.exit(1)

    body: dict = {"active_seconds": active_seconds}
    if threshold_seconds is not None:
        body["threshold_seconds"] = threshold_seconds

    if runtime.DEBUG:
        print(
            "[DEBUG] No request sent. Would POST "
            f"/api/v1/mc-server/watchdog {body}"
        )
        _print_watchdog_status(
            _debug_watchdog_payload(
                remaining_seconds=active_seconds,
                threshold_seconds=threshold_seconds
                if threshold_seconds is not None
                else 1800,
                empty_seconds=None,
                players_online=None,
                mc_reachable=False,
            )
        )
        return

    try:
        resp = nexus_post("mc-server/watchdog", json=body)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    if resp.status_code // 100 != 2:
        _print_watchdog_error(resp)
        sys.exit(1)

    _print_watchdog_status(resp.json())


def _cmd_mc_server_disable() -> None:
    """Handle ``mc-server disable``."""
    if runtime.DEBUG:
        print("[DEBUG] No request sent. Would DELETE /api/v1/mc-server/watchdog")
        _print_watchdog_status(
            _debug_watchdog_payload(
                armed=False,
                deadline=None,
                remaining_seconds=0,
                empty_seconds=None,
                players_online=None,
                mc_reachable=False,
                last_disarm_reason="manual",
            )
        )
        return

    try:
        resp = nexus_delete("mc-server/watchdog")
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    if resp.status_code // 100 != 2:
        _print_watchdog_error(resp)
        sys.exit(1)

    _print_watchdog_status(resp.json())


def _cmd_mc_server_status() -> None:
    """Handle ``mc-server status``.

    Informational: a successful request exits 0 whether the watchdog is
    armed or not.
    """
    if runtime.DEBUG:
        print("[DEBUG] No request sent. Would GET /api/v1/mc-server/watchdog")
        _print_watchdog_status(_debug_watchdog_payload())
        return

    try:
        resp = nexus_get("mc-server/watchdog")
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    if resp.status_code // 100 != 2:
        _print_watchdog_error(resp)
        sys.exit(1)

    _print_watchdog_status(resp.json())


def _debug_watchdog_payload(**overrides) -> dict:
    """Build a placeholder watchdog status dict for DEBUG mode.

    Mirrors ``templates/get-mc-server-watchdog.jsonc`` (an armed,
    reachable, briefly-empty server); callers override individual fields
    to match the command being simulated (e.g. ``disable`` mirrors
    ``templates/delete-mc-server-watchdog.jsonc``).

    Args:
        **overrides: Fields to replace in the default payload.

    Returns:
        The placeholder status dict.
    """
    payload = {
        "armed": True,
        "deadline": "2026-09-24T04:00:00Z",
        "remaining_seconds": 18000,
        "threshold_seconds": 1800,
        "empty_seconds": 120,
        "players_online": 0,
        "mc_reachable": True,
        "restarts_used": 0,
        "max_restarts": 3,
        "last_disarm_reason": None,
    }
    payload.update(overrides)
    return payload


def _print_watchdog_error(resp) -> None:
    """Print a failed watchdog response's server detail to stderr.

    FastAPI's 422 validation errors carry ``detail`` as a list of
    ``{"loc": [...], "msg": ...}`` objects; render those readably instead
    of dumping the raw list.

    Args:
        resp: The failed :class:`httpx.Response`.
    """
    try:
        data = resp.json()
    except Exception:
        print(f"Error: HTTP {resp.status_code}: {resp.text}", file=sys.stderr)
        return

    detail = data.get("detail") if isinstance(data, dict) else data
    if isinstance(detail, list):
        print(f"Error: HTTP {resp.status_code}:", file=sys.stderr)
        for item in detail:
            if isinstance(item, dict):
                loc = " -> ".join(str(part) for part in item.get("loc", []))
                msg = item.get("msg", item)
                print(f"  {loc}: {msg}", file=sys.stderr)
            else:
                print(f"  {item}", file=sys.stderr)
    else:
        print(f"Error: HTTP {resp.status_code}: {detail}", file=sys.stderr)


def _print_watchdog_status(data: dict) -> None:
    """Format and print watchdog status response data.

    Parameters
    ----------
    data : dict
        Parsed JSON response from the ``/api/v1/mc-server/watchdog``
        ``POST``/``DELETE``/``GET`` endpoints (or a DEBUG placeholder of
        the same shape).
    """
    armed = data.get("armed", False)
    remaining = data.get("remaining_seconds")
    empty_seconds = data.get("empty_seconds")
    mc_reachable = data.get("mc_reachable", False)
    players_online = data.get("players_online")
    reason = data.get("last_disarm_reason")

    if not mc_reachable:
        players_display = "unreachable"
    elif players_online is None:
        players_display = "-"
    else:
        players_display = str(players_online)

    print(f"  {'Armed:':<20} {'yes' if armed else 'no'}")
    print(f"  {'Remaining:':<20} {format_duration(remaining) if remaining else '-'}")
    print(f"  {'Deadline:':<20} {data.get('deadline') or '-'}")
    print(f"  {'Threshold:':<20} {format_duration(data.get('threshold_seconds', 0))}")
    print(
        f"  {'Empty for:':<20} "
        f"{format_duration(empty_seconds) if empty_seconds is not None else '-'}"
    )
    print(f"  {'Players online:':<20} {players_display}")
    print(f"  {'MC reachable:':<20} {'yes' if mc_reachable else 'no'}")
    print(
        f"  {'Restarts:':<20} "
        f"{data.get('restarts_used', 0)}/{data.get('max_restarts', '?')}"
    )
    print(f"  {'Last disarm reason:':<20} {_DISARM_REASONS.get(reason, reason)}")
