# nexus-API

A secure, lightweight 24/7 daemon API to monitor telemetry, sniff systemd logs,
and manage server power states (sleep & shutdown). Built with FastAPI (Python)
and a React + TypeScript + Vite frontend.

## Current State

> **Real telemetry is live — power management and frontend are in progress.**

- **Telemetry** (`/api/v1/telemetry`): Returns live hardware metrics (CPU, RAM,
  swap, NVIDIA/AMD GPU) via `psutil`, NVML, and AMD SMI. Backed by `api/hw/stats.py`.
- **Power management** (`/api/v1/power/poweroff`, `/api/v1/power/sleep`): Wired
  to `api/hw/power.py` (`systemctl poweroff/suspend`). On success they return
  `{"poweroff_triggered": "true"}` / `{"sleep_triggered": "true"}`. Gated by
  `DEBUG` — in dev mode the endpoints return stub templates instead of
  executing real commands.
- **Frontend**: The React app (`App.tsx`) is a scaffold — no UI, no dashboard,
  no API integration.
- **Tests**: 26 pytest tests in `api/test/` (auth matrix, health, telemetry
  shape, power DEBUG-gating).

## Architecture

```
nexus-API/
├── api/                 # FastAPI backend
│   ├── main.py          # App entrypoint, route definitions
│   ├── config/          # Runtime settings (dotenv) & paths
│   ├── hw/              # Hardware interfaces (telemetry, power)
│   │   ├── stats.py     # psutil + NVML + AMD SMI metrics collector
│   │   └── power.py     # systemctl poweroff / suspend wrappers
│   └── lib/             # Helpers (JSONC template loader)
├── daemon/              # Systemd unit for production deployment
│   └── nexus-api.service
├── frontend/            # React 19 + TypeScript + Vite
│   ├── src/             # App components & styles
│   └── public/          # Static assets (favicon.svg)
├── templates/           # Real API response examples (JSONC, tutorial for agents)
├── docs/                # Sphinx documentation (autodoc + Furo theme)
├── cmd/                 # Shell scripts (install.sh)
└── .github/workflows/   # CI/CD (Sphinx docs → GitHub Pages)
```

## API Endpoints

All business routes live under the versioned `/api/v1` prefix. The root
(`/`) and the API root (`/api/v1/`) redirect to the Swagger UI at `/docs`.

| Method | Path                        | Description                           | Backend           |
|--------|------------------------------|---------------------------------------|-------------------|
| GET    | `/`                          | Redirect to Swagger UI (`/docs`)      | —                 |
| GET    | `/api/v1/`                   | Redirect to Swagger UI (`/docs`)      | —                 |
| GET    | `/api/v1/health`             | Liveness probe (version, uptime)      | computed live    |
| POST   | `/api/v1/power/poweroff`     | Initiate system poweroff              | `api/hw/power.py` |
| POST   | `/api/v1/power/sleep`        | Initiate system sleep                 | `api/hw/power.py` |
| GET    | `/api/v1/telemetry`          | Live CPU, RAM, swap, GPU metrics      | `api/hw/stats.py` |
| GET    | `/favicon.ico`               | SVG favicon                           | static file       |

Power endpoints are **DEBUG-gated**: when `DEBUG=true` in `.env` they return
stub templates instead of executing real `systemctl` commands, so the host
cannot be shut down or suspended accidentally during development.

## Prerequisites

- **Python 3.12+** with pip
- **Node.js 22+** + pnpm (for frontend)
- Linux system with systemd (for full telemetry/power features)
- For NVIDIA GPU metrics: NVIDIA drivers with NVML support
- For AMD GPU metrics: ROCm stack with `amdsmi` (`libamd_smi.so`)

## Installation

### 1. Clone

```bash
git clone https://github.com/mochapulse/nexus-API.git
cd nexus-API
```

### 2. Backend (Python API)

**Option A — production install (with systemd service):**

```bash
chmod +x cmd/install.sh
./cmd/install.sh
```

This installs system packages, creates a virtual environment, deploys the
polkit rule for passwordless power/sleep, and enables the systemd service.

**Option B — development install (skip system artifacts):**

```bash
./cmd/install.sh -dev
```

Installs packages, venv, and pip dependencies only. Does NOT deploy polkit
rules or systemd service — ideal for local development.

**Option C — manual:**

