"""FINCO Radar v1 UI — read-only product surfaces over canonical authorities.

The existing Stocks surface remains presentation + composition over frozen
R0-R12 authority.  Domain extensions are assembled here so the existing
``main_web`` import of :mod:`app.radar_ui.router` receives the same root
APIRouter plus isolated read-only domain routers.

No route registered here may redefine market/reference/GAP authority.
"""

from app.radar_ui.r_live_router import router as _r_live_router
from app.radar_ui.router import router as _root_router
from app.radar_ui.economy_router import router as _economy_router
from app.radar_ui.crypto_router import router as _crypto_router
from app.radar_ui.stablecoin_router import router as _stablecoin_router
from app.radar_ui.derivatives_router import router as _derivatives_router
from app.radar_ui.rwa_router import router as _rwa_router
from app.radar_ui.tokenized_router import router as _tokenized_router

# R-LIVE router registered first so /radar redirect takes priority over sub-routers.
_root_router.include_router(_r_live_router)
_root_router.include_router(_economy_router)
_root_router.include_router(_crypto_router)
_root_router.include_router(_stablecoin_router)
_root_router.include_router(_derivatives_router)
_root_router.include_router(_rwa_router)
_root_router.include_router(_tokenized_router)

__all__ = []
