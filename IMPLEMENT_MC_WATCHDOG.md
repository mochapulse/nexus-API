# Minecraft Server Watchdog — Implementation Idea

Status: **Implemented** on branch chain feat/mc-watchdog-01..04.

## Goal

Power off the Nexus host when the Minecraft server has had **no players
for a threshold duration** (default 30m). If Minecraft is unreachable,
**try to restart it** first. The watchdog is armed from the CLI for a
limited **active window** (e.g. 5h) and is **always disabled after the
host boots**.

```
nexus-API mc-server active 5h threshold 10m   # arm for 5h, poweroff after 10m empty
nexus-API mc-server active 1h-30m              # arm for 1h30m, default threshold 30m
nexus-API mc-server disable                    # disarm now
nexus-API mc-server status                     # armed?, time left, empty counter, players
```

## Key Architecture Decision: the watchdog runs on the server

The CLI is an HTTP client on a workstation. If the watchdog loop lived in
the CLI, the terminal would have to stay open for 5h, and a laptop
sleeping or losing Wi-Fi would silently kill it.

So we split it the same way as DuckDNS:

| Piece | Runs on | Role |
|-------|---------|------|
| Watchdog loop | Nexus host (API process, asyncio task) | Probe MC, restart MC, count empty time, poweroff |
| Watchdog state | Nexus host, **in memory only** | Armed flag, deadline, threshold, empty-since, restart count |
| `/api/v1/mc-server/*` endpoints | Nexus host | Arm / disarm / status |
| `nexus-API mc-server ...` | Workstation CLI | Parse durations, call endpoints, print result |

**"Always disabled on boot" comes for free**: the state lives only in
process memory, so a reboot or service restart starts from the disarmed
state. Nothing is persisted.

## Production Context (nexus-lan)

- MC runs as the systemd unit `mc-server-create.service`, user `nexus-lan`.
- `Type=forking`: `ExecStart` launches `./start.sh` in a detached tmux session `mc-server-create`.
- `ExecStop` sends `stop` to the tmux console.
- `Restart=on-failure`, `RestartSec=5`, `TimeoutStopSec=30`.
- `nexus-api.service` also runs as `nexus-lan` (installed by `cmd/install.sh`).

## Behavior

State machine:

```
DISARMED --(active D threshold T)--> ARMED
ARMED    --(disable)---------------> DISARMED
ARMED    --(now >= deadline)-------> DISARMED   (window expired, no poweroff)
ARMED    --(empty for >= T)--------> POWEROFF   (systemctl poweroff)
ARMED    --(3 restarts failed)-----> DISARMED   (mc_unrecoverable, no poweroff)
```

Loop while ARMED (every `PROBE_INTERVAL` = 30s):

1. Probe MC with `mcstatus` (Java status query) on `localhost:MINECRAFT_PORT`.
2. **Reachable, players > 0** → reset `empty_since = None`.
3. **Reachable, players == 0** → set `empty_since` if unset.
4. **Unreachable** → reset `empty_since = None` (an unreachable server is
   never treated as empty), then run the **recovery policy** below.
5. `empty_since` set and `now - empty_since >= threshold` → poweroff.
6. `now >= deadline` → disarm and log it.

Re-arming while armed replaces the deadline and threshold, and resets the
empty counter and the restart count.

### Recovery policy (MC unreachable)

A modded server (Create Chronicles) takes minutes to boot, so "not
answering the ping" right after a start is normal. That is why there is
a **startup grace** period.

```
unreachable?
 ├─ inside startup grace (since last restart)  → wait, do nothing
 ├─ restarts_used >= MAX_RESTARTS
 │    and grace expired                        → give up: DISARM (no poweroff)
 └─ otherwise
     ├─ systemctl is-active mc-server-create
     │    failed / inactive  → systemctl restart   (unit crashed / stopped)
     │    active             → systemctl restart   (process hung / not listening)
     └─ restarts_used += 1, grace starts now
```

| Setting | Proposed default | Why |
|---------|------------------|-----|
| `STARTUP_GRACE` | 5m | Modded server boot time |
| `MAX_RESTARTS` | 3 per armed window | Avoid an infinite crash-restart loop |

