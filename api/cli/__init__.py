"""Nexus API command-line interface.

Entry point for the ``nexus-API`` command.  Parses arguments and
dispatches to the appropriate handler.

Usage::

    nexus-API <command> [args]

Commands
--------
config      Open the .env file in VS Code.
wol         Send a Wake-on-LAN packet to the ESP32.
telemetry   Launch a TUI dashboard (default: Nexus).
            Use ``-j`` / ``--json`` for raw JSON output.
health      Print the Nexus API health status.
poweroff    Power off the Nexus API host.
sleep       Put the Nexus API host to sleep.
"""

from __future__ import annotations

import argparse
import sys

from api.config.paths import ensure_dotenv
import api.config.runtime as runtime


def _telemetry_handler(args: argparse.Namespace) -> None:
    """Dispatch telemetry to the correct TUI or JSON output.

    Parameters
    ----------
    args : argparse.Namespace
        Parsed arguments — ``args.target`` is ``"nexus"`` or ``"esp"``.
        ``args.json`` enables raw JSON output instead of the TUI.
    """
    if args.json:
        from api.cli.json_output import main as json_main

        json_main(args.target)
    elif args.target == "esp":
        from api.cli.esp_tui import main as esp_main

        esp_main()
    else:
        from api.cli.nexus_tui import main as nexus_main

        nexus_main()


def build_parser() -> argparse.ArgumentParser:
    """Build the argument parser for the ``nexus-API`` CLI.

    Returns:
        Configured :class:`argparse.ArgumentParser`.
    """
    epilog = """\
examples:
  nexus-API config          Open .env in VS Code
  nexus-API health          Show API health status
  nexus-API telemetry       Nexus TUI dashboard (default)
  nexus-API telemetry esp   ESP32 TUI dashboard
  nexus-API telemetry -j    Nexus raw JSON output
  nexus-API telemetry -j esp  ESP32 raw JSON output
  nexus-API wol             Wake ESP32 via WOL
  nexus-API poweroff        Shut down the API host
  nexus-API sleep           Suspend the API host
"""

    parser = argparse.ArgumentParser(
        prog="nexus-API",
        description="Nexus API command-line interface.",
        epilog=epilog,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command")

    sub.add_parser(
        "config",
        help="Open the .env file in VS Code.",
        description="Open the workstation .env file in VS Code for editing.",
    )
    sub.add_parser(
        "wol",
        help="Send WOL packet to the ESP32.",
        description="Send a Wake-on-LAN magic packet to power on the ESP32.",
    )
    sub.add_parser(
        "health",
        help="Print Nexus API health status.",
        description="Query the Nexus API /health endpoint and display status.",
    )
    sub.add_parser(
        "poweroff",
        help="Power off the Nexus API host.",
        description="Gracefully shut down the machine running the Nexus API.",
    )
    sub.add_parser(
        "sleep",
        help="Put the Nexus API host to sleep.",
        description="Suspend (sleep) the machine running the Nexus API.",
    )

    telemetry = sub.add_parser(
        "telemetry",
        help="Launch a telemetry TUI dashboard.",
        description="Launch a live Textual TUI with CPU, RAM, GPU, and sensor data.",
    )
    telemetry.add_argument(
        "target",
        nargs="?",
        default="nexus",
        choices=["nexus", "esp"],
        help="Target device: nexus (default) or esp.",
    )
    telemetry.add_argument(
        "-j",
        "--json",
        action="store_true",
        default=False,
        help="Print raw JSON instead of the TUI dashboard.",
    )

    return parser


def main() -> None:
    """Parse arguments and run the matching command."""
    ensure_dotenv()

    parser = build_parser()
    args = parser.parse_args()

    from api.cli.http_client import _NEXUS_BASE, _ESP_BASE

    print(f"Nexus API: {_NEXUS_BASE}")
    if runtime.ESP_IP:
        print(f"ESP32:     {_ESP_BASE}")

    if not args.command:
        parser.print_help()
        sys.exit(0)

    from api.cli.commands import (
        cmd_config,
        cmd_health,
        cmd_sleep,
        cmd_wol,
        cmd_poweroff,
    )

    handlers = {
        "config": cmd_config,
        "wol": cmd_wol,
        "health": cmd_health,
        "poweroff": cmd_poweroff,
        "sleep": cmd_sleep,
        "telemetry": _telemetry_handler,
    }

    handler = handlers.get(args.command)
    if handler:
        handler(args) if args.command == "telemetry" else handler()
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
