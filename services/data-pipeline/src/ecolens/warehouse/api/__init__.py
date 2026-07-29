"""Warehouse API package — see `api.py`'s module docstring for the full design."""

from __future__ import annotations

from ecolens.warehouse.db.connection import ConnectionPool, check_health
from ecolens.warehouse.core.api_settings import (
    WarehouseApiSettings,
    get_warehouse_api_settings,
)

from .api import app
from .app import create_app

__all__ = [
    "app",
    "create_app",
    "ConnectionPool",
    "check_health",
    "WarehouseApiSettings",
    "get_warehouse_api_settings",
]
