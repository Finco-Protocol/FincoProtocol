"""Isolated FINCO-native prototype; not mounted into production app in Y0."""
from fastapi import APIRouter
from fastapi.responses import HTMLResponse
router=APIRouter(prefix="/yield",tags=["yield-spike"])

@router.get("/prototype",response_class=HTMLResponse)
def prototype()->str:
    return """<!doctype html><html><body><main><h1>ENTER POSITION <small>PROTOTYPE · NO BROADCAST</small></h1>
<p>Route: USDC → Morpho Vault</p><p>Reward-Off APY: COMPONENTS_UNAVAILABLE until source-bound components exist.</p>
<p>Receiver: connected wallet only</p><button disabled>REVIEW & SIGN — EXECUTION FLAG OFF</button>
<footer>Non-custodial · User-signed · FINCO analyses and routes — FINCO does not custody.</footer></main></body></html>"""
