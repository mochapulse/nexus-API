# AGENTS.md — Nexus API

## Project Overview

nexus-API is a FastAPI backend + React frontend for the Nexus platform.
It serves health checks, telemetry collection, and power-management endpoints,
with a React dashboard frontend.

- **Repo**: https://github.com/mochapulse/nexus-API
- **Python**: 3.12+ (virtualenv in `venv/`)
- **Node**: 22+ with pnpm
- **Sphinx docs**: deployed to GitHub Pages

## Directory Map

```
api/                    FastAPI backend
  __init__.py           __version__ via git describe + _FALLBACK_VERSION
  main.py               App & route definitions, verify_api_key dependency, lifespan
  cli/                  CLI package (nexus-API command)
    __init__.py          argparse entry point + command dispatch (incl. mc-server)
    http_client.py       Nexus + ESP HTTP helpers (httpx)
    commands.py          config, wol, health, poweroff, sleep, mc-server handlers
    nexus_tui.py         Textual TUI for Nexus telemetry
    esp_tui.py           Textual TUI for ESP status + plotext charts
    json_output.py       Raw JSON output mode for telemetry
    __main__.py          Entry point for `python -m api.cli`
  config/
    __init__.py          Package docstring
    paths.py             Resolved filesystem paths + ensure_dotenv()
    runtime.py           APP_NAME, PORT, DEBUG, API_KEY, DUCKDNS_*, NEXUS_*, ESP_*, MINECRAFT_*
  hw/
    telemetry.py        Real hardware metrics: psutil + NVML + AMD SMI + hwmon + power_supply
    power.py            systemctl poweroff / suspend wrappers
  net/
    utils.py            Async IP detection + DuckDNS updater (httpx)
    state.py            Shared metrics for /health (last_duckdns_update_ms, connectivity_delay_ms)
    duckdns_service.py  Background update loop (lifespan-managed)
  mc/
    slp.py              Minecraft status probe (mcstatus), probe() -> McStatus
    service.py          is_active()/restart() wrappers over systemctl (with timeout)
    watchdog.py         Watchdog state dataclass + pure tick() + async loop + arm/disarm/status
  lib/
    templates.py         load_template(name) — reads JSONC, strips comments, returns dict
    durations.py         parse_duration()/format_duration() — shared by CLI and API (stdlib only)
  test/
    test_auth.py         X-API-Key matrix, public routes, redirects
    test_health.py       Liveness payload, no-store, monotonic uptime
    test_telemetry.py    Payload shape, GPU schema
    test_power.py        DEBUG-gating, production paths, error handling
    test_duckdns.py      DuckDNS utils, service loop, connectivity, state tracking
    test_durations.py    Duration parser valid/invalid formats
    test_mc_slp.py       Minecraft status probe (mocked mcstatus)
    test_mc_service.py   systemctl wrappers
    test_mc_watchdog.py  tick() state machine, arm/disarm/snapshot, polling loop
    test_mc_endpoints.py mc-server/watchdog endpoints (auth, DEBUG stub, production, 422s)
    test_cli_mc.py       mc-server CLI parser + cmd_mc_server (DEBUG/production)
  .env.example           Committed template (APP_NAME, PORT, DEBUG, API_KEY)
  .env                   Gitignored local config (ensure_dotenv copies from example)
conftest.py              Root pytest fixtures (client, auth_headers) + sys.path bootstrap
requirements.txt         Fully pinned Python deps (incl. pytest)
requirements-cli.txt     CLI-only pinned deps (httpx, python-dotenv, textual, plotext)
cmd/
  install.sh             Bootstrap script: packages → venv → pip → polkit → systemd
                         Use -dev flag to skip polkit and systemd installation
  deploy-cli-linux.sh    Deploy CLI workstation: venv + .env + shell alias
  deploy-cli-windows.ps1 Deploy CLI workstation on Windows: venv + .env + .cmd shim + user PATH
daemon/
  nexus-api.service      Systemd unit with hardening (ProtectSystem, PrivateTmp, etc.)
  mc-server-create.service  Reference copy of the production Minecraft unit (tmux-backed, Type=forking)
docs/
  conf.py                Sphinx config (autodoc, napoleon, intersphinx, furo)
  index.rst              TOC tree entrypoint
  api.rst                Autodoc directives for api modules
frontend/
  src/
    main.tsx             React root
    App.tsx              Empty scaffold (ready for dashboard)
  public/favicon.svg     Shared favicon (served by API and frontend)
  vite.config.ts         Vite config (React plugin only, no proxy yet)
templates/
  get-health.jsonc       Health response example (docs only, computed live)
  get-telemetry.jsonc    Telemetry data stub (CPU, RAM, GPU, uptime)
  post-poweroff.jsonc    Poweroff triggered stub
  post-sleep.jsonc       Sleep triggered stub
  get-mc-server-watchdog.jsonc     Watchdog status stub
  post-mc-server-watchdog.jsonc    Watchdog arm response stub
  delete-mc-server-watchdog.jsonc  Watchdog disarm response stub
SERVER_ACCESS.md         Tracked but EMPTY placeholder — keep credentials out of git!
odd/
  tasks/                 Organic Driven Development feature task documents
.github/workflows/
  docs.yml               Sphinx build + GitHub Pages deploy
IMPLEMENT_MC_WATCHDOG.md Design record for the Minecraft server watchdog feature
```

