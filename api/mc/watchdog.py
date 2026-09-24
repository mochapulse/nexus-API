"""Minecraft server watchdog: state machine and polling loop.

See ``IMPLEMENT_MC_WATCHDOG.md`` for the full design and decision log.
The decision logic lives in the pure function :func:`tick`, which takes
an explicit ``now`` and never performs I/O or sleeps, so it is testable
without a real clock, socket, or subprocess. :func:`watchdog_loop` is
the thin async wrapper that supplies the real clock and the probe/
restart/poweroff side effects.

:data:`STATE` lives in process memory only, so a reboot or service
restart always starts disarmed, per the design doc.

No lock guards :data:`STATE`. This process runs a single asyncio event
loop, so any stretch of code with no ``await`` in it — every function
below except :func:`watchdog_loop` — runs atomically with respect to
every other coroutine, including the HTTP handlers in ``api.main``. The
only place :data:`STATE` is read on both sides of an ``await`` is
:func:`watchdog_loop`'s blocking probe/restart/poweroff calls; it
re-checks ``arm_generation`` (bumped by every :func:`arm` call) after
each ``await`` so a disarm or re-arm that raced an in-flight I/O call is
discarded instead of applied to a state it no longer reflects.
"""

import asyncio
import enum
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone

from api.hw import power
from api.mc import service, slp

log = logging.getLogger(__name__)

#: Seconds between probes while armed.
PROBE_INTERVAL = 30

#: Seconds after a restart before another failed probe counts as a new
#: failure, giving a modded server time to boot.
STARTUP_GRACE = 300

#: Maximum restart attempts per armed window before giving up.
MAX_RESTARTS = 3

#: Default empty-server threshold (seconds) when none is supplied to :func:`arm`.
DEFAULT_THRESHOLD = 1800


class Action(enum.Enum):
    """Decision returned by :func:`tick` for the caller to apply."""

    NOOP = "noop"
    RESTART_MC = "restart_mc"
    POWEROFF = "poweroff"
    DISARM_EXPIRED = "disarm_expired"
    DISARM_UNRECOVERABLE = "disarm_unrecoverable"


@dataclass
class WatchdogState:
    """In-memory watchdog state (see module docstring).

    ``armed_at``/``deadline``/``empty_since``/``last_restart_at`` are
    monotonic seconds; ``deadline_wall`` is the matching wall-clock
    timestamp, kept only for display in :func:`snapshot`.
    ``arm_generation`` increments on every :func:`arm` call and is how
    :func:`watchdog_loop` detects a disarm/re-arm racing an in-flight
    probe.
    """

    armed: bool = False
    armed_at: float | None = None
    deadline: float | None = None
    deadline_wall: datetime | None = None
    threshold_seconds: int = DEFAULT_THRESHOLD
    empty_since: float | None = None
    restarts_used: int = 0
    last_restart_at: float | None = None
    last_probe: slp.McStatus | None = None
    last_disarm_reason: str | None = None
    arm_generation: int = 0


#: Module-level singleton — the watchdog's only state, in-memory only.
STATE = WatchdogState()


def arm(
    state: WatchdogState,
    now: float,
    active_seconds: int,
    threshold_seconds: int = DEFAULT_THRESHOLD,
) -> None:
    """Arm (or re-arm) the watchdog for an active window.

    Re-arming while already armed replaces the deadline/threshold and
    resets the empty and restart counters.

    Raises:
        ValueError: If ``active_seconds`` or ``threshold_seconds`` is
            not greater than zero.
    """
    if active_seconds <= 0:
        raise ValueError(f"active_seconds must be > 0, got {active_seconds}")
    if threshold_seconds <= 0:
        raise ValueError(f"threshold_seconds must be > 0, got {threshold_seconds}")

    state.armed = True
    state.armed_at = now
    state.arm_generation += 1
    state.deadline = now + active_seconds
    state.deadline_wall = datetime.fromtimestamp(
        time.time() + active_seconds, tz=timezone.utc
    )
    state.threshold_seconds = threshold_seconds
    state.empty_since = None
    state.restarts_used = 0
    state.last_restart_at = None
    state.last_disarm_reason = None


