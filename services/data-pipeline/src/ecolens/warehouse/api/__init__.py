"""Warehouse API package — see `api/v1/api.py`'s module docstring for the
full design.
"""

from __future__ import annotations

from ecolens.warehouse.db.connection import ConnectionPool, check_health
from ecolens.warehouse.core.api_settings import (
    WarehouseApiSettings,
    get_warehouse_api_settings,
)

from .v1.api import app
from .v1.app import create_app

__all__ = [
    "app",
    "create_app",
    "ConnectionPool",
    "check_health",
    "WarehouseApiSettings",
    "get_warehouse_api_settings",
]
