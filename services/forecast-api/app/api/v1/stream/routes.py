"""`WS /v1/stream/emissions` (`README.md` § API reference: "Server-sent
stream, 5-min updates").

Pushes the latest `raw_marts.fct_carbon_intensity` row for `region` every
`Settings.stream_interval_seconds` until the client disconnects. Each
push is a fresh DB read (not a Postgres `LISTEN`/`NOTIFY` or a
change-feed) — simple and correct at this update cadence (5 minutes,
matching how often `fct_carbon_intensity` actually gets new hourly rows
from the warehouse-sync pipeline), not built to scale to a sub-second
push cadence.
"""

from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.core.config import get_settings
from app.db.session import get_session
from app.service.ml.data import load_latest_intensity
from app.core.logging import get_logger

log = get_logger(__name__)

router = APIRouter(tags=["stream"])


@router.websocket("/v1/stream/emissions")
async def stream_emissions(websocket: WebSocket) -> None:
    region = websocket.query_params.get("region")
    if not region:
        await websocket.close(code=4400, reason="'region' query parameter is required")
        return

    await websocket.accept()
    settings = get_settings()
    try:
        while True:
            async with get_session() as db:
                row = await load_latest_intensity(db, region)
            if row is not None:
                await websocket.send_text(
                    json.dumps(
                        {
                            "region": region,
                            "as_of": row["hour"].isoformat(),
                            "intensity_kgco2e_per_mwh": (
                                float(row["intensity_kgco2e_per_mwh"])
                                if row["intensity_kgco2e_per_mwh"] is not None
                                else None
                            ),
                            "factors_version": row["factors_version"],
                        }
                    )
                )
            await asyncio.sleep(settings.stream_interval_seconds)
    except WebSocketDisconnect:
        log.info("stream.client_disconnected", region=region)
