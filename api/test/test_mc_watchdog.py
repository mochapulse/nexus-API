"""Tests for api.mc.watchdog: pure tick() decisions, arm/disarm/snapshot,
and the polling loop with every side effect patched.

``systemctl``, real sockets, and ``asyncio.sleep`` are always patched or
faked: this suite must never call real systemctl, probe a real
Minecraft server, or actually sleep/power off the host.
"""

import asyncio
import logging
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest

from api.mc import watchdog
from api.mc.slp import McStatus


def _online(players: int) -> McStatus:
    return McStatus(
        online=True,
        players_online=players,
        players_max=20,
        version="1.20.1",
        motd="Create Chronicles",
        latency_ms=12.3,
        error=None,
    )


def _offline() -> McStatus:
    return McStatus(
        online=False,
        players_online=None,
        players_max=None,
        version=None,
        motd=None,
        latency_ms=None,
        error="connection refused",
    )


def _armed_state(**overrides) -> watchdog.WatchdogState:
    state = watchdog.WatchdogState(
        armed=True,
        armed_at=0.0,
        deadline=10_000.0,
        deadline_wall=datetime(2026, 9, 23, 23, 0, 0, tzinfo=timezone.utc),
        threshold_seconds=1800,
    )
    for key, value in overrides.items():
        setattr(state, key, value)
    return state


class TestTickDisarmed:
    def test_disarmed_is_always_noop(self):
        state = watchdog.WatchdogState(armed=False)
        action = watchdog.tick(state, now=100.0, probe=_online(0))
        assert action is watchdog.Action.NOOP


class TestTickPlayers:
    def test_players_online_resets_and_noops(self):
        state = _armed_state(empty_since=50.0)
        action = watchdog.tick(state, now=100.0, probe=_online(3))
        assert action is watchdog.Action.NOOP
        assert state.empty_since is None

    def test_player_joins_after_empty_resets_counter(self):
        state = _armed_state(empty_since=0.0)
        # Just under threshold, then a player joins.
        action = watchdog.tick(state, now=1000.0, probe=_online(1))
        assert action is watchdog.Action.NOOP
        assert state.empty_since is None


class TestTickEmpty:
    def test_empty_below_threshold_is_noop(self):
        state = _armed_state(empty_since=100.0, threshold_seconds=1800)
        action = watchdog.tick(state, now=1899.0, probe=_online(0))
        assert action is watchdog.Action.NOOP
        assert state.empty_since == 100.0

    def test_empty_exactly_at_threshold_powers_off(self):
        state = _armed_state(empty_since=100.0, threshold_seconds=1800)
        action = watchdog.tick(state, now=1900.0, probe=_online(0))
        assert action is watchdog.Action.POWEROFF

    def test_empty_since_starts_on_first_empty_probe(self):
        state = _armed_state(empty_since=None, threshold_seconds=1800)
        action = watchdog.tick(state, now=500.0, probe=_online(0))
        assert action is watchdog.Action.NOOP
        assert state.empty_since == 500.0


class TestTickExpiry:
    def test_expiry_with_players_online_disarms(self):
        state = _armed_state(deadline=1000.0)
        action = watchdog.tick(state, now=1000.0, probe=_online(5))
        assert action is watchdog.Action.DISARM_EXPIRED

    def test_expiry_beats_poweroff_when_both_due(self):
        # Empty well past threshold AND window expired: expiry wins,
        # per IMPLEMENT_MC_WATCHDOG.md ("disarm, no poweroff").
        state = _armed_state(
            deadline=1000.0, empty_since=0.0, threshold_seconds=100
        )
        action = watchdog.tick(state, now=1000.0, probe=_online(0))
        assert action is watchdog.Action.DISARM_EXPIRED


