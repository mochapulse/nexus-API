"""Minecraft server watchdog: state machine and polling loop.

Powers off the Nexus host when the Minecraft server has had no players
for a configurable threshold, and restarts Minecraft when it stops
answering the status probe (:mod:`api.mc.slp`). See
``IMPLEMENT_MC_WATCHDOG.md`` for the full design and decision log.

The decision logic lives in the pure function :func:`tick`, which takes
an explicit ``now`` (monotonic seconds) and never performs I/O or
sleeps, so it can be tested without a real clock, socket, or subprocess.
:func:`watchdog_loop` is the thin async wrapper that supplies the real
clock and probe/restart/poweroff side effects.

State (:class:`WatchdogState`) lives in process memory only, via the
module-level :data:`STATE` singleton — by design, per
``IMPLEMENT_MC_WATCHDOG.md``, so a reboot or service restart always
starts disarmed. :data:`STATE_LOCK` serializes mutation between the
polling loop and the HTTP endpoints (T4); the process runs a single
event loop, so a plain :class:`asyncio.Lock` is enough — no
cross-process or multi-worker coordination is needed.

:func:`watchdog_loop` never holds :data:`STATE_LOCK` across blocking
I/O (the status probe, ``systemctl restart``, ``systemctl poweroff``):
each iteration reads ``armed``/``arm_generation`` under the lock,
releases it for the I/O, then re-acquires it to compute and apply the
:func:`tick` decision. Because an HTTP endpoint can disarm or re-arm
the watchdog while a probe is in flight, every re-acquisition re-checks
``STATE.armed`` and ``STATE.arm_generation`` (bumped by every
:func:`arm` call) before touching state, so a stale in-flight probe
never applies an action against a state it no longer reflects. Each
iteration also runs inside a ``try/except Exception`` so one bad probe
or a transient error never kills the polling task; ``CancelledError``
is a ``BaseException`` in Python 3.8+, so it is never caught there and
still propagates for clean shutdown.

Deviation from the design doc: :func:`watchdog_loop` disarms with the
extra reason ``"poweroff_failed"`` (not listed among ``last_disarm_reason``
in ``IMPLEMENT_MC_WATCHDOG.md``) when ``systemctl poweroff`` itself
reports an error. Without this, a failed poweroff would leave the
watchdog silently armed and stuck at ``POWEROFF`` every subsequent
tick. This is recorded as a deviation in
``odd/tasks/mc-server-watchdog.md``.
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

#: Seconds to wait after a restart before probing again counts as a new
#: failure, giving a modded server time to boot.
STARTUP_GRACE = 300

#: Maximum restart attempts per armed window before giving up.
MAX_RESTARTS = 3

#: Default empty-server threshold (seconds) when none is supplied to :func:`arm`.
DEFAULT_THRESHOLD = 1800


class Action(enum.Enum):
    """Decision returned by :func:`tick` for the caller to apply."""

    #: Nothing to do this tick.
    NOOP = "noop"
    #: Restart the Minecraft systemd unit.
    RESTART_MC = "restart_mc"
    #: Power off the host.
    POWEROFF = "poweroff"
    #: Disarm because the active window expired.
    DISARM_EXPIRED = "disarm_expired"
    #: Disarm because Minecraft would not come back after MAX_RESTARTS.
    DISARM_UNRECOVERABLE = "disarm_unrecoverable"


@dataclass
class WatchdogState:
    """In-memory watchdog state.

    ``armed`` is the top-level on/off flag. ``armed_at`` and ``deadline``
    are monotonic seconds (``time.monotonic()``) marking when the
    current window was armed and when it expires; ``deadline_wall`` is
    the matching wall-clock (UTC) timestamp used only for display in
    :func:`snapshot`, since monotonic time has no meaningful calendar
    mapping. ``threshold_seconds`` is the empty-server duration that
    triggers a poweroff. ``empty_since`` is the monotonic time the
    server was first observed reachable with zero players since the
    counter was last reset, or ``None`` while not counting.
    ``restarts_used`` counts restart attempts in the current armed
    window (never reset on recovery, only by :func:`arm`).
    ``last_restart_at`` is the monotonic time of the most recent restart
    attempt, used to compute the startup grace period. ``last_probe`` is
    the most recent :class:`~api.mc.slp.McStatus`, or ``None`` before
    the first probe. ``last_disarm_reason`` records why the watchdog
    last left the armed state: ``"manual"``, ``"expired"``,
    ``"mc_unrecoverable"``, ``"poweroff_failed"``, or ``None`` if it has
    never been disarmed. ``arm_generation`` increments on every
    :func:`arm` call; :func:`watchdog_loop` captures it before releasing
    :data:`STATE_LOCK` for a blocking probe, and compares it again on
    re-acquisition to detect a disarm or re-arm that happened while the
    probe was in flight, so a stale decision is never applied.
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