## Development Commands

### Backend

```bash
source venv/bin/activate          # activate virtualenv
python -m api.main                # start dev server (hot-reload in DEBUG mode)
pip install -r requirements.txt   # sync dependencies
```

### Tests

```bash
source venv/bin/activate
python -m pytest          # run the full suite (from the repo root)
python -m pytest -q      # quiet, summary only
```

Tests live in `api/test/` (auth matrix, health, telemetry, power-gating)
with shared fixtures in the root `conftest.py`. The `systemctl` commands
are always mocked — the suite can never power off or suspend the host.

### Frontend

```bash
cd frontend
pnpm install      # install deps
pnpm dev          # start Vite dev server (http://localhost:5173)
pnpm build        # type-check + production build
pnpm lint         # ESLint
pnpm preview      # preview production build
```

### Docs

```bash
source venv/bin/activate
sphinx-build -b html docs/ docs/_build/html    # build
sphinx-build -b html docs/ docs/_build/html -W # build (warnings as errors, same as CI)
```

### Releases

Releases are git tags; the version is never edited by hand. At import time
`api/__init__.py` runs `git describe --tags --abbrev=0 --dirty --match v*`
against the project root: the nearest `v*` tag reachable from HEAD becomes
`__version__` (with `-dirty` appended when the tree is dirty). If git is
unavailable (tarball deployment), `_FALLBACK_VERSION` is used instead.

```bash
git tag v0.1.1 && git push origin v0.1.1
```

SemVer: MAJOR = breaking, MINOR = feature, PATCH = bugfix. The version
surfaces in `/api/v1/health` and OpenAPI at `/docs`. Full tutorial in
README.md → Releases.

### Updating the server deployment

The server runs from a git checkout (`~/nexus-API` on the machine, per
`cmd/install.sh`). Update = pull code AND tags, restart:

```bash
cd ~/nexus-API
git pull origin main
git fetch --tags          # tags drive the version — they must arrive with the code
source venv/bin/activate && pip install -r requirements.txt   # when deps changed
sudo systemctl restart nexus-api                              # version is read at import time
```

Verify with `systemctl status nexus-api` and `GET /api/v1/health`
(`X-API-Key` header) — the reported version must match the release tag.
A stale version usually means: tags not fetched or service not restarted.

### CLI Workstation Deploy

The CLI is an HTTP client — it needs only a handful of deps (httpx, textual,
python-dotenv). Deploy scripts create a workspace in `~/.nexus-API/workstation/`
with a `.env` (DEBUG=false enforced) and an isolated virtualenv. The full
`requirements.txt` is NOT used; `requirements-cli.txt` pins only what the
CLI needs, avoiding platform-blocked packages (uvloop, amdsmi) on Windows.