def disarm(state: WatchdogState, reason: str) -> None:
    """Disarm the watchdog and record why.

    Args:
        reason: One of ``"manual"``, ``"expired"``, ``"mc_unrecoverable"``,
            or ``"poweroff_failed"`` (a failed ``systemctl poweroff``,
            recorded instead of leaving the watchdog stuck retrying it
            every tick with no way to surface the failure via ``status``).
    """
    state.armed = False
    state.last_disarm_reason = reason


def tick(state: WatchdogState, now: float, probe: slp.McStatus) -> Action:
    """Decide the watchdog's next action for one probe cycle.

    Pure with respect to I/O: may update ``state.empty_since``/
    ``last_probe`` but never sleeps, probes, restarts, or powers
    anything off — the caller applies the returned :class:`Action`.

    Order: not armed -> :data:`NOOP <Action.NOOP>`. Window expired
    (``now >= deadline``) -> :data:`DISARM_EXPIRED <Action.DISARM_EXPIRED>`,
    even if also empty past the threshold (expiry wins, no poweroff).
    Reachable with players -> reset the empty counter, NOOP. Reachable,
    empty -> count up from the first empty probe; at
    ``threshold_seconds`` -> :data:`POWEROFF <Action.POWEROFF>`.
    Unreachable -> never counts as empty; inside the startup grace since
    the last restart -> NOOP; at :data:`MAX_RESTARTS` ->
    :data:`DISARM_UNRECOVERABLE <Action.DISARM_UNRECOVERABLE>`; otherwise
    -> :data:`RESTART_MC <Action.RESTART_MC>`. ``restarts_used`` is only
    reset by :func:`arm` (capped per armed window, not per outage).
    """
    state.last_probe = probe

    if not state.armed:
        return Action.NOOP
    if state.deadline is not None and now >= state.deadline:
        return Action.DISARM_EXPIRED

    if probe.online:
        if probe.players_online:
            state.empty_since = None
            return Action.NOOP
        if state.empty_since is None:
            state.empty_since = now
        if now - state.empty_since >= state.threshold_seconds:
            return Action.POWEROFF
        return Action.NOOP

    # Unreachable: never counts as empty, never powers off.
    state.empty_since = None
    if (
        state.last_restart_at is not None
        and now - state.last_restart_at < STARTUP_GRACE
    ):
        return Action.NOOP
    if state.restarts_used >= MAX_RESTARTS:
        return Action.DISARM_UNRECOVERABLE
    return Action.RESTART_MC


