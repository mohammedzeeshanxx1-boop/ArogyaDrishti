"""Arogya Drishti API — checkpoint C1.

Endpoints:
  GET  /health
  GET  /api/v1/meta
  GET  /api/v1/status                         dependency status (HAPI FHIR, SQLite)
  POST /api/fhir/Observation                  ingest one R4 vital-sign Observation
  GET  /api/fhir/Observation?patient=&code=   observations stored in HAPI
  GET  /api/patients                          synthetic discharge cohort
  GET  /api/patients/{id}/profile             discharge profile
  GET  /api/inspector/observations/{id}       FHIR Inspector: stored resource + validation
  GET  /api/inspector/ingestions              recent ingestion events (accepted and rejected)
  WS   /ws/heartbeat
"""

from __future__ import annotations

import json
import re
from contextlib import asynccontextmanager
from datetime import datetime, timezone

import httpx
from fastapi import FastAPI, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from . import CHECKPOINT, __version__
from .config import BRAND_NAME, DISCLAIMER, TAGLINE, Settings
from .db import check_db, ingestion_events, init_db
from .fhir import FhirClient, FhirUnavailable, outcome, outcome_issue, probe_fhir, summarize_outcome
from .ingest import ingest_observation
from .patients import patient_profile, list_patients
from .vitals import INGEST_TAG, LOINC, VITALS, validate_observation

FHIR_ID = re.compile(r"^[A-Za-z0-9\-.]{1,64}$")
FHIR_JSON = "application/fhir+json"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def fhir_error(status: int, code: str, diagnostics: str, expression: str | None = None) -> JSONResponse:
    return JSONResponse(outcome([outcome_issue("error", code, diagnostics, expression)]), status_code=status, media_type=FHIR_JSON)


def create_app(
    settings: Settings | None = None,
    fhir_transport: httpx.AsyncBaseTransport | None = None,
) -> FastAPI:
    settings = settings or Settings.from_env()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        init_db(settings.sqlite_path)
        app.state.fhir = FhirClient(settings.fhir_base_url, settings.fhir_request_timeout_seconds, fhir_transport)
        yield
        await app.state.fhir.aclose()

    app = FastAPI(title=f"{BRAND_NAME} API", version=__version__, lifespan=lifespan)
    app.add_middleware(CORSMiddleware, allow_origins=list(settings.cors_origins), allow_methods=["*"], allow_headers=["*"])

    @app.exception_handler(FhirUnavailable)
    async def _fhir_down(_: Request, exc: FhirUnavailable) -> JSONResponse:
        return fhir_error(503, "transient", f"FHIR server unavailable: {exc}")

    def fhir(request: Request) -> FhirClient:
        return request.app.state.fhir

    @app.get("/health")
    async def health() -> dict:
        return {"status": "ok"}

    @app.get("/api/v1/meta")
    async def meta() -> dict:
        return {"name": BRAND_NAME, "tagline": TAGLINE, "disclaimer": DISCLAIMER, "version": __version__, "checkpoint": CHECKPOINT}

    @app.get("/api/v1/status")
    async def status() -> dict:
        probe = await probe_fhir(settings.fhir_base_url, settings.fhir_timeout_seconds, fhir_transport)
        return {
            "checkedAt": _now(),
            "checkpoint": CHECKPOINT,
            "services": {"api": {"status": "ok", "version": __version__}, "fhir": probe, "eventStore": check_db(settings.sqlite_path)},
        }

    # ------------------------------------------------------------ ingestion
    @app.post("/api/fhir/Observation", status_code=201)
    async def post_observation(request: Request) -> JSONResponse:
        raw = await request.body()
        try:
            resource = json.loads(raw)
        except ValueError:
            return fhir_error(400, "structure", "Body is not valid JSON")
        result = await ingest_observation(resource, fhir(request), settings.sqlite_path)
        headers = {"Location": result.body["location"]} if result.http_status == 201 else None
        return JSONResponse(result.body, status_code=result.http_status, headers=headers,
                            media_type=FHIR_JSON if result.body.get("resourceType") == "OperationOutcome" else None)

    @app.get("/api/fhir/Observation")
    async def search_observations(
        request: Request,
        patient: str = Query(..., description="Patient id"),
        code: str | None = Query(None, description="LOINC code, one of the supported vitals"),
        ingested_only: bool = Query(True, alias="ingestedOnly"),
        count: int = Query(50, alias="_count", ge=1, le=500),
    ):
        if not FHIR_ID.match(patient):
            return fhir_error(400, "invalid", "patient must be a FHIR id")
        if code is not None and code not in VITALS:
            return fhir_error(400, "not-supported", f"code must be one of {sorted(VITALS)}")
        params = {"subject": f"Patient/{patient}", "_sort": "-date", "_count": min(count, 200),
                  "code": f"{LOINC}|{code}" if code else ",".join(f"{LOINC}|{c}" for c in VITALS)}
        if ingested_only:
            params["_tag"] = f"{INGEST_TAG['system']}|{INGEST_TAG['code']}"
        found = await fhir(request).search("Observation", params, limit=count)
        return {"patient": f"Patient/{patient}", "count": len(found), "observations": found}

    # ------------------------------------------------------------ patients
    @app.get("/api/patients")
    async def patients(request: Request) -> dict:
        items = await list_patients(fhir(request))
        return {"count": len(items), "synthetic": True, "patients": items}

    @app.get("/api/patients/{pid}/profile")
    async def profile(pid: str, request: Request):
        if not FHIR_ID.match(pid):
            return fhir_error(400, "invalid", "patient id must be a FHIR id")
        p = await patient_profile(fhir(request), pid)
        if p is None:
            return fhir_error(404, "not-found", f"Patient/{pid} not found")
        return p

    # ------------------------------------------------------------ inspector
    @app.get("/api/inspector/observations/{oid}")
    async def inspect_observation(oid: str, request: Request):
        if not FHIR_ID.match(oid):
            return fhir_error(400, "invalid", "observation id must be a FHIR id")
        client = fhir(request)
        stored = await client.read("Observation", oid)
        if stored is None:
            return fhir_error(404, "not-found", f"Observation/{oid} not found")
        # Re-check the stored copy. The server-assigned id/meta are removed for the
        # local check because that check is written for create payloads.
        payload = {k: v for k, v in stored.items() if k not in ("id", "meta")}
        local = validate_observation(payload)
        profile_url = local.spec.profile if local.spec else None
        hapi = {"profile": profile_url, **summarize_outcome(await client.validate(stored, profile_url))} if profile_url else None
        events = ingestion_events(settings.sqlite_path, observation_id=oid)
        tags = stored.get("meta", {}).get("tag", [])
        return {
            "observation": f"Observation/{oid}",
            "versionId": stored.get("meta", {}).get("versionId"),
            "lastUpdated": stored.get("meta", {}).get("lastUpdated"),
            "declaredProfiles": stored.get("meta", {}).get("profile", []),
            "source": "api-ingest" if any(t.get("code") == INGEST_TAG["code"] for t in tags) else "other (e.g. Synthea import)",
            "vital": local.spec.key if local.spec else None,
            "validation": {
                "local": {"passed": local.ok, "issues": [i.as_fhir() for i in local.issues]},
                "hapi": hapi,
                "checkedAt": _now(),
            },
            "ingestion": events,
            "resource": stored,
        }

    @app.get("/api/inspector/ingestions")
    async def recent_ingestions(limit: int = Query(50, ge=1, le=500)) -> dict:
        events = ingestion_events(settings.sqlite_path, limit=limit)
        return {"count": len(events), "events": events}

    # ------------------------------------------------------------ websocket
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
