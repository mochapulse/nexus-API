# Feature: mc-server-watchdog

Design reference: [`IMPLEMENT_MC_WATCHDOG.md`](../../IMPLEMENT_MC_WATCHDOG.md) (all questions resolved).

## Objective

`nexus-API mc-server active <D> [threshold <T>] | disable | status`. A server-side
watchdog powers off the Nexus host when Minecraft is reachable with 0 players for
T (default 30m), restarts MC when it is unreachable (5m grace, max 3 restarts,
then disarm without poweroff), and disarms when the window D expires. The state
lives in memory only, so the watchdog is always disarmed after boot.

## Constraints

- DEBUG: the server returns templates and never starts the loop; the CLI sends no request and prints an inline placeholder (the CLI deps have no orjson).
- An unreachable MC never counts as empty and never causes a poweroff.
- Tests never call real `systemctl` or sockets; the decision logic is a pure `tick()`.
- Polkit rule scoped to `mc-server-create.service`, verbs `start`/`restart` only.
- Follow repo conventions: lifespan guard+cancel (main.py:34-54), `logging.getLogger(__name__)` with % formatting, pytest `asyncio_mode=auto`, templates `{method}-{name}.jsonc`, docs/api.rst automodule blocks.
- Branch `feat/mc-server-watchdog`; one Conventional Commit per task, no AI attribution; push/PR are the user's decision.

## Workflow Settings

- Route: ODD (SDD declined 2026-09-23: native store resolver only supports openspec; user chose to stay on Engram).
- TDD: **off** (source: sdd-init detection, no project TDD config). Runner: `python -m pytest` (repo root, venv).
- RDD: off (global) → no native review.
- Delivery: `auto-chain` (user: "split commits in PR is ok"). Chain strategy: `feature-branch-chain`.
  - Tracker: `feat/mc-server-watchdog` (draft/no-merge PR to `main`, created only when the user decides to push).
  - PR1 `feat/mc-watchdog-01-foundation` → tracker (T0, T1, T2)
  - PR2 `feat/mc-watchdog-02-logic` → PR1 branch (T3)
  - PR3 `feat/mc-watchdog-03-api` → PR2 branch (T4)
  - PR4 `feat/mc-watchdog-04-cli` → PR3 branch (T5, T6)
- Forecast: ~1200 authored changed lines.

## Tasks

| ID | Task | Route | Slice |
|----|------|-------|-------|
| T0 | Commit design doc + `daemon/mc-server-create.service` | inline (2 mechanical, already-written files) | PR1 |
| T1 | `api/lib/durations.py` + tests | delegated writer | PR1 |
| T2 | `api/mc/slp.py`, `api/mc/service.py` + tests | delegated writer | PR1 |
| T3 | `api/mc/watchdog.py` (state, `tick()`, loop) + tests | delegated writer | PR2 |
| T4 | API endpoints + lifespan, runtime config, `.env.example`, templates, polkit in `install.sh` + tests | delegated writer | PR3 |
| T5 | CLI `mc-server`, dispatch refactor, `nexus_delete` + tests | delegated writer | PR4 |
| T6 | AGENTS.md, README, docs/api.rst | delegated writer | PR4 |

Route trigger evidence: every T1-T6 touches 2+ non-trivial files → writer trigger.

## Checklist

- [x] T0
- [x] T1
- [x] T2
- [x] T3
- [x] T4
- [ ] T5
- [ ] T6

## Acceptance Criteria

- `python -m pytest` passes (existing 48 tests + new ones).
- `sphinx-build -b html docs/ docs/_build/html -W` passes.
- Manual on nexus-lan: arm/status/disable via CLI; poweroff after the threshold with an empty server; restart after MC is killed.

## Progress / Evidence

- Environment: no venv existed; created with local `python3` (3.14.4), `pip install -r requirements.txt` succeeded with no failures (no Python-version fallback needed).
- Baseline (before T1/T2): `python -m pytest -q` -> 48 passed.
- T1 (`92daac2 feat(lib): add duration parser for watchdog windows`, followed by
  `ba96616 style(lib): use Google-style docstrings in durations module` — fixed
  numpy-style docstrings to match `napoleon_google_docstring = True` in
  `docs/conf.py` and the AGENTS.md convention):
  - Files: `api/lib/durations.py`, `api/test/test_durations.py`, `docs/api.rst`.
  - `python -m pytest -q`: 85 passed.
  - `sphinx-build -b html docs/ docs/_build/html -W -q`: exit 0 (stderr only
    shows the pre-existing `libamd_smi.so` runtime warning from importing
    `api.hw.telemetry` during autodoc, not a Sphinx warning).
