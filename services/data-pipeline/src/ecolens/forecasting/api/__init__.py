"""Re-exports `router` so `from ecolens.forecasting.api import router` keeps
working unchanged now that `api.py` is a package (`api/routes.py`) rather
than a single module. Named `routes.py`, not `router.py` -- same
self-shadowing reasoning as `ecolens.ingestion.api`'s `__init__.py`.
"""

from __future__ import annotations

from .routes import router

__all__ = ["router"]
