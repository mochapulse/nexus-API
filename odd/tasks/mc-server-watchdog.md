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
- [x] T5
- [x] T6

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

- T5 (`abd2fe5 feat(cli): add mc-server command to arm, disarm and inspect
  the watchdog`) on `feat/mc-watchdog-04-cli` (parent
  `feat/mc-watchdog-03-api`):
  - Files: `api/cli/__init__.py`, `api/cli/commands.py`,
    `api/cli/http_client.py`, `api/test/test_cli_mc.py`.
  - `mc-server` subparser added with nested `active`/`disable`/`status`
    subcommands; `active` takes a positional `duration` plus a
    `nargs="*"` `extra` argument validated by a custom
    `_ThresholdAction` (empty, or exactly `["threshold", "<duration>"]`,
    else `parser.error(...)` — matches argparse's own exit-2 error
    style). `mc-server` with no subcommand prints its own help and
    exits 1 (via a `mc_parser` default stashed on the namespace with
    `set_defaults`).
  - Dispatch refactor: `cmd_config`, `cmd_wol`, `cmd_health`,
    `cmd_poweroff`, `cmd_sleep` all now take `args: argparse.Namespace`
    (documented as unused where applicable); `main()`'s handler dict
    calls every handler as `handler(args)` uniformly — the
    telemetry-only special case is gone.
  - `http_client.nexus_post` gained an optional `json: dict | None`
    parameter (backward compatible with existing no-body callers);
    added `nexus_delete(path)` mirroring `nexus_get`/`nexus_post`.
  - `cmd_mc_server(args)`: validates the duration(s) with
    `api.lib.durations.parse_duration` first (invalid -> `Error: ...`
    to stderr, exit 1); in `DEBUG` sends no request and prints a
    placeholder built inline in Python (`_debug_watchdog_payload`,
    mirroring the three `templates/*-mc-server-watchdog.jsonc` shapes)
    through the same `_print_watchdog_status` formatter used for real
    responses; in production calls `nexus_post`/`nexus_delete`/
    `nexus_get` with the omitted-when-absent `threshold_seconds` body,
    and a non-2xx response is rendered by `_print_watchdog_error`
    (handles FastAPI's list-shaped 422 `detail` readably) then exits 1.
    `status` exits 0 on any successful request, armed or not.
  - Verified no CLI-path module imports `orjson`/`fastapi`/`pydantic`/
    `api.lib.templates` (`rg` over `api/cli/*.py api/lib/durations.py`
    — no matches); `api.lib.durations` is stdlib-only as required.
  - `python -m pytest -q`: 194 passed (172 before this task, 22 new in
    `api/test/test_cli_mc.py`: parser accepted/rejected forms, uniform
    `handler(args)` dispatch, DEBUG never calling
    `nexus_post`/`nexus_get`/`nexus_delete` (patched with `MagicMock`),
    production request shape for `active`/`disable`/`status`, invalid
    duration and non-2xx exiting 1, network error exiting 1, and the
    no-subcommand help+exit-1 path).
  - `sphinx-build -b html docs/ docs/_build/html -W -q`: exit 0 (only
    the pre-existing `libamd_smi.so` runtime warning, same as T1-T4; no
    new autodoc module, `docs/api.rst` unchanged).
  - CLI smoke (`api/.env` already existed with `DEBUG=true`, not
    modified):
    - `python -m api.cli mc-server active 5h threshold 10m` -> DEBUG
      placeholder, `Armed: yes`, `Threshold: 10m`, `MC reachable: no`,
      exit 0.
    - `python -m api.cli mc-server status` -> DEBUG placeholder,
      `Threshold: 30m` (server default shown), `Players online: 0`,
      exit 0.
    - `python -m api.cli mc-server disable` -> DEBUG placeholder,
      `Armed: no`, `Last disarm reason: manual`, exit 0.
    - `python -m api.cli mc-server active 5x` -> `Error: invalid
      duration '5x': ...`, exit 1.
  - `git diff --stat` for the T5 commit: 4 files changed, 732
    insertions(+), 18 deletions(-).
  - Deviation: none.

- T6 (`955af1a docs: document minecraft watchdog in agents, readme and
  design`) on `feat/mc-watchdog-04-cli`:
  - Files: `AGENTS.md`, `README.md`, `IMPLEMENT_MC_WATCHDOG.md`.
  - `AGENTS.md`: Directory Map gained `api/mc/`, `api/lib/durations.py`,
    the new `api/test/test_*` files, the three watchdog templates,
    `daemon/mc-server-create.service`, `odd/tasks/`, and
    `IMPLEMENT_MC_WATCHDOG.md`; Environment Variables gained
    `MINECRAFT_PORT`/`MINECRAFT_SERVICE`; Architecture Patterns gained
    a "Minecraft Watchdog" section (server-side loop, in-memory
    boot-disarmed state, DEBUG never starting the loop, poweroff only
    when reachable+empty for the threshold, 5m grace / 3-restart
    recovery policy, polkit scoped to the one unit); Implementation
    Status gained the watchdog bullet, the CLI bullet now lists
    `mc-server`, and the test count was corrected to the observed 194
    (was stale at 48).
  - `README.md`: CLI command table gained the three `mc-server` rows; a
    new "Minecraft server watchdog" subsection under CLI documents the
    syntax, behavior, and the server-side deployment step (set
    `MINECRAFT_PORT`/`MINECRAFT_SERVICE`, re-run `cmd/install.sh` or
    install the polkit rule manually, restart `nexus-api`).
  - `IMPLEMENT_MC_WATCHDOG.md`: Status line changed from "Draft /
    iterating — nothing implemented yet" to "Implemented on branch
    chain feat/mc-watchdog-01..04"; rest of the design record
    unchanged.
  - `git diff --stat` for the T6 commit: 3 files changed, 102
    insertions(+), 7 deletions(-).
  - Deviation: none.

## Simplification Pass (2026-09-23)

User request: "Add to requirements.txt mcstatus, and rewrite the code to
be more simple." Route: direct/delegated ODD work on the already-complete
feature branch chain (not a new SDD change); single writer, no push/PR.

- **`api/mc/slp.py` rewritten to use `mcstatus`** (installed `mcstatus==14.2.0`,
  which pulls in `asyncio-dgram==3.0.0`; `dnspython` was already pinned at
  `2.8.0`, satisfying mcstatus's `>=2.4.2`). Replaces the hand-written Java
  Edition Server List Ping client (VarInt framing, socket handshake, MOTD
  chat-component parsing — ~250 lines) with `JavaServer(host, port,
  timeout=timeout).async_status(tries=1)`. Verified the installed API from
  source (`venv/lib/python3.14/site-packages/mcstatus/server.py`,
  `mcstatus/responses/java.py`, `mcstatus/responses/base.py`) rather than
  guessing: `status.players.online/.max`, `status.version.name`,
  `status.motd.to_plain()`, `status.latency`. Same `McStatus`/`probe()`
  contract (kept all fields; only `players_online`/`players_max` are
  actually consumed by the watchdog, but the rest cost nothing extra
  through mcstatus and are useful for `status` debugging). `probe()` is
  now `async def` (mcstatus's `async_status()` is a native coroutine), so
  `watchdog_loop()` awaits it directly instead of via `asyncio.to_thread`
  — one fewer thread hop per tick. `requirements-cli.txt` was NOT changed
  (`rg -n "mcstatus|api\.mc" api/cli` — no matches; the probe is
  server-side only).
- **`api/test/test_mc_slp.py` replaced**: 196 lines of VarInt/handshake/
  buffered-socket test doubles → 80 lines mocking `mcstatus.JavaServer`
  (5 focused tests: success, connection refused, timeout, protocol error,
  zero players). No real sockets opened, same as before.
- **`api/mc/watchdog.py` / `api/test/test_mc_watchdog.py`**: fixed the
  `asyncio.to_thread(slp.probe, ...)` call site (now `await slp.probe(...)`
  directly — the double-wrap would have produced an unawaited coroutine)
  and updated docstrings' SLP references; updated the four loop tests that
  patched `slp.probe` to use `AsyncMock`. No other watchdog logic changed:
  the lock/arm_generation race-guard and the `tick()` state machine were
  judged correct-and-necessary complexity, not over-engineering, so they
  were left alone.
- `api/main.py`, `api/cli/*`: no changes needed — neither imports
  `api.mc.slp` directly or depends on the old SLP contract.
- Docs: `IMPLEMENT_MC_WATCHDOG.md` (probe section + a new Decisions Log
  line), `AGENTS.md` (directory map, Minecraft Watchdog section,
  `MINECRAFT_PORT` description, test count 194 → 175).

### Where each change landed (rebase cascade)

- `refactor(mc): use mcstatus for the server list ping probe` (mcstatus +
  slp.py + its tests + requirements.txt + `IMPLEMENT_MC_WATCHDOG.md`) →
  committed on `feat/mc-watchdog-01-foundation`.
- `git checkout feat/mc-watchdog-04-cli && git rebase --update-refs
  feat/mc-watchdog-01-foundation` replayed 02/03/04 cleanly except one
  textual conflict in `IMPLEMENT_MC_WATCHDOG.md`'s Decisions Log (both the
  01 commit and the original T4 commit appended a line there) — resolved
  by keeping both lines.
- `fix(mc): await the mcstatus probe directly` (watchdog.py + its tests)
  → committed on `feat/mc-watchdog-02-logic`, since the async-probe
  contract change is a direct consequence of the 01 commit and only
  affects code that lives on 02.
- Second `git rebase --update-refs feat/mc-watchdog-02-logic` from
  `feat/mc-watchdog-04-cli` replayed 03/04 with no conflicts (neither
  touches `api/mc/slp.py` or `api/mc/watchdog.py`).
- `chore(odd): record simplification pass` (this entry, AGENTS.md) →
  committed on `feat/mc-watchdog-04-cli` tip.
- No changes needed on `feat/mc-watchdog-03-api` — `api/main.py`'s
  mc-server endpoints only call `mc_watchdog.arm/disarm/snapshot`, never
  `slp` directly.

### Verification

- `python -m pytest -q`: 100 passed at `feat/mc-watchdog-01-foundation`
  tip (was 119; SLP test count dropped from 24 to 5); 132 passed at
  `feat/mc-watchdog-02-logic` tip; 175 passed at
  `feat/mc-watchdog-03-api` and `feat/mc-watchdog-04-cli` tips (was 194
  total — the net -19 matches the SLP test rewrite, nothing else changed
  test count).
- `sphinx-build -b html docs/ docs/_build/html -W -q`: exit 0 at every
  branch tip touched (only the pre-existing `libamd_smi.so` runtime
  warning from importing `api.hw.telemetry`, same as every prior task).
- CLI smoke (`api/.env` DEBUG=true, not modified): `python -m api.cli
  mc-server active 5h threshold 10m` and `... mc-server status` both
  produce the same DEBUG placeholder output as before (armed/remaining/
  threshold/players/reachable), exit 0.
- `rg -n "mcstatus|api\.mc" api/cli`: no matches.
- Branch chain: `git log --oneline main..feat/mc-watchdog-04-cli` shows
  15 commits (14 before + this pass's 2 code commits, minus none removed,
  plus this doc commit = confirmed linear); `git merge-base
  --is-ancestor <branch> feat/mc-watchdog-04-cli` true for 01/02/03 both
  before and after each rebase.
- Slice sizes (`git diff --shortstat <A>..<B>`), before → after:
  - `main..01-foundation`: 1222 → 902 insertions (**-320**, the mcstatus
    win).
  - `01-foundation..02-logic`: 869 → 873 insertions (+4, the
    to_thread-removal fixup and its test changes).
  - `02-logic..03-api`: 485 → 485 insertions (unchanged).
  - `03-api..04-cli`: 931 → 931 insertions (unchanged, before this doc
    commit).
  - Total `main..04-cli`: 3493+34d → 3177+34d insertions (**-316** net
    lines across the whole chain).

Status: **done**. Working tree clean on `feat/mc-watchdog-04-cli` after
this doc commit. Push/PR remain the user's decision, unchanged from
before this pass.

## Next Step

T5 and T6 done on `feat/mc-watchdog-04-cli`. All tasks (T0-T6) complete,
plus the mcstatus simplification pass above. Next: manual verification on
nexus-lan (arm/status/disable via CLI, poweroff after an empty threshold,
restart after MC is killed) and opening the chained PRs (user decision —
draft/no-merge tracker PR to `main`, then PR1..PR4 per branch, per the
`auto-chain` / `feature-branch-chain` delivery strategy recorded above).
