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
- [ ] T4
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

## Next Step

T3 done on `feat/mc-watchdog-02-logic`. Next: T4 (API endpoints + lifespan,
runtime config, `.env.example`, templates, polkit in `install.sh` + tests)
on `feat/mc-watchdog-03-api`.