- T2 (`ec3bfdb feat(mc): add server list ping probe and systemd unit control`):
  - Files: `api/mc/__init__.py`, `api/mc/slp.py`, `api/mc/service.py`,
    `api/test/test_mc_slp.py`, `api/test/test_mc_service.py`, `docs/api.rst`.
  - `python -m pytest -q`: 119 passed.
  - `sphinx-build -b html docs/ docs/_build/html -W -q`: exit 0 after removing
    the napoleon `Attributes:` docstring section on `McStatus` (a dataclass's
    fields plus a napoleon `Attributes:` block both register as
    `py:attribute` objects with the same qualified name, which `-W` turns
    into a fatal "duplicate object description" error — rewrote the
    docstring as prose instead).
  - `git diff --stat` for the T1+T2 slice: 8 files changed, ~857 insertions
    (durations 196, mc-style fixup 9/-26, mc module+tests 661, docs/api.rst
    +15 across both).

- T3 (`5716e0c feat(mc): add watchdog state machine and polling loop`) on
  `feat/mc-watchdog-02-logic` (parent `feat/mc-watchdog-01-foundation`):
  - Files: `api/mc/watchdog.py`, `api/test/test_mc_watchdog.py`, `docs/api.rst`.
  - `python -m pytest -q`: 149 passed (119 before this task, 30 new for
    `test_mc_watchdog.py`: `tick()` boundaries, `arm`/`disarm`/`snapshot`,
    and the async loop with `slp.probe`/`service.restart`/
    `power.system_poweroff`/`asyncio.sleep`/`time.monotonic` all patched —
    no real systemctl, socket, or sleep).
  - `sphinx-build -b html docs/ docs/_build/html -W -q`: exit 0 (stderr
    only shows the pre-existing `libamd_smi.so` runtime warning from
    importing `api.hw.telemetry` during autodoc, same as T1/T2, not a
    Sphinx warning).
  - `git diff --stat` for the T3 commit: 3 files changed, 714 insertions
    (`api/mc/watchdog.py` 351, `api/test/test_mc_watchdog.py` 355,
    `docs/api.rst` +6).
  - Deviation: `watchdog_loop()` disarms with an extra
    `last_disarm_reason` value, `"poweroff_failed"`, not listed in
    `IMPLEMENT_MC_WATCHDOG.md`'s status payload doc, for the case where
    `systemctl poweroff` itself reports an error (e.g. missing polkit
    rule). Without it the watchdog would stay armed and re-attempt (and
    re-fail) the poweroff every 30s tick forever with no way to
    surface the failure via `status`. Documented in the module
    docstring; `IMPLEMENT_MC_WATCHDOG.md`'s payload example should be
    updated when T4 wires the endpoint (tracked here, not fixed
    retroactively in the design doc since "all decisions are final").
  - Design choice recorded: `restarts_used` is capped per armed window
    (only reset by `arm()`), not per outage — matches
    "`MAX_RESTARTS` per armed window" in the design doc. Confirmed by
    `test_restarts_used_not_reset_on_recovery`.
  - Design choice recorded: when both window expiry and the poweroff
    threshold are due on the same tick, expiry wins (`DISARM_EXPIRED`,
    no poweroff), per "ARMED --(now >= deadline)--> DISARMED (window
    expired, no poweroff)" in the design doc's state machine — this is
    evaluated before the empty/poweroff branch in `tick()`. Confirmed
    by `test_expiry_beats_poweroff_when_both_due`.

- Step A fix (`a6a6275 fix(mc): keep watchdog lock short and survive
  iteration errors`) on `feat/mc-watchdog-02-logic`, applied before T4:
  `watchdog_loop()` no longer holds `STATE_LOCK` across the blocking
  SLP probe / `systemctl restart` / `systemctl poweroff` calls — it
  snapshots `armed`/`arm_generation` under the lock, releases it for
  I/O, then re-acquires and re-checks `arm_generation` (a new
  `WatchdogState` field, bumped by every `arm()` call) so a disarm or
  re-arm that races an in-flight probe never applies a stale decision.
  Each iteration also runs inside `try/except Exception` so an
  unexpected error is logged and retried next tick instead of killing
  the polling task (`asyncio.CancelledError` is a `BaseException`, not
  an `Exception`, and still propagates for clean shutdown — verified).
  - Files: `api/mc/watchdog.py`, `api/test/test_mc_watchdog.py`.
  - `python -m pytest -q`: 151 passed (149 before, 2 new:
    probe-error-continues, disarm-during-in-flight-probe).
  - `sphinx-build -b html docs/ docs/_build/html -W -q`: exit 0 (only
    the pre-existing `libamd_smi.so` runtime warning).
  - `git diff --stat`: 2 files changed, 148 insertions(+), 33
    deletions(-).

