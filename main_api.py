from fastapi import FastAPI
from app.api.router import router as api_router
from app.api.v1.router import router as radar_v1_router
from app.api.v1_1.router import router as institutional_v1_1_router
import app.api.v1.run_limiter as _run_limiter  # noqa: F401 — initialises semaphore at process start

app = FastAPI(title="FINCO Model API", version="1.0.0")
app.include_router(api_router, prefix="/api/v1")
app.include_router(radar_v1_router, prefix="/api/v1")
app.include_router(institutional_v1_1_router, prefix="/api/v1.1")

# EXPERIMENTAL / READ-ONLY: Model ↔ Market Bridge V1 contract spike.
# Fail-closed evaluation over synthetic fixtures only — no mutation, no
# Verify promotion, no production bindings.  See
# docs/review/MODEL_MARKET_BRIDGE_V1.md.
from app.model_market_bridge.api import router as model_market_bridge_router
app.include_router(model_market_bridge_router, prefix="/api/v1.1")


@app.get("/health")
async def health():
    return {"status": "ok", "service": "finco-model-api"}
