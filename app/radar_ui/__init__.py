"""FINCO Radar v1 UI — read-only product surfaces over canonical authorities.

The existing Stocks surface remains presentation + composition over frozen
R0-R12 authority.  Domain extensions are assembled here so the existing
``main_web`` import of :mod:`app.radar_ui.router` receives the same root
APIRouter plus isolated read-only domain routers.

No route registered here may redefine market/reference/GAP authority.
"""

# ``main_web`` already mounts ``app.radar_ui.router.router``.  Assemble domain
# extensions once at package import time instead of widening main_web or the
# frozen Radar authority namespaces.
from app.radar_ui.router import router as _root_router
from app.radar_ui.economy_router import router as _economy_router
from app.radar_ui.crypto_router import router as _crypto_router

_root_router.include_router(_economy_router)
_root_router.include_router(_crypto_router)

__all__ = []
