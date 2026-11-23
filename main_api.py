import os
from fastapi import APIRouter, FastAPI
from app.api.router import router as api_router
from app.api.v1.model_router import router as model_v1_router
from app.api.v1_1.run_certificate_public_router import router as run_cert_v1_1_router
import app.api.v1.run_limiter as _run_limiter  # noqa: F401 — initialises semaphore at process start
from app.internal_auth_introspect import router as internal_auth_router


def _parse_mount_radar_flag() -> bool:
    raw = os.environ.get("FINCO_MOUNT_RADAR", "1").strip().lower()
    if raw in ("1", "true", "yes", "on", ""):
        return True
    if raw in ("0", "false", "no", "off"):
        return False
    # Safe fail-back to default-on coexistence for unrecognized values
    return True


FINCO_MOUNT_RADAR = _parse_mount_radar_flag()

app = FastAPI(title="FINCO Model API", version="1.0.0")
app.include_router(api_router, prefix="/api/v1")
app.include_router(internal_auth_router)

if FINCO_MOUNT_RADAR:
    from app.api.v1.router import router as radar_v1_router
    from app.api.v1_1.router import router as institutional_v1_1_router
    app.include_router(radar_v1_router, prefix="/api/v1")
    app.include_router(institutional_v1_1_router, prefix="/api/v1.1")

    # EXPERIMENTAL / READ-ONLY: Model ↔ Market Bridge V1 contract spike.
    # Fail-closed evaluation over synthetic fixtures only — no mutation, no
    # Verify promotion, no production bindings.  See
    # docs/review/MODEL_MARKET_BRIDGE_V1.md.
    from app.model_market_bridge.api import router as model_market_bridge_router
    app.include_router(model_market_bridge_router, prefix="/api/v1.1")
else:
    # Preserve 100% of Model-owned v1 and v1.1 institutional routes (/supported-today,
    # /projects, /last-run, /kpis, /export, /run-certificate, etc.) while excluding
    # only Radar-owned /radar/* routes and importing zero finco_radar / finco_yield modules.
    from app.api.v1_1.router import router as _full_v1_1_router
    _model_only_v1_1 = APIRouter()
    for _route in _full_v1_1_router.routes:
        _rpath = getattr(_route, "path", "") or ""
        if _rpath.startswith("/radar/") or _rpath == "/radar":
            continue
        _model_only_v1_1.routes.append(_route)
    app.include_router(model_v1_router, prefix="/api/v1")
    app.include_router(_model_only_v1_1, prefix="/api/v1.1")
    app.include_router(run_cert_v1_1_router, prefix="/api/v1.1")


@app.get("/health")
async def health():
    return {"status": "ok", "service": "finco-model-api", "radar_mounted": FINCO_MOUNT_RADAR}
