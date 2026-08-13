"""Background DuckDNS update service.

Runs as a single long-lived asyncio task managed by the FastAPI lifespan.
The service follows a simple cycle: wait for an outbound connection to
Google, update the DuckDNS record, then sleep for 5 hours.  If the update
fails, it retries every 5 minutes until the record is refreshed.

The entire loop shuts down cleanly when the task is cancelled during
application shutdown.

Functions
---------
duckdns_loop(domain, token)
    Main service coroutine — runs forever until cancelled.
"""

import asyncio
import logging
import time

import httpx

from api.net import state
from api.net.utils import update_duckdns

_CONNECTIVITY_HOST = "google.com"
_CONNECTIVITY_PORT = 443
_CONNECTIVITY_TIMEOUT = 5
_CONNECTIVITY_POLL_INTERVAL = 10
_UPDATE_RETRY_INTERVAL = 300
_UPDATE_IDLE_INTERVAL = 18_000

log = logging.getLogger(__name__)


async def duckdns_loop(domain: str, token: str) -> None:
    """Run the DuckDNS update cycle until the task is cancelled.

    Each iteration:

    1. Block until a TCP connection to ``google.com:443`` succeeds,
       polling every 10 seconds.  This guarantees the network is up
       before we attempt any external calls.
    2. Push the current public IP to DuckDNS.
    3. On success, sleep 5 hours before the next refresh.
    4. On failure, sleep 5 minutes and retry the full cycle.

    Args:
        domain: DuckDNS subdomain (e.g. ``"nexus-coffee"``).
        token: DuckDNS API token for the account that owns *domain*.
    """
    log.info("DuckDNS service started for %s.duckdns.org", domain)

    async with httpx.AsyncClient() as client:
        while True:
            await _wait_for_connectivity(log)

            result = await update_duckdns(domain, token, client)
            log.info(
                "DuckDNS update %s — %s",
                "OK" if result["success"] else "FAILED",
                result["message"],
            )

            if result["success"]:
                state.last_duckdns_update_ms = int(time.time() * 1000)
                log.info("Next refresh in %d hours", _UPDATE_IDLE_INTERVAL // 3600)
                await asyncio.sleep(_UPDATE_IDLE_INTERVAL)
            else:
                log.info(
                    "Retrying in %d seconds", _UPDATE_RETRY_INTERVAL
                )
                await asyncio.sleep(_UPDATE_RETRY_INTERVAL)


async def _wait_for_connectivity(log: logging.Logger) -> None:
    """Block until a TCP connection to Google succeeds.

    Probes ``google.com:443`` with :func:`asyncio.open_connection`.  The
    check is non-blocking with respect to the event loop — only the
    waiting coroutine is suspended.  Polls every
    ``_CONNECTIVITY_POLL_INTERVAL`` seconds.
    """
    while True:
        try:
            t0 = time.monotonic()
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(_CONNECTIVITY_HOST, _CONNECTIVITY_PORT),
                timeout=_CONNECTIVITY_TIMEOUT,
            )
            writer.close()
            await writer.wait_closed()
            state.connectivity_delay_ms = int((time.monotonic() - t0) * 1000)
            log.info(
                "Connectivity confirmed (%s:%s) in %d ms",
                _CONNECTIVITY_HOST,
                _CONNECTIVITY_PORT,
                state.connectivity_delay_ms,
            )
            return
        except (OSError, asyncio.TimeoutError):
            log.info(
                "Waiting for connectivity (%s:%s)...",
                _CONNECTIVITY_HOST,
                _CONNECTIVITY_PORT,
            )
            await asyncio.sleep(_CONNECTIVITY_POLL_INTERVAL)
