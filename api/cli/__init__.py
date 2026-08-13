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
health      Print the Nexus API health status.
poweroff    Power off the Nexus API host.
sleep       Put the Nexus API host to sleep.
"""

from __future__ import annotations

import argparse
import sys

from api.config.paths import ensure_dotenv


def _telemetry_handler(args: argparse.Namespace) -> None:
    """Dispatch telemetry to the correct TUI.

    Parameters
    ----------
    args : argparse.Namespace
        Parsed arguments — ``args.target`` is ``"nexus"`` or ``"esp"``.
    """
    if args.target == "esp":
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
    parser = argparse.ArgumentParser(
        prog="nexus-API",
        description="Nexus API command-line interface.",
    )
    sub = parser.add_subparsers(dest="command")
    sub.required = True

    sub.add_parser("config", help="Open the .env file in VS Code.")
    sub.add_parser("wol", help="Send WOL packet to the ESP32.")
    sub.add_parser("health", help="Print Nexus API health status.")
    sub.add_parser("poweroff", help="Power off the Nexus API host.")
    sub.add_parser("sleep", help="Put the Nexus API host to sleep.")

    telemetry = sub.add_parser(
        "telemetry", help="Launch a telemetry TUI dashboard."
    )
    telemetry.add_argument(
        "target",
        nargs="?",
        default="nexus",
        choices=["nexus", "esp"],
        help="Target device: nexus (default) or esp.",
    )

    return parser


def main() -> None:
    """Parse arguments and run the matching command."""
    ensure_dotenv()

    parser = build_parser()
    args = parser.parse_args()

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
