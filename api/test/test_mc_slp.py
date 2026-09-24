"""Tests for api.mc.slp: the mcstatus-backed status probe.

Mocks ``mcstatus.JavaServer`` so the suite never opens a real socket.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from api.mc import slp


def _fake_status(players_online=3, players_max=20, version="1.20.1", motd="A Minecraft Server", latency=12.3):
    """Build a minimal stand-in for mcstatus's JavaStatusResponse."""
    return SimpleNamespace(
        players=SimpleNamespace(online=players_online, max=players_max),
        version=SimpleNamespace(name=version),
        motd=SimpleNamespace(to_plain=lambda: motd),
        latency=latency,
    )


class TestProbe:
    async def test_probe_success(self, monkeypatch):
        server = AsyncMock()
        server.async_status.return_value = _fake_status()
        monkeypatch.setattr(slp, "JavaServer", lambda *a, **kw: server)

        status = await slp.probe("localhost", 25565)

        assert status.online is True
        assert status.players_online == 3
        assert status.players_max == 20
        assert status.version == "1.20.1"
        assert status.motd == "A Minecraft Server"
        assert status.latency_ms == 12.3
        assert status.error is None
        server.async_status.assert_awaited_once_with(tries=1)

    async def test_probe_connection_refused(self, monkeypatch):
        server = AsyncMock()
        server.async_status.side_effect = ConnectionRefusedError("connection refused")
        monkeypatch.setattr(slp, "JavaServer", lambda *a, **kw: server)

        status = await slp.probe("localhost", 25565)

        assert status.online is False
        assert status.players_online is None
        assert status.error is not None

    async def test_probe_timeout(self, monkeypatch):
        server = AsyncMock()
        server.async_status.side_effect = TimeoutError("timed out")
        monkeypatch.setattr(slp, "JavaServer", lambda *a, **kw: server)

        status = await slp.probe("localhost", 25565, timeout=0.1)

        assert status.online is False
        assert status.error is not None

    async def test_probe_protocol_error(self, monkeypatch):
        server = AsyncMock()
        server.async_status.side_effect = ValueError("malformed status response")
        monkeypatch.setattr(slp, "JavaServer", lambda *a, **kw: server)

        status = await slp.probe("localhost", 25565)

        assert status.online is False
        assert status.error is not None

    async def test_probe_zero_players(self, monkeypatch):
        server = AsyncMock()
        server.async_status.return_value = _fake_status(players_online=0)
        monkeypatch.setattr(slp, "JavaServer", lambda *a, **kw: server)

        status = await slp.probe("localhost", 25565)

        assert status.online is True
        assert status.players_online == 0
