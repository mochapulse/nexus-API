"""Nexus API application entry point.

A FastAPI server that serves health, telemetry, and power-management
endpoints.  Health and telemetry are computed live; power endpoints use
JSONC response templates while DEBUG-gated.  All business routes live
under the versioned ``/api/v1`` prefix; the root and the API root redirect
to the Swagger UI at ``/docs``.  Run with::

    python -m api.main
"""

from fastapi import APIRouter, Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, Response
from fastapi.security import APIKeyHeader
from pydantic import BaseModel, Field
import asyncio
import logging
from contextlib import asynccontextmanager
import psutil
import time

from api import __version__
from api.config.paths import FAVICON_PATH, ensure_dotenv
from api.lib.templates import load_template
from api.hw.telemetry import get_system_metrics
from api.hw.power import system_poweroff, system_sleep
from api.mc import watchdog as mc_watchdog
from api.mc.watchdog import watchdog_loop
from api.net import state
from api.net.duckdns_service import duckdns_loop

ensure_dotenv()

import api.config.runtime as runtime

log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan — start and stop background services.

    On startup, launches the DuckDNS background updater as a single
    asyncio task when all three conditions are met: ``DEBUG`` is off,
    ``DUCKDNS_DOMAIN`` is set, and ``DUCKDNS_TOKEN`` is set. Also
    launches the Minecraft watchdog polling loop (:func:`watchdog_loop`)
    whenever ``DEBUG`` is off — the loop itself only probes/acts while
    the watchdog is armed via the ``/api/v1/mc-server/watchdog``
    endpoints, and it starts disarmed every boot (in-memory state). In
    ``DEBUG`` the watchdog loop is never started, matching the power
    endpoints' DEBUG-gating. On shutdown every started task is
    cancelled so the process exits cleanly.
    """
    tasks: list[asyncio.Task] = []
    if not runtime.DEBUG and runtime.DUCKDNS_DOMAIN and runtime.DUCKDNS_TOKEN:
        tasks.append(
            asyncio.create_task(
                duckdns_loop(runtime.DUCKDNS_DOMAIN, runtime.DUCKDNS_TOKEN)
            )
        )
    if not runtime.DEBUG:
        tasks.append(
            asyncio.create_task(
                watchdog_loop("localhost", runtime.MINECRAFT_PORT, runtime.MINECRAFT_SERVICE)
            )
        )
    else:
        log.info("DEBUG is on; Minecraft watchdog loop is disabled")
    yield
    for task in tasks:
        task.cancel()
    for task in tasks:
        try:
            await task
        except asyncio.CancelledError:
            pass

# Warm up CPU timers
psutil.cpu_percent(interval=None)

# Process uptime anchor (per-worker, monotonic clock)
_START_TIME = time.monotonic()

app = FastAPI(
    title=runtime.APP_NAME,
    version=__version__,
    debug=runtime.DEBUG,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

_x_api_key = APIKeyHeader(name="X-API-Key", auto_error=False)


def verify_api_key(api_key: str | None = Depends(_x_api_key)) -> None:
    """Reject requests without a valid ``X-API-Key`` header.

    Applies to every route on the versioned router (all ``/api/v1``
    endpoints).  The docs routes (``/docs``, ``/redoc``, ``/openapi.json``)
    and the app-level helpers (``/``, ``/favicon.ico``) stay public.

    When ``API_KEY`` is not configured the check fails closed in production
    (HTTP 503) and passes silently in DEBUG, so development keeps working
    out of the box.
    """
    if not runtime.API_KEY:
        if runtime.DEBUG:
            return
        raise HTTPException(status_code=503, detail="API_KEY is not configured")
    if api_key != runtime.API_KEY:
        raise HTTPException(status_code=401, detail="Invalid or missing X-API-Key")


api_v1_router = APIRouter(
    prefix="/api/v1",
    dependencies=[Depends(verify_api_key)],
)


@api_v1_router.get("/", include_in_schema=False)
def api_root():
    """Redirect to the Swagger UI (``/docs``)."""
    return RedirectResponse("/docs", status_code=307)


@api_v1_router.get("/health")
def get_health(response: Response):
    """Liveness probe — confirms the process is alive and serving.

    Dependency-free by design: no hardware, database, or external calls,
    so a dependency blip can never cascade into a false "dead" verdict.
    Returns 200 with the service version, process uptime, and timestamp.
    The response is marked ``Cache-Control: no-store`` so load balancers
    and proxies never serve a stale "ok".
    """
    response.headers["Cache-Control"] = "no-store"
    return {
        "status": "ok",
        "version": __version__,
        "uptime_seconds": int(time.monotonic() - _START_TIME),
        "timestamp": int(time.time()),
        "last_duckdns_update_ms": state.last_duckdns_update_ms,
        "connectivity_delay_ms": state.connectivity_delay_ms,
    }


@api_v1_router.post("/power/poweroff")
def post_poweroff():
    """Power off the host system.

    On success the response is ``{"poweroff_triggered": "true"}``.
    When ``DEBUG`` is enabled, the real command is skipped and a stub
    template is returned instead, so the machine cannot be shut down
    accidentally during development.
    """
    if runtime.DEBUG:
        return load_template("post-poweroff")
    error = system_poweroff()
    if error:
        return JSONResponse(status_code=500, content={"status": "error", "detail": error})
    return {"poweroff_triggered": "true"}


@api_v1_router.post("/power/sleep")
def post_sleep():
    """Put the host system into S3 (suspend-to-RAM) sleep.

    On success the response is ``{"sleep_triggered": "true"}``.
    When ``DEBUG`` is enabled, the real command is skipped and a stub
    template is returned instead, so the machine cannot be suspended
    accidentally during development.
    """
    if runtime.DEBUG:
        return load_template("post-sleep")
    error = system_sleep()
    if error:
        return JSONResponse(status_code=500, content={"status": "error", "detail": error})
    return {"sleep_triggered": "true"}


class WatchdogArmRequest(BaseModel):
    """Body for ``POST /api/v1/mc-server/watchdog``.

    ``active_seconds`` is how long the watchdog stays armed (capped at
    one week). ``threshold_seconds`` is how long Minecraft must be
    reachable with zero players before the watchdog powers off the
    host, defaulting to :data:`~api.mc.watchdog.DEFAULT_THRESHOLD`
    (30 minutes) and capped at one day.
    """

    active_seconds: int = Field(gt=0, le=7 * 24 * 3600)
    threshold_seconds: int = Field(default=mc_watchdog.DEFAULT_THRESHOLD, gt=0, le=24 * 3600)


@api_v1_router.post("/mc-server/watchdog")
def post_mc_server_watchdog(body: WatchdogArmRequest):
    """Arm (or re-arm) the Minecraft server watchdog. Returns the status
    payload. ``DEBUG`` still validates the body but returns a stub
    template and never touches the watchdog state.
    """
    if runtime.DEBUG:
        return load_template("post-mc-server-watchdog")
    mc_watchdog.arm(
        mc_watchdog.STATE, time.monotonic(), body.active_seconds, body.threshold_seconds
    )
    return mc_watchdog.snapshot(mc_watchdog.STATE, time.monotonic())


@api_v1_router.delete("/mc-server/watchdog")
def delete_mc_server_watchdog():
    """Disarm the Minecraft server watchdog (idempotent). ``DEBUG``
    returns a stub template and never touches the watchdog state.
    """
    if runtime.DEBUG:
        return load_template("delete-mc-server-watchdog")
    mc_watchdog.disarm(mc_watchdog.STATE, "manual")
    return mc_watchdog.snapshot(mc_watchdog.STATE, time.monotonic())


@api_v1_router.get("/mc-server/watchdog")
def get_mc_server_watchdog():
    """Return the current watchdog status; see
    :func:`api.mc.watchdog.snapshot` for the payload shape. ``DEBUG``
    returns a stub template and never touches the watchdog state.
    """
    if runtime.DEBUG:
        return load_template("get-mc-server-watchdog")
    return mc_watchdog.snapshot(mc_watchdog.STATE, time.monotonic())


@api_v1_router.get("/telemetry")
async def get_telemetry():
    """Return live hardware telemetry (CPU, RAM, swap, GPU).

    The payload is pre-serialized by orjson in the metrics worker and
    served as raw bytes with a standard ``application/json`` media type,
    so no re-serialization occurs on the response path.
    """
    body = await get_system_metrics(pretty=True, return_bytes=True)
    return Response(content=body, media_type="application/json")


app.include_router(api_v1_router)


@app.get("/", include_in_schema=False)
def root():
    """Redirect to the Swagger UI (``/docs``)."""
    return RedirectResponse("/docs", status_code=307)


@app.get("/favicon.ico")
async def favicon():
    """Serve the Nexus favicon as an SVG."""
    return FileResponse(FAVICON_PATH, media_type="image/svg+xml")


if __name__ == "__main__":
    import uvicorn
    print(f"Listening WSL->Windows DEV on http://localhost:{runtime.PORT}")
    uvicorn.run("api.main:app", host="0.0.0.0", port=runtime.PORT, reload=runtime.DEBUG)
