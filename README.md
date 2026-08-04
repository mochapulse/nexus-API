# nexus-API

A secure, lightweight 24/7 daemon API to monitor telemetry, sniff systemd logs,
and manage server power states (sleep & shutdown). Built with FastAPI (Python)
and a React + TypeScript + Vite frontend.

## Current State

> **Real telemetry is live — power management and frontend are in progress.**

- **Telemetry** (`/telemetry`): Returns live hardware metrics (CPU, RAM, swap,
  NVIDIA/AMD GPU) via `psutil`, NVML, and AMD SMI. Backed by `api/hw/stats.py`.
- **Power management** (`/power/poweroff`, `/power/sleep`): Logic exists in
  `api/hw/power.py` (calls `systemctl poweroff/suspend`) but the endpoints
  still return JSONC template stubs — not yet wired to the real functions.
- **Frontend**: The React app (`App.tsx`) is a scaffold — no UI, no dashboard,
  no API integration.
- **Sentry**: SDK installed but not wired into the app.
- **Tests**: None written yet.

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
├── templates/           # JSONC response stubs for API endpoints
├── docs/                # Sphinx documentation (autodoc + Furo theme)
├── cmd/                 # Shell scripts (install.sh)
└── .github/workflows/   # CI/CD (Sphinx docs → GitHub Pages)
```

## API Endpoints

| Method | Path               | Description                           | Backend           |
|--------|---------------------|---------------------------------------|-------------------|
| GET    | `/`                 | Root health-check                     | —                 |
| GET    | `/health`           | Health status                         | template stub     |
| POST   | `/power/poweroff`   | Initiate system poweroff              | template stub     |
| POST   | `/power/sleep`      | Initiate system sleep                 | template stub     |
| POST   | `/telemetry`        | Live CPU, RAM, swap, GPU metrics      | `api/hw/stats.py` |

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
curl http://localhost:8000/
# {"msg":"Nexus API is running! (Nexus API)"}

curl http://localhost:8000/health
# {"status":"up","healthy":true,"timestamp":1718800000}

curl -X POST http://localhost:8000/telemetry
# {"uptime_seconds":655,"cpu":{"overall_usage_percent":8.9,...},...}
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
| Errors   | Sentry SDK                       |
