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
  main.py               App & route definitions, verify_api_key dependency
  config/
    __init__.py          Package docstring
    paths.py             Resolved filesystem paths + ensure_dotenv()
    runtime.py           APP_NAME, PORT, DEBUG, API_KEY from dotenv
  hw/
    telemetry.py        Real hardware metrics: psutil + NVML + AMD SMI + hwmon + power_supply
    power.py            systemctl poweroff / suspend wrappers
  lib/
    templates.py         load_template(name) — reads JSONC, strips comments, returns dict
  test/
    test_auth.py         X-API-Key matrix, public routes, redirects
    test_health.py       Liveness payload, no-store, monotonic uptime
    test_telemetry.py    Payload shape, GPU schema
    test_power.py        DEBUG-gating, production paths, error handling
  .env.example           Committed template (APP_NAME, PORT, DEBUG, API_KEY)
  .env                   Gitignored local config (ensure_dotenv copies from example)
conftest.py              Root pytest fixtures (client, auth_headers) + sys.path bootstrap
requirements.txt         Fully pinned Python deps (incl. pytest)
cmd/
  install.sh             Bootstrap script: packages → venv → pip → polkit → systemd
                         Use -dev flag to skip polkit and systemd installation
daemon/
  nexus-api.service      Systemd unit with hardening (ProtectSystem, PrivateTmp, etc.)
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
SERVER_ACCESS.md         Tracked but EMPTY placeholder — keep credentials out of git!
.github/workflows/
  docs.yml               Sphinx build + GitHub Pages deploy
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
import), and `timestamp`, with `Cache-Control: no-store`.
No hardware, DB, or external calls — the endpoint responding IS the liveness
signal. Note: it sits behind the `X-API-Key` check like every `/api/v1`
route, so monitoring probes must send the key.

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

## Environment Variables

| Variable   | Default     | Description                  |
|------------|-------------|------------------------------|
| `APP_NAME` | `Nexus API` | App title for docs & root    |
| `PORT`     | `8000`      | Server listen port           |
| `DEBUG`    | `True`      | Hot-reload & verbose logging |
| `API_KEY`  | *(empty)*   | Required for `X-API-Key` auth on `/api/v1` routes |

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
- **Power management is wired and DEBUG-gated** (`/api/v1/power/poweroff`,
  `/api/v1/power/sleep`): `api/hw/power.py` wraps `systemctl poweroff/suspend`.
  On success they return `{"poweroff_triggered": "true"}` /
  `{"sleep_triggered": "true"}`. When `DEBUG=true`, both endpoints return stub
  templates instead of executing the real commands — accidental shutdowns
  during development are impossible.
  On systemctl failure the endpoints return HTTP 500 with the error detail.
- **Frontend is void code**: `App.tsx` returns an empty fragment. `App.css` and
  `index.css` are empty files. No components, no routing, no state, no API
  calls — just a Vite + React + TypeScript skeleton.
- **Tests**: pytest suite in `api/test/` (26 tests: auth matrix, health,
  telemetry shape, power DEBUG-gating). Frontend tests: none yet.
- **No frontend-backend integration**: Vite config has no proxy to the API.