class TestTickUnreachable:
    def test_unreachable_triggers_restart(self):
        state = _armed_state(last_restart_at=None, restarts_used=0)
        action = watchdog.tick(state, now=100.0, probe=_offline())
        assert action is watchdog.Action.RESTART_MC

    def test_unreachable_inside_grace_waits(self):
        state = _armed_state(last_restart_at=100.0, restarts_used=1)
        action = watchdog.tick(
            state, now=100.0 + watchdog.STARTUP_GRACE - 1, probe=_offline()
        )
        assert action is watchdog.Action.NOOP

    def test_unreachable_after_grace_expires_restarts_again(self):
        state = _armed_state(last_restart_at=100.0, restarts_used=1)
        action = watchdog.tick(
            state, now=100.0 + watchdog.STARTUP_GRACE, probe=_offline()
        )
        assert action is watchdog.Action.RESTART_MC

    def test_max_restarts_reached_gives_up(self):
        state = _armed_state(
            last_restart_at=100.0, restarts_used=watchdog.MAX_RESTARTS
        )
        action = watchdog.tick(
            state, now=100.0 + watchdog.STARTUP_GRACE, probe=_offline()
        )
        assert action is watchdog.Action.DISARM_UNRECOVERABLE

    def test_unreachable_resets_empty_counter(self):
        state = _armed_state(empty_since=50.0, last_restart_at=None)
        watchdog.tick(state, now=100.0, probe=_offline())
        assert state.empty_since is None

    def test_recovery_resumes_counting_from_fresh(self):
        # After a restart, MC comes back online but empty: the empty
        # counter must start fresh, not resume from before the outage.
        state = _armed_state(
            empty_since=None, last_restart_at=100.0, restarts_used=1
        )
        action = watchdog.tick(state, now=500.0, probe=_online(0))
        assert action is watchdog.Action.NOOP
        assert state.empty_since == 500.0

    def test_restarts_used_not_reset_on_recovery(self):
        # Cap is per armed window, not per outage: only arm() resets it.
        state = _armed_state(restarts_used=2, last_restart_at=100.0)
        watchdog.tick(state, now=500.0, probe=_online(0))
        assert state.restarts_used == 2


class TestArm:
    def test_active_seconds_must_be_positive(self):
        state = watchdog.WatchdogState()
        with pytest.raises(ValueError):
            watchdog.arm(state, now=0.0, active_seconds=0, threshold_seconds=60)

    def test_threshold_seconds_must_be_positive(self):
        state = watchdog.WatchdogState()
        with pytest.raises(ValueError):
            watchdog.arm(state, now=0.0, active_seconds=60, threshold_seconds=-1)

    def test_arm_sets_deadline_and_defaults(self):
        state = watchdog.WatchdogState()
        watchdog.arm(state, now=100.0, active_seconds=3600, threshold_seconds=600)
        assert state.armed is True
        assert state.deadline == 3700.0
        assert state.threshold_seconds == 600
        assert state.empty_since is None
        assert state.restarts_used == 0
        assert state.last_disarm_reason is None

    def test_rearm_while_armed_resets_counters(self):
        state = _armed_state(
            empty_since=50.0, restarts_used=2, last_restart_at=90.0
        )
        watchdog.arm(state, now=200.0, active_seconds=100, threshold_seconds=30)
        assert state.deadline == 300.0
        assert state.threshold_seconds == 30
        assert state.empty_since is None
        assert state.restarts_used == 0
        assert state.last_restart_at is None
        assert state.last_disarm_reason is None


class TestDisarm:
    def test_disarm_sets_flag_and_reason(self):
        state = _armed_state()
        watchdog.disarm(state, "manual")
        assert state.armed is False
        assert state.last_disarm_reason == "manual"


class TestSnapshot:
    def test_disarmed_snapshot(self):
        state = watchdog.WatchdogState()
        result = watchdog.snapshot(state, now=100.0)
        assert result["armed"] is False
        assert result["deadline"] is None
        assert result["remaining_seconds"] == 0
        assert result["mc_reachable"] is False
        assert result["players_online"] is None
        assert result["empty_seconds"] is None

    def test_armed_online_with_players(self):
        state = _armed_state(last_probe=_online(4))
        result = watchdog.snapshot(state, now=100.0)
        assert result["armed"] is True
        assert result["mc_reachable"] is True
        assert result["players_online"] == 4
        assert result["empty_seconds"] is None
        assert result["deadline"] is not None
        assert result["deadline"].endswith("Z")

    def test_armed_online_empty_reports_elapsed_seconds(self):
        state = _armed_state(last_probe=_online(0), empty_since=40.0)
        result = watchdog.snapshot(state, now=100.0)
        assert result["players_online"] == 0
        assert result["empty_seconds"] == 60

    def test_unreachable_nulls_players_and_empty(self):
        state = _armed_state(last_probe=_offline(), empty_since=None)
        result = watchdog.snapshot(state, now=100.0)
        assert result["mc_reachable"] is False
        assert result["players_online"] is None
        assert result["empty_seconds"] is None

    def test_restarts_and_max_restarts_reported(self):
        state = _armed_state(restarts_used=2)
        result = watchdog.snapshot(state, now=100.0)
        assert result["restarts_used"] == 2
        assert result["max_restarts"] == watchdog.MAX_RESTARTS

    def test_disarm_reason_reported(self):
        state = _armed_state()
        watchdog.disarm(state, "mc_unrecoverable")
        result = watchdog.snapshot(state, now=100.0)
        assert result["last_disarm_reason"] == "mc_unrecoverable"

    def test_metadata_null_when_no_probe(self):
        state = watchdog.WatchdogState()
        result = watchdog.snapshot(state, now=100.0)
        assert result["players_max"] is None
        assert result["mc_version"] is None
        assert result["mc_motd"] is None
        assert result["mc_latency_ms"] is None

    def test_metadata_reported_when_online(self):
        state = _armed_state(last_probe=_online(4))
        result = watchdog.snapshot(state, now=100.0)
        assert result["players_max"] == 20
        assert result["mc_version"] == "1.20.1"
        assert result["mc_motd"] == "Create Chronicles"
        assert result["mc_latency_ms"] == 12.3

    def test_metadata_null_when_unreachable(self):
        state = _armed_state(last_probe=_offline())
        result = watchdog.snapshot(state, now=100.0)
        assert result["players_max"] is None
        assert result["mc_version"] is None
        assert result["mc_motd"] is None
        assert result["mc_latency_ms"] is None


