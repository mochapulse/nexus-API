"""CLI command handlers.

Non-TUI commands (config, wol, health, poweroff, sleep) are implemented
here.  TUI commands (telemetry) live in their own modules because they
run a full-screen Textual app.

Functions
---------
cmd_config()
    Open the ``.env`` file in VS Code.
cmd_wol()
    Send a Wake-on-LAN packet to the ESP32.
cmd_health()
    Print the Nexus API health status.
cmd_poweroff()
    Power off the Nexus API host.
cmd_sleep()
    Put the Nexus API host to sleep.
"""

import shutil
import subprocess
import sys

import api.config.runtime as runtime
from api.config.paths import DOTENV_PATH
from api.cli.http_client import esp_post, nexus_get, nexus_post


def cmd_config() -> None:
    """Open the ``.env`` file in VS Code.

    Uses ``code`` (VS Code CLI) to open the file for editing.
    Exits with an error if the file does not exist or VS Code is not installed.
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


def cmd_wol() -> None:
    """Send a Wake-on-LAN packet to the ESP32.

    Posts to ``/api/wol`` on the ESP device.  Fails immediately if
    ``DEBUG`` is enabled to prevent accidental triggers during development.
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


def cmd_health() -> None:
    """Print the Nexus API health status.

    Fetches ``/api/v1/health`` and displays the response in a formatted
    table.
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


def cmd_poweroff() -> None:
    """Power off the Nexus API host.

    Posts to ``/api/v1/power/poweroff``.  Fails immediately if ``DEBUG``
    is enabled to prevent accidental shutdowns during development.
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


def cmd_sleep() -> None:
    """Put the Nexus API host to sleep (S3 suspend-to-RAM).

    Posts to ``/api/v1/power/sleep``.  Fails immediately if ``DEBUG``
    is enabled to prevent accidental suspends during development.
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