def snapshot(state: WatchdogState, now: float, probe: slp.McStatus | None = None) -> dict:
    """Build the status payload described in ``IMPLEMENT_MC_WATCHDOG.md``.

    Args:
        state: The watchdog state to read (``empty_since``/``armed``/
            ``deadline``/etc. always come from here).
        now: Monotonic time used for ``remaining_seconds``/``empty_seconds``.
        probe: When given, this is used for the reachability/player-count/
            server-metadata fields instead of ``state.last_probe``. This
            never mutates ``state`` — callers (e.g. a live GET status
            probe) may pass a probe result without it ever being recorded
            as ``state.last_probe``, which only :func:`tick` owns. When
            omitted, behavior is unchanged: ``state.last_probe`` (set by
            the polling loop) is used, which is ``None`` while disarmed.
    """
    effective_probe = probe if probe is not None else state.last_probe
    mc_reachable = bool(effective_probe.online) if effective_probe is not None else False
    players_online = (
        effective_probe.players_online if effective_probe is not None and effective_probe.online else None
    )
    players_max = effective_probe.players_max if mc_reachable and effective_probe is not None else None
    mc_version = effective_probe.version if mc_reachable and effective_probe is not None else None
    mc_motd = effective_probe.motd if mc_reachable and effective_probe is not None else None
    mc_latency_ms = (
        round(effective_probe.latency_ms, 1)
        if mc_reachable and effective_probe is not None and effective_probe.latency_ms is not None
        else None
    )

    empty_seconds: int | None = None
    if mc_reachable and players_online == 0 and state.empty_since is not None:
        empty_seconds = int(max(0.0, now - state.empty_since))

    deadline_iso = None
    remaining_seconds = 0
    if state.armed and state.deadline is not None:
        remaining_seconds = int(max(0.0, state.deadline - now))
        if state.deadline_wall is not None:
            deadline_iso = state.deadline_wall.strftime("%Y-%m-%dT%H:%M:%SZ")

    return {
        "armed": state.armed,
        "deadline": deadline_iso,
        "remaining_seconds": remaining_seconds,
        "threshold_seconds": state.threshold_seconds,
        "empty_seconds": empty_seconds,
        "players_online": players_online,
        "players_max": players_max,
        "mc_version": mc_version,
        "mc_motd": mc_motd,
        "mc_latency_ms": mc_latency_ms,
        "mc_reachable": mc_reachable,
        "restarts_used": state.restarts_used,
        "max_restarts": MAX_RESTARTS,
        "last_disarm_reason": state.last_disarm_reason,
    }


async def watchdog_loop(host: str, port: int, unit: str) -> None:
    """Poll Minecraft every :data:`PROBE_INTERVAL` seconds while armed and
    apply the :func:`tick` decision, until the task is cancelled.

    Each iteration snapshots ``armed``/``arm_generation`` before the
    blocking probe, then re-checks both after it returns (see the module
    docstring) so a disarm/re-arm racing an in-flight probe is discarded
    rather than applied. The same re-check gates the bookkeeping after
    the restart/poweroff calls, which also cross an ``await``. The whole
    iteration runs inside ``try/except Exception`` so one bad probe never
    kills the task; ``CancelledError`` is a ``BaseException`` and still
    propagates for clean shutdown.

    Not started while ``DEBUG`` is on.
    """
    log.info("Minecraft watchdog loop started (host=%s port=%d unit=%s)", host, port, unit)

    while True:
        try:
            generation = STATE.arm_generation
            if STATE.armed:
                probe_result = await slp.probe(host, port)
                now = time.monotonic()

                if STATE.armed and STATE.arm_generation == generation:
                    action = tick(STATE, now, probe_result)

                    if action is Action.RESTART_MC:
                        error = await asyncio.to_thread(service.restart, unit)
                        if STATE.arm_generation == generation:
                            STATE.last_restart_at = time.monotonic()
                            STATE.restarts_used += 1
                            if error:
                                log.warning(
                                    "Watchdog restart of %s failed (attempt %d/%d): %s",
                                    unit, STATE.restarts_used, MAX_RESTARTS, error,
                                )
                            else:
                                log.info(
                                    "Watchdog restarted %s (attempt %d/%d)",
                                    unit, STATE.restarts_used, MAX_RESTARTS,
                                )
                    elif action is Action.POWEROFF:
                        log.warning("Watchdog triggering poweroff: Minecraft empty past threshold")
                        error = await asyncio.to_thread(power.system_poweroff)
                        if error and STATE.arm_generation == generation:
                            log.error("Watchdog poweroff failed: %s", error)
                            disarm(STATE, "poweroff_failed")
                    elif action is Action.DISARM_EXPIRED:
                        disarm(STATE, "expired")
                        log.info("Watchdog window expired; disarmed")
                    elif action is Action.DISARM_UNRECOVERABLE:
                        disarm(STATE, "mc_unrecoverable")
                        log.info(
                            "Watchdog gave up after %d failed restarts; disarmed",
                            STATE.restarts_used,
                        )
        except Exception:
            log.exception("Unexpected error in Minecraft watchdog iteration; retrying next tick")

        await asyncio.sleep(PROBE_INTERVAL)
