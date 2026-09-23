from fastapi import FastAPI
from app.api.router import router as api_router
from app.api.v1.router import router as radar_v1_router

app = FastAPI(title="FINCO Model API", version="1.0.0")
app.include_router(api_router, prefix="/api/v1")
app.include_router(radar_v1_router, prefix="/api/v1")


@app.get("/health")
async def health():
    return {"status": "ok", "service": "finco-model-api"}