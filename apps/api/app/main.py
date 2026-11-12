"""Arogya Drishti API — checkpoint C0 (scaffold and service startup only).

No clinical logic lives here yet. Endpoints:
  GET /health            liveness
  GET /api/v1/meta       brand, disclaimer, checkpoint
  GET /api/v1/status     dependency status (HAPI FHIR, SQLite event store)
  WS  /ws/heartbeat      WebSocket transport check (hello + ping/pong)
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime, timezone

import httpx
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from . import CHECKPOINT, __version__
from .config import BRAND_NAME, DISCLAIMER, TAGLINE, Settings
from .db import check_db, init_db
from .fhir import probe_fhir


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def create_app(
    settings: Settings | None = None,
    fhir_transport: httpx.AsyncBaseTransport | None = None,
) -> FastAPI:
    settings = settings or Settings.from_env()

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        init_db(settings.sqlite_path)
        yield

    app = FastAPI(title=f"{BRAND_NAME} API", version=__version__, lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.cors_origins),
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/health")
    async def health() -> dict:
        return {"status": "ok"}

    @app.get("/api/v1/meta")
    async def meta() -> dict:
        return {
            "name": BRAND_NAME,
            "tagline": TAGLINE,
            "disclaimer": DISCLAIMER,
            "version": __version__,
            "checkpoint": CHECKPOINT,
        }

    @app.get("/api/v1/status")
    async def status() -> dict:
        fhir = await probe_fhir(settings.fhir_base_url, settings.fhir_timeout_seconds, fhir_transport)
        store = check_db(settings.sqlite_path)
        return {
            "checkedAt": _now(),
            "checkpoint": CHECKPOINT,
            "services": {
                "api": {"status": "ok", "version": __version__},
                "fhir": fhir,
                "eventStore": store,
            },
        }

    @app.websocket("/ws/heartbeat")
    async def heartbeat(ws: WebSocket) -> None:
        await ws.accept()
        await ws.send_json({"type": "hello", "checkpoint": CHECKPOINT, "serverTime": _now()})
        try:
            while True:
                msg = await ws.receive_text()
                if msg == "ping":
                    await ws.send_json({"type": "pong", "serverTime": _now()})
                else:
                    await ws.send_json({"type": "error", "detail": "unsupported message"})
        except WebSocketDisconnect:
            return

    return app


app = create_app()