**Linux** (Bash alias, added to shell rc):
```bash
bash cmd/deploy-cli-linux.sh        # create workspace + alias
source ~/.bashrc                    # or ~/.zshrc
nexus-API health                    # verify
```

**Windows** (PowerShell, .cmd shim on user PATH):
```powershell
powershell -ExecutionPolicy Bypass -File cmd\deploy-cli-windows.ps1
# open a new terminal:
nexus-API health
```

Windows deploy creates `%USERPROFILE%\.nexus-API\workstation\bin\nexus-API.cmd`
and prepends it to the user PATH. Works in cmd, PowerShell, and Windows Terminal.
Re-running is idempotent.

## Architecture Patterns

### Versioned Routing (api/main.py)

All business routes live on `api_v1_router = APIRouter(prefix="/api/v1")`,
mounted via `app.include_router(api_v1_router)`. The root (`/`) and the API
root (`/api/v1/`) redirect to the Swagger UI at `/docs`. Only `/favicon.ico`
stays as a standalone root route. New endpoints go on the router, not on
`app` directly.

### API-Key Auth (api/main.py)

Every route on `api_v1_router` is protected by the `verify_api_key`
dependency: the `X-API-Key` header must equal `runtime.API_KEY` (from
`.env`). Docs routes (`/docs`, `/redoc`, `/openapi.json`) and app-level
helpers (`/`, `/favicon.ico`) stay public. When `API_KEY` is unset the
check fails closed in production (HTTP 503) and passes silently in DEBUG.

### Hardware Metrics (api/hw/telemetry.py)

`get_system_metrics()` is an async function that offloads blocking C-driver calls
(NVML, AMD SMI, psutil) to a worker thread via `asyncio.to_thread()`. Returns
orjson-encoded bytes that can be decoded to str or returned raw. Also reads
hwmon and power_supply sensors from sysfs for voltage, current, power, and
battery metrics.

GPU detection is best-effort:
- **NVIDIA**: `pynvml` — caught silently on `NVMLError`
- **AMD**: `amdsmi` — import-time init/shutdown test validates the native lib;
  caught on any `Exception` since the import may succeed but the .so may fail

### JSONC Template Stubs

Power endpoints (DEBUG-gated) return static JSONC templates loaded by
`api.lib.templates.load_template()`. Comments (`//`, `/* */`) are stripped via
regex before `json.loads()`. Templates live in `templates/` and follow the
naming convention `{method}-{name}.jsonc`.

Templates double as a tutorial: every file mirrors a REAL captured API
response, and `templates/get-health.jsonc` documents the computed live health
payload (it is NOT loaded by `load_template()`). Keep them in sync when
response shapes change.

Computed endpoints (health, telemetry) do NOT use templates — they build the
payload at request time.

To add a new endpoint:
1. Create a `templates/{method}-{name}.jsonc` file
2. Add a route in `api/main.py` calling `load_template("{method}-{name}")`
3. Add a docstring describing the endpoint

### Health Endpoint (api/main.py)

`GET /api/v1/health` is a dependency-free liveness probe: it returns
`status`, `version` (derived from the nearest git `v*` tag via
`git describe`, with a `_FALLBACK_VERSION` constant in `api/__init__.py`
for non-git deployments), `uptime_seconds` (monotonic clock anchored at
import), `timestamp`, `last_duckdns_update_ms`, and `connectivity_delay_ms`,
with `Cache-Control: no-store`.
No hardware, DB, or external calls — the endpoint responding IS the liveness
signal. Note: it sits behind the `X-API-Key` check like every `/api/v1`
route, so monitoring probes must send the key.

### Minecraft Watchdog (api/mc/, api/lib/durations.py)