#: Serializes mutation of :data:`STATE` between the polling loop and the
#: HTTP endpoints (T4). A single event loop runs this process, so a plain
#: asyncio.Lock is sufficient; no cross-process coordination is needed.
STATE_LOCK = asyncio.Lock()


def arm(
    state: WatchdogState,
    now: float,
    active_seconds: int,
    threshold_seconds: int = DEFAULT_THRESHOLD,
) -> None:
    """Arm (or re-arm) the watchdog for an active window.

    Re-arming while already armed replaces the deadline and threshold
    and resets the empty counter and restart count, per
    ``IMPLEMENT_MC_WATCHDOG.md``.

    Args:
        state: The watchdog state to mutate.
        now: The current monotonic time (seconds), e.g. ``time.monotonic()``.
        active_seconds: How long the window stays armed, in seconds.
            Must be greater than zero.
        threshold_seconds: How long the server must be empty before a
            poweroff. Must be greater than zero.

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
        state: The watchdog state to mutate.
        reason: One of ``"manual"``, ``"expired"``, ``"mc_unrecoverable"``,
            or ``"poweroff_failed"`` (see the module docstring for the
            latter's rationale).
    """
    state.armed = False
    state.last_disarm_reason = reason


def tick(state: WatchdogState, now: float, probe: slp.McStatus) -> Action:
    """Decide the watchdog's next action for one probe cycle.

    Pure with respect to I/O: it may mutate ``state``'s counters
    (``empty_since``, ``last_probe``) but never sleeps, probes, restarts,
    or powers anything off — the caller applies the returned
    :class:`Action`. Evaluation order (exactly per
    ``IMPLEMENT_MC_WATCHDOG.md``):

    1. Not armed -> :data:`Action.NOOP`.
    2. Window expired (``now >= deadline``) -> :data:`Action.DISARM_EXPIRED`,
       even if the server is also empty past the threshold: expiry wins,
       no poweroff.
    3. Reachable with players -> reset the empty counter, :data:`Action.NOOP`.
    4. Reachable, empty -> start (or continue) the empty counter; once it
       reaches ``threshold_seconds`` -> :data:`Action.POWEROFF`, otherwise
       :data:`Action.NOOP`.
    5. Unreachable -> reset the empty counter (unreachable never counts as
       empty and never triggers a poweroff), then apply the recovery
       policy: inside the startup grace since the last restart -> wait
       (:data:`Action.NOOP`); ``restarts_used`` already at
       :data:`MAX_RESTARTS` -> :data:`Action.DISARM_UNRECOVERABLE`;
       otherwise -> :data:`Action.RESTART_MC`.

    ``restarts_used`` is capped per armed window, not per outage: it is
    only reset by :func:`arm`, never when Minecraft comes back online.
    If Minecraft recovers after some restarts, the empty counter still
    starts fresh from the first reachable, empty probe, since step 3/4
    above always (re)synchronizes ``empty_since`` from the live probe.

    Args:
        state: The watchdog state; ``last_probe`` is updated as a side
            effect so callers/snapshots can report the latest probe.
        now: The current monotonic time (seconds).
        probe: The result of the latest status probe.

    Returns:
        The :class:`Action` the caller should apply.
    """
    state.last_probe = probe

    if not state.armed:
        return Action.NOOP

    if state.deadline is not None and now >= state.deadline:
        return Action.DISARM_EXPIRED

    if probe.online:
        if probe.players_online is not None and probe.players_online > 0:
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


def snapshot(state: WatchdogState, now: float) -> dict:
    """Build the status payload described in ``IMPLEMENT_MC_WATCHDOG.md``.

    Args:
        state: The watchdog state to read.
        now: The current monotonic time (seconds), used to compute
            ``remaining_seconds`` and ``empty_seconds``.

    Returns:
        A dict with keys ``armed``, ``deadline`` (ISO-8601 UTC with a
        trailing ``Z``, or ``None``), ``remaining_seconds``,
        ``threshold_seconds``, ``empty_seconds`` (``None`` when players
        are online, MC is unreachable, or the counter is not running),
        ``players_online`` (``None`` when unreachable), ``mc_reachable``,
        ``restarts_used``, ``max_restarts``, and ``last_disarm_reason``.
    """
    probe = state.last_probe
    mc_reachable = bool(probe.online) if probe is not None else False
    players_online = probe.players_online if probe is not None and probe.online else None

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
        "mc_reachable": mc_reachable,
        "restarts_used": state.restarts_used,
        "max_restarts": MAX_RESTARTS,
        "last_disarm_reason": state.last_disarm_reason,
    }


