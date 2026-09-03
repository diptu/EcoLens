"""Re-exports `router` so `from ecolens.ingestion.api import router` keeps
working unchanged now that `api.py` is a package (`api/routes.py`) rather
than a single module. Named `routes.py`, not `router.py` -- matches
`warehouse/api/routes.py`'s convention, and avoids a self-shadowing
collision: a submodule named `router.py` containing a variable also
named `router` would have this `__init__.py`'s own re-export overwrite
the package's `router` attribute (normally the submodule itself) with
the `APIRouter` instance, breaking `import ecolens.ingestion.api.router
as x`-style access to the actual module.

`data_sources_router` is deliberately a *separate* export, mounted
directly (not nested under `router`) -- `router` already carries its
own `/ingestion` prefix, and `data_sources_router` needs the bare
`/v1/data-sources` path the TODO spec calls for, not
`/ingestion/v1/data-sources`.
"""

from __future__ import annotations

from .data_sources_routes import router as data_sources_router
from .routes import router

__all__ = ["router", "data_sources_router"]