**An unreachable MC never causes a poweroff.** If MC is still unreachable
after the 3rd restart's grace, the watchdog **disarms itself** and records
why (`last_disarm_reason: "mc_unrecoverable"`), so `status` tells you to
fix it manually. After a manual fix, re-arm with `mc-server active ...`.

If MC comes back within a grace window, normal behavior resumes: the empty
counter starts fresh from the first reachable, empty probe.

Worst case timeline: 3 restarts × 5m grace = the watchdog gives up about
15m after MC first goes down.

Only a **reachable MC with 0 players for the full threshold** triggers a poweroff.

The **mcstatus probe is the source of truth**, not `systemctl is-active`
(see the unit file hazards below: systemd can report `active` while MC is dead).

### Poweroff

Reuses `api.hw.power.system_poweroff()`. Systemd then stops
`mc-server-create`, whose `ExecStop` sends `stop` (world save).

## DEBUG Mode — placeholders everywhere, no real requests

Same rule as the existing power endpoints:

| Side | `DEBUG=true` behavior |
|------|-----------------------|
| CLI | Parses and validates the command, prints a placeholder response loaded from a template. **No HTTP request is sent.** |
| Server endpoints | Return template stubs (`load_template`). |
| Server loop | Never started. No status probe, no `systemctl restart`, no poweroff. |

## Duration Format

Accepted: `5h`, `10h`, `1h`, `30m`, `1m`, `1h-30m`, `1h30m`.

```python
_DURATION_RE = re.compile(r"^(?:(\d+)h)?-?(?:(\d+)m)?$")
```

- At least one of the `h`/`m` parts is required, and the total must be > 0.
- Parsed in the CLI into seconds and sent as integers. The server
  validates again (never trust the client).

## API (on `api_v1_router`, X-API-Key protected)

| Method | Path | Body | Response |
|--------|------|------|----------|
| POST | `/api/v1/mc-server/watchdog` | `{"active_seconds": 18000, "threshold_seconds": 1800}` | status payload |
| DELETE | `/api/v1/mc-server/watchdog` | — | status payload |
| GET | `/api/v1/mc-server/watchdog` | — | status payload |

Status payload:

```jsonc
{
  "armed": true,
  "deadline": "2026-09-23T23:00:00Z",
  "remaining_seconds": 17820,
  "threshold_seconds": 1800,
  "empty_seconds": 120,        // null when players are online or MC is unreachable
  "players_online": 0,         // null when MC is unreachable
  "mc_reachable": true,
  "restarts_used": 0,
  "max_restarts": 3,
  "last_disarm_reason": null   // "manual" | "expired" | "mc_unrecoverable" | "poweroff_failed"
}
```

## Configuration

| Variable | Default | Used by |
|----------|---------|---------|
| `MINECRAFT_PORT` | `25565` | Server (mcstatus probe on localhost) |
| `MINECRAFT_SERVICE` | `mc-server-create` | Server (`systemctl restart <unit>`) |

## Permissions (polkit)

`systemctl restart mc-server-create` from the `nexus-api` process (user
`nexus-lan`, no TTY) needs polkit authorization. Extend the rule in
`cmd/install.sh` **scoped to this one unit**:

```js
if (action.id == "org.freedesktop.systemd1.manage-units" &&
    action.lookup("unit") == "mc-server-create.service" &&
    (action.lookup("verb") == "restart" || action.lookup("verb") == "start") &&
    subject.user == "${SERVICE_USER}") {
    return polkit.Result.YES;
}
```

Never grant `manage-units` for all units.

## Unit File Hazards (Q7 — fixed in production 2026-09-23, reference copy in `daemon/mc-server-create.service`)

1. **Shared tmux server** — `tmux new-session` uses the user's default
   socket. If `nexus-lan` has other tmux sessions (SSH work), the tmux
   server is shared, and systemd can keep reporting `active` after MC dies.
   Fix: dedicated socket, `tmux -L mc-server-create ...` in both
   `ExecStart` and `ExecStop`.