`nexus-API mc-server active <D> [threshold <T>] | disable | status` arms a
server-side watchdog (`api/mc/watchdog.py`) that powers off the Nexus host
when Minecraft is empty. The loop runs as an asyncio task in `lifespan()`
(skipped entirely in `DEBUG`) and its state — armed flag, deadline,
threshold, empty-since, restart count — lives **in memory only**, so a
reboot or service restart always starts disarmed.

Every 30s while armed: probe Minecraft's status with `mcstatus`
(`api/mc/slp.py`, `localhost:MINECRAFT_PORT`). Reachable with 0 players for
`threshold_seconds` (default 1800s / 30m) triggers `systemctl poweroff`
(only when reachable **and** empty — an unreachable server never counts as
empty and never causes a poweroff). Unreachable triggers the recovery
policy: a 5-minute startup grace after each restart, then
`systemctl restart $MINECRAFT_SERVICE` (`api/mc/service.py`), capped at 3
restarts per armed window; after the 3rd failed restart the watchdog
disarms itself (`last_disarm_reason: "mc_unrecoverable"`) instead of
retrying forever. The active window expiring also disarms (`"expired"`),
with no poweroff. The decision logic is the pure function
`tick(state, now, probe_result, unit_state) -> Action`, so tests never
sleep, probe a real socket, or call `systemctl`.

`api/lib/durations.py` (`parse_duration`/`format_duration`, stdlib-only) is
shared by the CLI, which parses user input before sending it, and the API,
which validates it again server-side. Restarting the `mc-server-create`
unit needs a polkit rule scoped to exactly that unit and the `start`/
`restart` verbs (installed by `cmd/install.sh`); never grant
`manage-units` for all units. See `IMPLEMENT_MC_WATCHDOG.md` for the full
design record and decisions log.

### Config Bootstrap

On startup, `api.config.paths.ensure_dotenv()` copies `.env.example` → `.env`
if no `.env` exists. Runtime config (`api.config.runtime`) reads from dotenv after.

### Project Paths

All filesystem paths are resolved relative to `api/config/paths.py`:
- `API_DIR` = `api/` directory
- `PROJECT_DIR` = repo root
- `TEMPLATES_DIR` = `<root>/templates/`
- `DOTENV_PATH` = `<root>/api/.env`
- `FAVICON_PATH` = `<root>/frontend/public/favicon.svg`

## Code Conventions

- Python: Google-style docstrings (napoleon), type hints everywhere
- Sphinx autodoc reads docstrings for API reference — keep them accurate
- Frontend: strict TypeScript, ESLint flat config with `typescript-eslint`
- Package manager: pnpm (no npm/yarn)
- Tests: pytest via `python -m pytest` from the repo root
- `.env` is gitignored; `.env.example` is committed
- PowerShell scripts (.ps1) must be pure ASCII -- no em-dashes, arrows, or box-drawing characters (PowerShell 5 cannot parse them)

## Environment Variables

| Variable   | Default     | Description                  |
|------------|-------------|------------------------------|
| `APP_NAME` | `Nexus API` | App title for docs & root    |
| `PORT`     | `8000`      | Server listen port           |
| `DEBUG`    | `True`      | Hot-reload & verbose logging |
| `API_KEY`  | *(empty)*   | Required for `X-API-Key` auth on `/api/v1` routes |
| `DUCKDNS_DOMAIN` | *(empty)* | DuckDNS subdomain; service disabled when empty |
| `DUCKDNS_TOKEN` | *(empty)* | DuckDNS API token; service disabled when empty |
| `NEXUS_IP` | `localhost` | Nexus API server IP for CLI requests |
| `NEXUS_PORT` | `8000` | Nexus API server port for CLI requests |
| `ESP_IP` | *(empty)* | ESP32 device IP for WOL and status |
| `ESP_PORT` | *(empty)* | ESP32 device HTTPS port |
| `ESP_API_KEY` | *(empty)* | ESP32 API key for `X-API-Key` header |
| `MINECRAFT_PORT` | `25565` | Minecraft server port for the mcstatus status probe (localhost) |
| `MINECRAFT_SERVICE` | `mc-server-create` | Systemd unit name the watchdog restarts |

