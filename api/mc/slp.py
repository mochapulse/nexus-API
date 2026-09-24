"""Minecraft Java Edition server status probe.

Thin async wrapper over `mcstatus <https://pypi.org/project/mcstatus/>`_'s
Java status query. Replaces a hand-written Server List Ping client: see
``IMPLEMENT_MC_WATCHDOG.md`` for why (user request to simplify).
"""

import logging
from dataclasses import dataclass

from mcstatus import JavaServer

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class McStatus:
    """Result of a Minecraft Java Edition status probe.

    ``online`` reflects whether the server answered the status query.
    On success, ``players_online``, ``players_max``, ``version``, and
    ``motd`` carry the parsed status, ``latency_ms`` is the round-trip
    time reported by ``mcstatus``, and ``error`` is ``None``. On
    failure, every field except ``online`` and ``error`` is ``None``,
    and ``error`` holds a human-readable failure reason.
    """

    online: bool
    players_online: int | None
    players_max: int | None
    version: str | None
    motd: str | None
    latency_ms: float | None
    error: str | None


async def probe(host: str, port: int, timeout: float = 3.0) -> McStatus:
    """Probe a Minecraft Java Edition server for its status.

    Never raises: any connection, timeout, or protocol error from
    ``mcstatus`` is captured in the returned :class:`McStatus`. Uses a
    single attempt (``tries=1``) since the watchdog re-probes every
    :data:`~api.mc.watchdog.PROBE_INTERVAL` seconds anyway.

    Args:
        host: The server hostname or IP address.
        port: The server port.
        timeout: Connect/read timeout in seconds.

    Returns:
        An :class:`McStatus` describing the outcome. ``online`` is
        ``False`` and ``error`` is set on any failure.
    """
    try:
        server = JavaServer(host, port, timeout=timeout)
        status = await server.async_status(tries=1)
        return McStatus(
            online=True,
            players_online=status.players.online,
            players_max=status.players.max,
            version=status.version.name,
            motd=status.motd.to_plain(),
            latency_ms=status.latency,
            error=None,
        )
    except Exception as exc:
        log.debug("Minecraft status probe to %s:%d failed: %s", host, port, exc)
        return McStatus(
            online=False,
            players_online=None,
            players_max=None,
            version=None,
            motd=None,
            latency_ms=None,
            error=str(exc),
        )