- T4 (`ec605c2 feat(api): expose minecraft watchdog endpoints and
  lifespan task`) on `feat/mc-watchdog-03-api` (parent
  `feat/mc-watchdog-02-logic`):
  - Files: `api/config/runtime.py`, `api/.env.example`, `api/main.py`,
    `cmd/install.sh`, `api/test/test_mc_endpoints.py`,
    `templates/get-mc-server-watchdog.jsonc`,
    `templates/post-mc-server-watchdog.jsonc`,
    `templates/delete-mc-server-watchdog.jsonc`,
    `IMPLEMENT_MC_WATCHDOG.md`.
  - `MINECRAFT_PORT` (default `25565`) and `MINECRAFT_SERVICE` (default
    `mc-server-create`) added to `runtime.py`; `.env.example` gained
    the two new vars and lost its duplicated `ESP_IP/ESP_PORT/ESP_API_KEY`
    block.
  - `POST/DELETE/GET /api/v1/mc-server/watchdog` added on
    `api_v1_router` (X-API-Key already enforced); production paths
    call `mc_watchdog.arm/disarm/snapshot` under `STATE_LOCK` via
    module-qualified access (`mc_watchdog.STATE`, not a rebound local)
    so tests can reset the singleton per test. DEBUG returns the new
    JSONC templates and never touches `STATE`; POST still validates its
    body (422 on invalid `active_seconds`/`threshold_seconds`) even in
    DEBUG.
  - `lifespan()` now tracks a list of tasks (DuckDNS + the watchdog
    loop) and starts `watchdog_loop("localhost", MINECRAFT_PORT,
    MINECRAFT_SERVICE)` whenever `DEBUG` is off (the loop itself only
    probes/acts once armed via the endpoints, and always starts
    disarmed on boot per the in-memory-state design); all started
    tasks are cancelled the same way on shutdown. `watchdog_loop` is
    imported by name into `api.main` (`from api.mc.watchdog import
    watchdog_loop`), matching the `duckdns_loop` pattern, so tests can
    patch `main.watchdog_loop` directly.
  - `cmd/install.sh`: added a second, separately-scoped polkit rule
    file (`/etc/polkit-1/rules.d/20-nexus-mc-server.rules`) granting
    `org.freedesktop.systemd1.manage-units` only for
    `action.lookup("unit") == "${MC_UNIT}"` (default
    `mc-server-create.service`, overridable via the `MC_UNIT` env var)
    and verb `start`/`restart`, scoped to `${SERVICE_USER}`; `-dev`
    still skips both polkit rule files.
  - `IMPLEMENT_MC_WATCHDOG.md`: status payload's `last_disarm_reason`
    comment now lists `"poweroff_failed"`; Decisions Log gained one
    line recording that reason (not in the original design) and why it
    exists (surface a failed poweroff via `status` instead of
    retrying/re-failing every tick).
  - `python -m pytest -q`: 172 passed (151 before this task, 21 new in
    `api/test/test_mc_endpoints.py`: auth-required for all three verbs,
    DEBUG stub-equals-template with `STATE` untouched, DEBUG still
    validating the POST body, production arm/re-arm/disarm/idempotent-
    disarm behavior, 422 matrix for invalid bodies, and two lifespan
    tests patching `main.watchdog_loop` with an `AsyncMock` to assert
    it is skipped in DEBUG and started with the right args in
    production — no real socket probe or `systemctl` call in the
    suite).
  - `sphinx-build -b html docs/ docs/_build/html -W -q`: exit 0 (only
    the pre-existing `libamd_smi.so` runtime warning; no new module was
    added, so `docs/api.rst` is unchanged).
  - `bash -n cmd/install.sh`: syntax OK.
  - `git diff --stat` for the T4 commit: 9 files changed, 401
    insertions(+), 11 deletions(-).
  - Deviation: none beyond the `poweroff_failed` reason already
    recorded under T3 and now reflected in the design doc.

## Next Step

T4 done on `feat/mc-watchdog-03-api`. Next: T5 (CLI `mc-server`
subcommand, dispatch refactor, `nexus_delete` + tests) on
`feat/mc-watchdog-04-cli`.