```bash
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

**Run the test suite** (from the repo root, venv active):

```bash
python -m pytest        # full suite
python -m pytest -q     # summary only
```

The 26 tests in `api/test/` cover the auth matrix (X-API-Key), health
payload, telemetry shape, and the DEBUG-gating of the power endpoints.
`systemctl` is always mocked — the suite can never power off or suspend
the host.

**Environment configuration:**

Copy the example env file if it doesn't already exist (the API does this
automatically on startup, but you can do it manually):

```bash
cp api/.env.example api/.env
```

Edit `api/.env` to adjust settings:

| Variable  | Default     | Description                      |
|-----------|-------------|----------------------------------|
| `APP_NAME`| `Nexus API` | App title shown in docs & root   |
| `PORT`    | `8000`      | Server listen port               |
| `DEBUG`   | `True`      | Hot-reload, verbose logging      |
| `API_KEY` | *(empty)*   | Shared secret for `X-API-Key` header; **required in production** |

> **Authentication**: every `/api/v1` endpoint requires an `X-API-Key`
> header matching `API_KEY`. The docs (`/docs`, `/redoc`, `/openapi.json`)
> stay public. In DEBUG mode an unset key is allowed for convenience; in
> production an unset key returns HTTP 503 — the server refuses to serve
> unauthenticated.

### 3. Frontend

```bash
cd frontend
pnpm install
```

## Running

### Start the API server

```bash
source venv/bin/activate
python -m api.main
```

The server starts on `http://0.0.0.0:8000` (configurable via `PORT` in `.env`).

Verify it's running:

```bash
curl -i http://localhost:8000/        # 307 → /docs (Swagger UI) — public

# All /api/v1 endpoints need the key from api/.env:
curl -H "X-API-Key: $API_KEY" http://localhost:8000/api/v1/health
# {"status":"ok","version":"0.1.0","uptime_seconds":655,"timestamp":1718800000}

curl -H "X-API-Key: $API_KEY" http://localhost:8000/api/v1/telemetry
# {"uptime_seconds":655,"cpu":{"overall_usage_percent":8.9,...},...}

curl -i http://localhost:8000/api/v1/health    # no key → 401 Unauthorized
```

### Systemd service (production)

After running `./cmd/install.sh`, the `nexus-api` service is enabled for
autostart. To start it immediately:

```bash
sudo systemctl start nexus-api
```

```bash
systemctl status nexus-api      # check service health
journalctl -u nexus-api -f      # tail logs
sudo systemctl stop nexus-api   # stop the service
```

### Start the frontend dev server

```bash
cd frontend
pnpm dev
```

The Vite dev server starts on `http://localhost:5173` by default.

### Build frontend for production

```bash
cd frontend
pnpm build
```

Output goes to `frontend/dist/`.

## Releases

Releases are **git tags**. The API version is derived automatically at
startup from the nearest `v*` tag reachable from HEAD
(`git describe --tags --abbrev=0 --dirty --match v*`), so bumping the
version is a one-step tag operation — no file edits, no commits.

### Versioning rules (SemVer)

| Bump   | When                                   | Example       |
|--------|----------------------------------------|---------------|
| MAJOR  | Breaking change (renamed routes, removed fields) | `v1.0.0` |
| MINOR  | New feature (new endpoint, new fields) | `v0.2.0` |
| PATCH  | Bugfix                                 | `v0.1.1` |

### Release steps

```bash
# 1. Everything committed and pushed on main
git status                  # clean tree
git push origin main

# 2. Tag the current HEAD with the next version
git tag v0.1.1

# 3. Publish the tag
git push origin v0.1.1

# 4. Verify — the running API now reports the new version
curl http://localhost:8000/api/v1/health
# {"status":"ok","version":"0.1.1","uptime_seconds":42,"timestamp":...}
```

### How the version behaves

- **Git checkout deployment**: version = last tag reachable from HEAD
  (e.g. `0.1.1`), plus a `-dirty` suffix when the working tree has
  uncommitted changes (`0.1.1-dirty`).
- **Non-git deployment** (tarball, copied files): no tag lookup possible,
  the fallback constant `_FALLBACK_VERSION` in `api/__init__.py` is used.
  Bump it manually there, or deploy a git checkout.
- The version surfaces in `GET /api/v1/health` and in the OpenAPI/Swagger
  UI at `/docs`.

## Documentation

Sphinx docs live in `docs/` and use the Furo theme with autodoc from source.

```bash
source venv/bin/activate
sphinx-build -b html docs/ docs/_build/html
```

Open `docs/_build/html/index.html` in a browser, or serve with:

```bash
python -m http.server -d docs/_build/html
```

Docs are automatically built and deployed to GitHub Pages on every push to
`main` via the workflow at `.github/workflows/docs.yml`.

## CI/CD

| Workflow   | Trigger                   | Action                            |
|------------|---------------------------|-----------------------------------|
| `docs.yml` | push/PR to `main`         | Build Sphinx docs, deploy to Pages|

## Tech Stack

| Layer    | Technology                       |
|----------|----------------------------------|
| Backend  | FastAPI, Uvicorn                 |
| Config   | python-dotenv                    |
| HW       | psutil, pynvml, amdsmi (optional)|
| Docs     | Sphinx, Furo theme, autodoc      |
| Frontend | React 19, TypeScript, Vite       |
| Linting  | ESLint, typescript-eslint        |
| Package  | pnpm                             |
| CI/CD    | GitHub Actions                   |