2. **`Restart=on-failure` rarely fires** — when Java exits, tmux exits
   cleanly (code 0), so systemd does not consider it a failure. The
   watchdog's recovery covers this gap while armed.
3. **`ExecStop` doesn't wait** — `send-keys "stop"` returns immediately,
   and systemd then SIGTERMs the cgroup. The world save may be cut short
   on restart/poweroff. Fix: an `ExecStop` script that sends `stop` and
   waits for the tmux session to end (bounded by `TimeoutStopSec`).

## Files

| File | Change |
|------|--------|
| `api/config/runtime.py` | `MINECRAFT_PORT`, `MINECRAFT_SERVICE` |
| `api/.env.example` | New vars (also dedupe the `ESP_*` keys) |
| `api/mc/slp.py` | Minecraft status probe (`mcstatus`), `probe() -> McStatus` |
| `api/mc/service.py` | `is_active()`, `restart()` wrappers over `systemctl` (with timeout) |
| `api/mc/watchdog.py` | State dataclass + pure `tick()` + async loop + arm/disarm/status |
| `api/lib/durations.py` | `parse_duration("1h-30m") -> 5400` (shared by CLI and API) |
| `api/main.py` | Endpoints; watchdog task in `lifespan()` (skipped in DEBUG) |
| `api/cli/__init__.py` | `mc-server` subcommand; dispatch refactor (all handlers get `args`) |
| `api/cli/commands.py` | `cmd_mc_server(args)`, DEBUG → placeholder |
| `templates/*-mc-server-watchdog.jsonc` | Placeholder payloads (GET/POST/DELETE) |
| `cmd/install.sh` | Scoped polkit rule for the MC unit |
| `api/test/test_durations.py` | Valid and invalid formats |
| `api/test/test_mc_watchdog.py` | `tick()` with fake clock: empty/players/unreachable/grace/restart cap/expiry |
| AGENTS.md, README | Docs |

The decision logic is a **pure function**
`tick(state, now, probe_result, unit_state) -> Action` (`NOOP`,
`RESTART_MC`, `POWEROFF`, `DISARM`), so tests never sleep, never restart
MC, and never power anything off.

## Open Questions

_None — all resolved._

## Decisions Log

- **Scope**: poweroff when MC is empty for the threshold, plus a restart attempt when MC is unreachable. No WOL/alerts.
- **Activation**: armed via CLI with an active window + threshold; disarmable.
- **Boot state**: always disarmed after boot (in-memory state, by design).
- **Location**: the loop runs server-side; the CLI is only a remote control.
- **Q1 Unreachable**: restart MC via systemd (with grace + cap). Unreachable never counts as empty and never causes a poweroff.
- **Q2 Window expiry**: disarm only, no poweroff.
- **Q3 Default threshold**: 30m.
- **Q4 Probe interval**: 30s. Poweroff is at most 30s late, never early; the cost is negligible.
- **Q6 Grace and cap**: 5m startup grace, max 3 restarts. After the 3rd failed restart, disarm (`mc_unrecoverable`), never poweroff.
- **Q7 Unit file**: fixed manually on nexus-lan (dedicated tmux socket, ExecStop waits for the save, TimeoutStopSec=120, Restart=on-failure kept). Verified: main PID = `tmux -L mc-server-create` server, Java in the unit cgroup.
- **Q5 DEBUG**: placeholders everywhere; the CLI sends no request, and the server loop never runs.
- **`last_disarm_reason: "poweroff_failed"`** (added in T3/T4, not in the original design): when `systemctl poweroff` itself reports an error (e.g. missing polkit rule), the watchdog disarms and records this reason instead of leaving itself armed to silently retry (and re-fail) the poweroff every 30s tick with no way to surface the failure via `status`.
- **Probe uses mcstatus (user request) instead of hand-written SLP**: `api/mc/slp.py` now wraps `mcstatus.JavaServer.async_status()` instead of implementing the Java Edition Server List Ping wire protocol by hand. Same `McStatus`/`probe()` contract; `probe()` is now a coroutine (`async def`), so `watchdog_loop()` awaits it directly instead of via `asyncio.to_thread`.
