"""Tests for DuckDNS utilities and the background update service."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from api.net.utils import (
    _ip_from_ifconfig,
    _ip_from_myip_com,
    get_public_ip,
    update_duckdns,
)
from api.net import state
from api.net.duckdns_service import _wait_for_connectivity, duckdns_loop


class TestGetPublicIp:
    """IP resolution across primary and fallback services."""

    async def test_returns_ip_from_myip_com(self):
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_resp = MagicMock()
        mock_resp.text = '{"ip":"203.0.113.5"}'
        mock_client.get = AsyncMock(return_value=mock_resp)

        result = await get_public_ip(mock_client)
        assert result == "203.0.113.5"

    async def test_falls_back_to_ifconfig(self):
        mock_client = AsyncMock(spec=httpx.AsyncClient)

        def side_effect(url, **kwargs):
            mock_resp = MagicMock()
            if "myip.com" in str(url):
                raise httpx.ConnectError("connection refused")
            mock_resp.text = "198.51.100.7"
            return mock_resp

        mock_client.get = AsyncMock(side_effect=side_effect)
        result = await get_public_ip(mock_client)
        assert result == "198.51.100.7"

    async def test_returns_none_when_both_fail(self):
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.get = AsyncMock(side_effect=httpx.ConnectError("down"))

        result = await get_public_ip(mock_client)
        assert result is None

    async def test_returns_none_on_empty_ip(self):
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_resp = MagicMock()
        mock_resp.text = '{"ip":""}'

        call_count = 0

        def side_effect(url, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return mock_resp
            raise httpx.ConnectError("fallback also fails")

        mock_client.get = AsyncMock(side_effect=side_effect)

        result = await get_public_ip(mock_client)
        assert result is None


class TestIpFromMyipCom:
    """Direct tests for the primary IP fetcher."""

    async def test_parses_ip_from_json(self):
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_resp = MagicMock()
        mock_resp.text = '{"ip":"10.0.0.1","country":"US"}'
        mock_client.get = AsyncMock(return_value=mock_resp)

        result = await _ip_from_myip_com(mock_client)
        assert result == "10.0.0.1"

    async def test_returns_none_on_error(self):
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.get = AsyncMock(side_effect=httpx.ConnectError("timeout"))

        result = await _ip_from_myip_com(mock_client)
        assert result is None

    async def test_returns_none_on_empty_ip(self):
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_resp = MagicMock()
        mock_resp.text = '{"ip":"  "}'
        mock_client.get = AsyncMock(return_value=mock_resp)

        result = await _ip_from_myip_com(mock_client)
        assert result is None


class TestIpFromIfconfig:
    """Direct tests for the fallback IP fetcher."""

    async def test_parses_plain_text_ip(self):
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_resp = MagicMock()
        mock_resp.text = "  172.16.0.1  \n"
        mock_client.get = AsyncMock(return_value=mock_resp)

        result = await _ip_from_ifconfig(mock_client)
        assert result == "172.16.0.1"

    async def test_returns_none_on_error(self):
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.get = AsyncMock(side_effect=httpx.ConnectError("timeout"))

        result = await _ip_from_ifconfig(mock_client)
        assert result is None


class TestUpdateDuckdns:
    """DuckDNS update response handling."""

    async def test_success(self):
        mock_client = AsyncMock(spec=httpx.AsyncClient)

        async def fake_get(url, **kwargs):
            mock_resp = MagicMock()
            if "duckdns.org" in str(url):
                mock_resp.text = "OK"
            else:
                mock_resp.text = '{"ip":"203.0.113.5"}'
            return mock_resp

        mock_client.get = AsyncMock(side_effect=fake_get)

        result = await update_duckdns("nexus-coffee", "tok-123", mock_client)
        assert result["success"] is True
        assert result["domain"] == "nexus-coffee"
        assert result["ip"] == "203.0.113.5"
        assert "successfully" in result["message"].lower()

    async def test_duckdns_rejects_update(self):
        mock_client = AsyncMock(spec=httpx.AsyncClient)

        async def fake_get(url, **kwargs):
            mock_resp = MagicMock()
            if "duckdns.org" in str(url):
                mock_resp.text = "KO"
            else:
                mock_resp.text = '{"ip":"203.0.113.5"}'
            return mock_resp

        mock_client.get = AsyncMock(side_effect=fake_get)

        result = await update_duckdns("nexus-coffee", "bad-token", mock_client)
        assert result["success"] is False
        assert "rejected" in result["message"].lower()

    async def test_network_failure(self):
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_client.get = AsyncMock(side_effect=httpx.ConnectError("down"))

        result = await update_duckdns("nexus-coffee", "tok-123", mock_client)
        assert result["success"] is False
        assert "failed" in result["message"].lower()

    async def test_ip_detection_failure_still_updates(self):
        mock_client = AsyncMock(spec=httpx.AsyncClient)

        async def fake_get(url, **kwargs):
            mock_resp = MagicMock()
            if "duckdns.org" in str(url):
                mock_resp.text = "OK"
            else:
                raise httpx.ConnectError("IP services down")
            return mock_resp

        mock_client.get = AsyncMock(side_effect=fake_get)

        result = await update_duckdns("nexus-coffee", "tok-123", mock_client)
        assert result["success"] is True
        assert result["ip"] == "auto-detected"


class TestWaitForConnectivity:
    """TCP connectivity probe."""

    async def test_returns_immediately_on_success(self):
        mock_writer = MagicMock()
        mock_writer.close = MagicMock()
        mock_writer.wait_closed = AsyncMock()

        with patch(
            "api.net.duckdns_service.asyncio.open_connection",
            new_callable=AsyncMock,
            return_value=(MagicMock(), mock_writer),
        ):
            await _wait_for_connectivity(MagicMock())

    async def test_retries_on_failure_then_succeeds(self):
        call_count = 0
        mock_writer = MagicMock()
        mock_writer.close = MagicMock()
        mock_writer.wait_closed = AsyncMock()

        async def fake_open(host, port):
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise OSError("connection refused")
            return MagicMock(), mock_writer

        with patch(
            "api.net.duckdns_service.asyncio.open_connection",
            side_effect=fake_open,
        ):
            with patch(
                "api.net.duckdns_service.asyncio.wait_for",
                wraps=asyncio.wait_for,
            ):
                with patch(
                    "api.net.duckdns_service.asyncio.sleep",
                    new_callable=AsyncMock,
                ):
                    await _wait_for_connectivity(MagicMock())

        assert call_count == 3


class TestDuckdnsLoop:
    """The main service loop with mocked time."""

    async def test_success_sleeps_5_hours(self):
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_writer = MagicMock()
        mock_writer.close = MagicMock()
        mock_writer.wait_closed = AsyncMock()

        sleep_durations = []

        async def track_sleep(duration):
            sleep_durations.append(duration)
            if len(sleep_durations) >= 2:
                raise asyncio.CancelledError()

        with patch(
            "api.net.duckdns_service.httpx.AsyncClient",
        ) as mock_cm:
            mock_cm.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cm.__aexit__ = AsyncMock(return_value=False)
            with patch(
                "api.net.duckdns_service._wait_for_connectivity",
                new_callable=AsyncMock,
            ):
                with patch(
                    "api.net.duckdns_service.update_duckdns",
                    new_callable=AsyncMock,
                    return_value={"success": True, "message": "ok"},
                ):
                    with patch(
                        "api.net.duckdns_service.asyncio.sleep",
                        side_effect=track_sleep,
                    ):
                        with pytest.raises(asyncio.CancelledError):
                            await duckdns_loop("test", "tok")

        assert sleep_durations[0] == 18_000

    async def test_failure_retries_in_5_minutes(self):
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        sleep_durations = []

        async def track_sleep(duration):
            sleep_durations.append(duration)
            if len(sleep_durations) >= 2:
                raise asyncio.CancelledError()

        with patch(
            "api.net.duckdns_service.httpx.AsyncClient",
        ) as mock_cm:
            mock_cm.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cm.__aexit__ = AsyncMock(return_value=False)
            with patch(
                "api.net.duckdns_service._wait_for_connectivity",
                new_callable=AsyncMock,
            ):
                with patch(
                    "api.net.duckdns_service.update_duckdns",
                    new_callable=AsyncMock,
                    return_value={"success": False, "message": "KO"},
                ):
                    with patch(
                        "api.net.duckdns_service.asyncio.sleep",
                        side_effect=track_sleep,
                    ):
                        with pytest.raises(asyncio.CancelledError):
                            await duckdns_loop("test", "tok")

        assert sleep_durations[0] == 300

    async def test_waits_for_connectivity_before_updating(self):
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        connectivity_called = False
        update_called = False

        async def fake_connectivity(log):
            nonlocal connectivity_called
            connectivity_called = True

        async def fake_update(domain, token, client):
            nonlocal update_called
            update_called = True
            raise asyncio.CancelledError()

        with patch(
            "api.net.duckdns_service.httpx.AsyncClient",
        ) as mock_cm:
            mock_cm.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cm.__aexit__ = AsyncMock(return_value=False)
            with patch(
                "api.net.duckdns_service._wait_for_connectivity",
                side_effect=fake_connectivity,
            ):
                with patch(
                    "api.net.duckdns_service.update_duckdns",
                    side_effect=fake_update,
                ):
                    with pytest.raises(asyncio.CancelledError):
                        await duckdns_loop("test", "tok")

        assert connectivity_called
        assert update_called


class TestConnectivityDelayState:
    """Verify _wait_for_connectivity records latency in shared state."""

    async def test_sets_connectivity_delay_ms(self):
        mock_writer = MagicMock()
        mock_writer.close = MagicMock()
        mock_writer.wait_closed = AsyncMock()
        state.connectivity_delay_ms = None

        with patch(
            "api.net.duckdns_service.asyncio.open_connection",
            new_callable=AsyncMock,
            return_value=(MagicMock(), mock_writer),
        ):
            await _wait_for_connectivity(MagicMock())

        assert state.connectivity_delay_ms is not None
        assert isinstance(state.connectivity_delay_ms, int)
        assert state.connectivity_delay_ms >= 0

    async def test_delay_resets_on_retry(self):
        call_count = 0
        mock_writer = MagicMock()
        mock_writer.close = MagicMock()
        mock_writer.wait_closed = AsyncMock()
        state.connectivity_delay_ms = None

        async def fake_open(host, port):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise OSError("first attempt fails")
            return MagicMock(), mock_writer

        with patch(
            "api.net.duckdns_service.asyncio.open_connection",
            side_effect=fake_open,
        ):
            with patch(
                "api.net.duckdns_service.asyncio.wait_for",
                wraps=asyncio.wait_for,
            ):
                with patch(
                    "api.net.duckdns_service.asyncio.sleep",
                    new_callable=AsyncMock,
                ):
                    await _wait_for_connectivity(MagicMock())

        assert state.connectivity_delay_ms is not None
        assert call_count == 2


class TestDuckdnsUpdateTimestamp:
    """Verify duckdns_loop records last update timestamp."""

    async def test_sets_last_duckdns_update_ms_on_success(self):
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        state.last_duckdns_update_ms = None

        with patch(
            "api.net.duckdns_service.httpx.AsyncClient",
        ) as mock_cm:
            mock_cm.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cm.__aexit__ = AsyncMock(return_value=False)
            with patch(
                "api.net.duckdns_service._wait_for_connectivity",
                new_callable=AsyncMock,
            ):
                with patch(
                    "api.net.duckdns_service.update_duckdns",
                    new_callable=AsyncMock,
                    return_value={"success": True, "message": "ok"},
                ):
                    with patch(
                        "api.net.duckdns_service.asyncio.sleep",
                        new_callable=AsyncMock,
                        side_effect=AsyncMock(side_effect=asyncio.CancelledError()),
                    ):
                        with pytest.raises(asyncio.CancelledError):
                            await duckdns_loop("test", "tok")

        assert state.last_duckdns_update_ms is not None
        assert isinstance(state.last_duckdns_update_ms, int)

    async def test_no_timestamp_on_failure(self):
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        state.last_duckdns_update_ms = None

        with patch(
            "api.net.duckdns_service.httpx.AsyncClient",
        ) as mock_cm:
            mock_cm.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cm.__aexit__ = AsyncMock(return_value=False)
            with patch(
                "api.net.duckdns_service._wait_for_connectivity",
                new_callable=AsyncMock,
            ):
                with patch(
                    "api.net.duckdns_service.update_duckdns",
                    new_callable=AsyncMock,
                    return_value={"success": False, "message": "KO"},
                ):
                    with patch(
                        "api.net.duckdns_service.asyncio.sleep",
                        new_callable=AsyncMock,
                        side_effect=asyncio.CancelledError(),
                    ):
                        with pytest.raises(asyncio.CancelledError):
                            await duckdns_loop("test", "tok")

        assert state.last_duckdns_update_ms is None
