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
  main.py               App & route definitions (FastAPI instance)
  config/
    __init__.py          Package docstring
    paths.py             Resolved filesystem paths + ensure_dotenv()
    runtime.py           APP_NAME, PORT, DEBUG from dotenv
  lib/
    templates.py         load_template(name) — reads JSONC, strips comments, returns dict
cmd/
  install.sh             Bootstrap script (apt deps → venv → pip install)
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
  get-health.jsonc       Health check response stub
  post-poweroff.jsonc    Poweroff confirmation stub
  post-sleep.jsonc       Sleep confirmation stub
  post-telemetry.jsonc   Telemetry data stub (CPU, RAM, GPU, uptime)
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

## Architecture Patterns

### JSONC Template Stubs

API endpoints return static JSONC templates loaded by `api.lib.templates.load_template()`.
Comments (`//`, `/* */`) are stripped via regex before `json.loads()`.
Templates live in `templates/` and follow the naming convention `{method}-{name}.jsonc`.

To add a new endpoint:
1. Create a `templates/{method}-{name}.jsonc` file
2. Add a route in `api/main.py` calling `load_template("{method}-{name}")`
3. Add a docstring describing the endpoint

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
- No tests written yet — test framework TBD
- `.env` is gitignored; `.env.example` is committed

## Environment Variables

| Variable   | Default     | Description                  |
|------------|-------------|------------------------------|
| `APP_NAME` | `Nexus API` | App title for docs & root    |
| `PORT`     | `8000`      | Server listen port           |
| `DEBUG`    | `True`      | Hot-reload & verbose logging |

## CI/CD

Single workflow `docs.yml`:
- Triggered on push/PR to `main` when `api/**`, `docs/**`, or `requirements.txt` changes
- Builds Sphinx HTML with `-W` (warnings = errors)
- PRs: uploads artifact (7-day retention)
- Push to main: deploys to GitHub Pages via `peaceiris/actions-gh-pages`

## External Services

- **Sentry**: error monitoring via `sentry-sdk` (configured in requirements, not yet wired in code)
- **GitHub Pages**: hosts Sphinx documentation

## Implementation Status

**Nothing is implemented yet — all code is placeholder scaffolding.**

- **Frontend is void code**: `App.tsx` returns an empty fragment. `App.css` and
  `index.css` are empty files. No components, no routing, no state, no API
  calls — just a Vite + React + TypeScript skeleton.
- **API templates are hardcoded stubs**: every endpoint (`/health`,
  `/telemetry`, `/power/poweroff`, `/power/sleep`) returns static JSON loaded
  from `templates/`. No real telemetry collection, no systemd log sniffing, no
  actual power management logic exists.
- **Sentry SDK**: listed in `requirements.txt` but never imported or configured
  in application code.
- **No tests**: zero test coverage across both backend and frontend.
- **No frontend-backend integration**: Vite config has no proxy to the API.
