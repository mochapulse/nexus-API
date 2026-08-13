"""Raw JSON output mode for telemetry commands.

Polls the target endpoint every 2 seconds and prints the pretty-printed
JSON response, clearing the screen on each refresh for a live-updating view.

Usage::

    nexus-API telemetry -j
    nexus-API telemetry esp -j
"""

from __future__ import annotations

import json
import sys
import time

from api.cli.http_client import esp_get, nexus_get

_INTERVAL = 2
_CLEAR = "\033[H\033[J"


def _poll_nexus() -> None:
    """Poll ``/api/v1/telemetry`` and print raw JSON."""
    while True:
        try:
            resp = nexus_get("telemetry")
            data = resp.json()
            print(_CLEAR + json.dumps(data, indent=2), flush=True)
        except KeyboardInterrupt:
            raise
        except Exception as e:
            print(_CLEAR + f"Error: {e}", file=sys.stderr, flush=True)
        time.sleep(_INTERVAL)


def _poll_esp() -> None:
    """Poll ESP32 ``/api/status`` and print raw JSON."""
    while True:
        try:
            resp = esp_get("api/status")
            data = resp.json()
            print(_CLEAR + json.dumps(data, indent=2), flush=True)
        except KeyboardInterrupt:
            raise
        except Exception as e:
            print(_CLEAR + f"Error: {e}", file=sys.stderr, flush=True)
        time.sleep(_INTERVAL)


def main(target: str) -> None:
    """Start the JSON polling loop for the given target.

    Parameters
    ----------
    target : str
        ``"nexus"`` or ``"esp"``.
    """
    try:
        if target == "esp":
            _poll_esp()
        else:
            _poll_nexus()
    except KeyboardInterrupt:
        print()