class TestSnapshotExplicitProbe:
    """``snapshot(state, now, probe=...)`` — used by the live GET status
    probe, which must never touch ``state.last_probe`` (that field is
    owned exclusively by :func:`watchdog.tick`).
    """

    def test_explicit_probe_overrides_stale_last_probe(self):
        # Disarmed state with a stale last_probe from a prior armed window;
        # an explicit live probe must win.
        state = watchdog.WatchdogState(last_probe=_offline())
        result = watchdog.snapshot(state, now=100.0, probe=_online(2))
        assert result["mc_reachable"] is True
        assert result["players_online"] == 2
        assert result["players_max"] == 20
        assert result["mc_version"] == "1.20.1"

    def test_explicit_unreachable_probe_reports_unreachable(self):
        state = watchdog.WatchdogState(last_probe=_online(2))
        result = watchdog.snapshot(state, now=100.0, probe=_offline())
        assert result["mc_reachable"] is False
        assert result["players_online"] is None
        assert result["players_max"] is None
        assert result["mc_version"] is None

    def test_explicit_probe_none_falls_back_to_last_probe(self):
        state = _armed_state(last_probe=_online(5))
        result = watchdog.snapshot(state, now=100.0, probe=None)
        assert result["mc_reachable"] is True
        assert result["players_online"] == 5

    def test_explicit_probe_does_not_mutate_state(self):
        state = watchdog.WatchdogState(last_probe=None)
        watchdog.snapshot(state, now=100.0, probe=_online(1))
        assert state.last_probe is None

    def test_explicit_probe_empty_seconds_still_from_state_empty_since(self):
        state = _armed_state(empty_since=40.0)
        result = watchdog.snapshot(state, now=100.0, probe=_online(0))
        assert result["players_online"] == 0
        assert result["empty_seconds"] == 60


@pytest.fixture(autouse=True)
def _reset_global_state():
    """Isolate the module-level STATE singleton across tests."""
    original = watchdog.STATE
    watchdog.STATE = watchdog.WatchdogState()
    yield
    watchdog.STATE = original


