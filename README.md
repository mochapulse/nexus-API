# nexus-API

A secure, lightweight 24/7 daemon API to monitor telemetry, sniff systemd logs,
and manage server power states (sleep & shutdown). Built with FastAPI (Python)
and a React + TypeScript + Vite frontend.

## Current State

> **Work in progress — both frontend and backend logic are placeholder stubs.**

- **Frontend**: The React app (`App.tsx`) is a completely empty component — no
  UI, no dashboard, no API integration. Only the project scaffold is in place
  (Vite + React + TypeScript + ESLint).
- **API templates**: All endpoint responses return hardcoded JSON stubs from
  `templates/`. Endpoints like `/telemetry`, `/power/poweroff`, and
  `/power/sleep` return static placeholder data — they do NOT actually collect
  telemetry, sniff systemd logs, or control power states.
- **Sentry**: SDK is installed but not wired into the app.
- **Tests**: None written yet.

## Architecture

```
nexus-API/
├── api/                 # FastAPI backend
│   ├── main.py          # App entrypoint, route definitions
│   ├── config/          # Runtime settings (dotenv) & paths
│   └── lib/             # Helpers (JSONC template loader)
├── frontend/            # React 19 + TypeScript 6 + Vite 8
│   ├── src/             # App components & styles
│   └── public/          # Static assets (favicon.svg)
├── templates/           # JSONC response stubs for API endpoints
├── docs/                # Sphinx documentation (autodoc + Furo theme)
├── cmd/                 # Shell scripts (install.sh)
└── .github/workflows/   # CI/CD (Sphinx docs → GitHub Pages)
```

## API Endpoints

| Method | Path               | Description                  | Template              |
|--------|---------------------|------------------------------|------------------------|
| GET    | `/`                 | Root health-check            | —                      |
| GET    | `/health`           | Health status                | `get-health.jsonc`     |
| POST   | `/power/poweroff`   | Initiate system poweroff     | `post-poweroff.jsonc`  |
| POST   | `/power/sleep`      | Initiate system sleep        | `post-sleep.jsonc`     |
| POST   | `/telemetry`        | Collect system telemetry     | `post-telemetry.jsonc` |

All JSON responses are driven by templates in `templates/`. Templates use JSONC
(JSON with comments); comments are stripped at load time.

## Prerequisites

- **Python 3.12+** with pip
- **Node.js 22+** + pnpm (for frontend)
- Linux system with systemd (for full telemetry/power features)

## Installation

### 1. Clone

```bash
git clone https://github.com/mochapulse/nexus-API.git
cd nexus-API
```

### 2. Backend (Python API)

**Option A — automated install script:**

```bash
chmod +x cmd/install.sh
./cmd/install.sh
```

This installs system packages (`python3-full`, build tools), creates a virtual
environment in `venv/`, and installs all Python dependencies.

**Option B — manual:**

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
| Backend  | FastAPI 0.141, Uvicorn 0.52     |
| Config   | python-dotenv, pydantic-settings |
| Docs     | Sphinx 9, Furo theme, autodoc    |
| Frontend | React 19, TypeScript 6, Vite 8  |
| Linting  | ESLint 10, typescript-eslint     |
| Package  | pnpm                             |
| CI/CD    | GitHub Actions                   |
| Errors   | Sentry SDK                       |