async def watchdog_loop(host: str, port: int, unit: str) -> None:
    """Run the watchdog polling loop until the task is cancelled.

    Every :data:`PROBE_INTERVAL` seconds, while :data:`STATE` is armed:
    probes Minecraft via :func:`api.mc.slp.probe` (a native coroutine),
    computes the :class:`Action` via :func:`tick`, and applies it:

    - :data:`Action.RESTART_MC`: calls :func:`api.mc.service.restart`
      off the event loop, and records the attempt (``last_restart_at``,
      ``restarts_used``) regardless of whether the restart itself
      reported an error — the error is logged at ``WARNING`` and the
      startup-grace/retry-cap bookkeeping still needs to progress so the
      loop cannot restart-spin without ever hitting :data:`MAX_RESTARTS`.
    - :data:`Action.POWEROFF`: calls :func:`api.hw.power.system_poweroff`
      off the event loop. On success the host is going down and no
      further bookkeeping matters. On failure (e.g. no polkit rule),
      logs at ``ERROR`` and disarms with reason ``"poweroff_failed"``
      (see the module docstring) rather than leaving the watchdog stuck
      retrying an unwinnable poweroff every tick.
    - :data:`Action.DISARM_EXPIRED` / :data:`Action.DISARM_UNRECOVERABLE`:
      disarms with the matching reason and logs at ``INFO``.

    :data:`STATE_LOCK` is never held across the blocking probe/restart/
    poweroff calls (see the module docstring): each iteration snapshots
    ``armed``/``arm_generation`` under the lock, releases it for the I/O,
    then re-acquires it to compute and apply the decision — re-checking
    ``arm_generation`` so a disarm or re-arm that raced the in-flight
    probe discards the now-stale action instead of applying it.

    The whole iteration body runs inside a ``try/except Exception`` so
    an unexpected error (a probe exception, and so on) is logged and the
    loop retries on the next tick rather than dying;
    :class:`asyncio.CancelledError` is a ``BaseException``, not an
    ``Exception``, so it is never swallowed here and still propagates
    for clean task cancellation on shutdown.

    Not started while ``DEBUG`` is on. Wired into the FastAPI lifespan
    in T4.

    Args:
        host: Minecraft server host to probe (``localhost`` in production).
        port: Minecraft server port to probe.
        unit: The systemd unit name to restart on recovery.
    """
    log.info("Minecraft watchdog loop started (host=%s port=%d unit=%s)", host, port, unit)

    while True:
        try:
            async with STATE_LOCK:
                armed = STATE.armed
                generation = STATE.arm_generation

            if armed:
                probe_result = await slp.probe(host, port)
                now = time.monotonic()

                async with STATE_LOCK:
                    is_current = STATE.armed and STATE.arm_generation == generation
                    action = tick(STATE, now, probe_result) if is_current else None

                if action is Action.RESTART_MC:
                    error = await asyncio.to_thread(service.restart, unit)
                    async with STATE_LOCK:
                        if STATE.arm_generation == generation:
                            STATE.last_restart_at = time.monotonic()
                            STATE.restarts_used += 1
                            restarts_used = STATE.restarts_used
                        else:
                            restarts_used = None
                    if restarts_used is not None:
                        if error:
                            log.warning(
                                "Watchdog restart of %s failed (attempt %d/%d): %s",
                                unit,
                                restarts_used,
                                MAX_RESTARTS,
                                error,
                            )
                        else:
                            log.info(
                                "Watchdog restarted %s (attempt %d/%d)",
                                unit,
                                restarts_used,
                                MAX_RESTARTS,
                            )
                elif action is Action.POWEROFF:
                    log.warning("Watchdog triggering poweroff: Minecraft empty past threshold")
                    error = await asyncio.to_thread(power.system_poweroff)
                    if error:
                        log.error("Watchdog poweroff failed: %s", error)
                        async with STATE_LOCK:
                            if STATE.arm_generation == generation:
                                disarm(STATE, "poweroff_failed")
                elif action is Action.DISARM_EXPIRED:
                    async with STATE_LOCK:
                        if STATE.arm_generation == generation:
                            disarm(STATE, "expired")
                    log.info("Watchdog window expired; disarmed")
                elif action is Action.DISARM_UNRECOVERABLE:
                    async with STATE_LOCK:
                        if STATE.arm_generation == generation:
                            disarm(STATE, "mc_unrecoverable")
                            restarts_used = STATE.restarts_used
                        else:
                            restarts_used = None
                    if restarts_used is not None:
                        log.info(
                            "Watchdog gave up after %d failed restarts; disarmed",
                            restarts_used,
                        )
        except Exception:
            log.exception("Unexpected error in Minecraft watchdog iteration; retrying next tick")

        await asyncio.sleep(PROBE_INTERVAL)