class TestWatchdogLoop:
    async def test_poweroff_called_when_due(self):
        watchdog.arm(watchdog.STATE, now=0.0, active_seconds=10_000, threshold_seconds=100)
        watchdog.STATE.empty_since = 0.0

        with (
            patch.object(watchdog.time, "monotonic", return_value=200.0),
            patch.object(
                watchdog.slp, "probe", new=AsyncMock(return_value=_online(0))
            ) as probe,
            patch.object(watchdog.service, "restart") as restart,
            patch.object(watchdog.power, "system_poweroff", return_value=None) as poweroff,
            patch.object(
                watchdog.asyncio,
                "sleep",
                new=AsyncMock(side_effect=asyncio.CancelledError()),
            ),
        ):
            with pytest.raises(asyncio.CancelledError):
                await watchdog.watchdog_loop("localhost", 25565, "mc-server-create")

        probe.assert_awaited_once_with("localhost", 25565)
        poweroff.assert_called_once()
        restart.assert_not_called()

    async def test_restart_called_when_unreachable(self):
        watchdog.arm(watchdog.STATE, now=0.0, active_seconds=10_000, threshold_seconds=100)

        with (
            patch.object(watchdog.time, "monotonic", return_value=50.0),
            patch.object(watchdog.slp, "probe", new=AsyncMock(return_value=_offline())),
            patch.object(watchdog.service, "restart", return_value=None) as restart,
            patch.object(watchdog.power, "system_poweroff") as poweroff,
            patch.object(
                watchdog.asyncio,
                "sleep",
                new=AsyncMock(side_effect=asyncio.CancelledError()),
            ),
        ):
            with pytest.raises(asyncio.CancelledError):
                await watchdog.watchdog_loop("localhost", 25565, "mc-server-create")

        restart.assert_called_once_with("mc-server-create")
        poweroff.assert_not_called()
        assert watchdog.STATE.restarts_used == 1
        assert watchdog.STATE.last_restart_at == 50.0

    async def test_poweroff_failure_disarms_with_reason(self):
        watchdog.arm(watchdog.STATE, now=0.0, active_seconds=10_000, threshold_seconds=100)
        watchdog.STATE.empty_since = 0.0

        with (
            patch.object(watchdog.time, "monotonic", return_value=200.0),
            patch.object(watchdog.slp, "probe", new=AsyncMock(return_value=_online(0))),
            patch.object(
                watchdog.power, "system_poweroff", return_value="polkit denied"
            ),
            patch.object(
                watchdog.asyncio,
                "sleep",
                new=AsyncMock(side_effect=asyncio.CancelledError()),
            ),
        ):
            with pytest.raises(asyncio.CancelledError):
                await watchdog.watchdog_loop("localhost", 25565, "mc-server-create")

        assert watchdog.STATE.armed is False
        assert watchdog.STATE.last_disarm_reason == "poweroff_failed"

    async def test_disarmed_state_skips_probe_and_still_sleeps(self):
        watchdog.STATE.armed = False

        with (
            patch.object(watchdog.slp, "probe") as probe,
            patch.object(
                watchdog.asyncio,
                "sleep",
                new=AsyncMock(side_effect=asyncio.CancelledError()),
            ) as sleep,
        ):
            with pytest.raises(asyncio.CancelledError):
                await watchdog.watchdog_loop("localhost", 25565, "mc-server-create")

        probe.assert_not_called()
        sleep.assert_called_once_with(watchdog.PROBE_INTERVAL)

    async def test_probe_error_is_logged_and_loop_continues(self, caplog):
        # A probe that raises must not kill the task: the iteration is
        # logged and the loop tries again on the next tick.
        watchdog.arm(watchdog.STATE, now=0.0, active_seconds=10_000, threshold_seconds=100)

        with (
            patch.object(watchdog.time, "monotonic", return_value=50.0),
            patch.object(
                watchdog.slp,
                "probe",
                new=AsyncMock(side_effect=[RuntimeError("boom"), _online(3)]),
            ) as probe,
            patch.object(watchdog.service, "restart") as restart,
            patch.object(watchdog.power, "system_poweroff") as poweroff,
            patch.object(
                watchdog.asyncio,
                "sleep",
                new=AsyncMock(side_effect=[None, asyncio.CancelledError()]),
            ),
            caplog.at_level(logging.ERROR, logger="api.mc.watchdog"),
        ):
            with pytest.raises(asyncio.CancelledError):
                await watchdog.watchdog_loop("localhost", 25565, "mc-server-create")

        assert probe.call_count == 2
        restart.assert_not_called()
        poweroff.assert_not_called()
        assert "Unexpected error" in caplog.text

    async def test_disarm_during_probe_skips_action(self):
        # If the watchdog is disarmed by the HTTP endpoint while a probe
        # is in flight, the now-stale action must not be applied.
        watchdog.arm(watchdog.STATE, now=0.0, active_seconds=10_000, threshold_seconds=100)
        watchdog.STATE.empty_since = 0.0

        def _probe_then_disarm(host, port):
            watchdog.disarm(watchdog.STATE, "manual")
            return _online(0)

        with (
            patch.object(watchdog.time, "monotonic", return_value=200.0),
            patch.object(watchdog.slp, "probe", new=AsyncMock(side_effect=_probe_then_disarm)),
            patch.object(watchdog.service, "restart") as restart,
            patch.object(watchdog.power, "system_poweroff") as poweroff,
            patch.object(
                watchdog.asyncio,
                "sleep",
                new=AsyncMock(side_effect=asyncio.CancelledError()),
            ),
        ):
            with pytest.raises(asyncio.CancelledError):
                await watchdog.watchdog_loop("localhost", 25565, "mc-server-create")

        restart.assert_not_called()
        poweroff.assert_not_called()
        assert watchdog.STATE.armed is False
        assert watchdog.STATE.last_disarm_reason == "manual"