## CI/CD

Single workflow `docs.yml`:
- Triggered on push/PR to `main` when `api/**`, `docs/**`, or `requirements.txt` changes
- Builds Sphinx HTML with `-W` (warnings = errors)
- PRs: uploads artifact (7-day retention)
- Push to main: deploys to GitHub Pages via `peaceiris/actions-gh-pages`

## External Services

- **GitHub Pages**: hosts Sphinx documentation

## Implementation Status

- **Telemetry is live** (`/api/v1/telemetry`): `api/hw/telemetry.py` returns real CPU,
  RAM, swap, GPU metrics via psutil, NVML, and AMD SMI. Also reads hwmon and
  power_supply sensors for voltage, current, power, and battery data. AMD SMI
  gracefully degrades when `libamd_smi.so` is absent.
- **Power management is live** (`/api/v1/power/poweroff`,
  `/api/v1/power/sleep`): `api/hw/power.py` wraps `systemctl poweroff/suspend`.
  On success they return `{"poweroff_triggered": "true"}` /
  `{"sleep_triggered": "true"}`. When `DEBUG=true`, both endpoints return stub
  templates instead of executing the real commands — accidental shutdowns
  during development are impossible.
  On systemctl failure the endpoints return HTTP 500 with the error detail.
- **DuckDNS dynamic DNS is live** (`api/net/`): Background service
  (`api/net/duckdns_service.py`) updates a DuckDNS subdomain with the
  host's public IP. Runs as a lifespan-managed asyncio task in production.
  Waits for TCP connectivity to `google.com:443`, updates DuckDNS, then
  sleeps 5 hours. Retries every 5 minutes on failure. State visible
  via `/api/v1/health` (`last_duckdns_update_ms`, `connectivity_delay_ms`).
  Disabled when `DEBUG=true` or `DUCKDNS_DOMAIN`/`DUCKDNS_TOKEN` are unset.
- **CLI is live** (`api/cli/`): `nexus-API` command with subcommands for
  config, WOL, telemetry (Textual TUI with `-j` JSON mode), health, poweroff,
  sleep, and mc-server (`active`/`disable`/`status`).
  WOL/poweroff/sleep are DEBUG-gated. Telemetry TUIs use native Textual widgets
  (ProgressBar, Sparkline) and auto-refresh every 2s. ESP TUI includes PlotextPlot
  time-series charts. Cross-platform workstation deploy scripts for Linux and Windows.
  Uses `NEXUS_IP`/`NEXUS_PORT` for Nexus API and `ESP_IP`/`ESP_PORT` for ESP32.
- **Minecraft server watchdog is live** (`/api/v1/mc-server/watchdog`,
  `api/mc/`, `nexus-API mc-server`): arms a server-side loop that restarts
  Minecraft when unreachable and powers off the host when it is reachable
  with 0 players for the configured threshold. State is in-memory only
  (always disarmed on boot). `DEBUG=true` never starts the loop and both
  the CLI and the endpoints return stub payloads instead of sending/acting
  on real requests. See "Minecraft Watchdog" under Architecture Patterns
  and `IMPLEMENT_MC_WATCHDOG.md` for the full design.
- **Frontend is void code**: `App.tsx` returns an empty fragment. `App.css` and
  `index.css` are empty files. No components, no routing, no state, no API
  calls — just a Vite + React + TypeScript skeleton.
- **Tests**: pytest suite in `api/test/` (175 tests: auth matrix, health,
  telemetry shape, power DEBUG-gating, DuckDNS utils and service, duration
  parsing, Minecraft status probe (mocked mcstatus) and systemd wrappers,
  watchdog state machine and polling loop, mc-server endpoints, and the
  mc-server CLI). Frontend tests: none yet.
- **No frontend-backend integration**: Vite config has no proxy to the API.
