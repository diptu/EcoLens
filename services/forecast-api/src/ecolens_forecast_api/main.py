"""ASGI entrypoint: `uvicorn ecolens_forecast_api.main:app`."""

from __future__ import annotations

from .app import create_app

app = create_app()
