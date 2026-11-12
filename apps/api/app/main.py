"""Arogya Drishti API — checkpoint C1.

Endpoints:
  GET  /health
  GET  /api/v1/meta
  GET  /api/v1/status                         dependency status (HAPI FHIR, SQLite)
  POST /api/fhir/Observation                  ingest one R4 vital-sign Observation
  GET  /api/fhir/Observation?patient=&code=   observations stored in HAPI
  GET  /api/fhir/Observation/{id}             one stored Observation, read from HAPI
  GET  /api/patients                          synthetic discharge cohort
  GET  /api/patients/{id}/profile             discharge profile
  GET  /api/inspector/observations/{id}       FHIR Inspector: stored resource + validation
  GET  /api/inspector/ingestions              recent ingestion events (accepted and rejected)
  WS   /ws/heartbeat
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone

import httpx
from fastapi import FastAPI, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from . import CHECKPOINT, __version__
from .config import BRAND_NAME, DISCLAIMER, TAGLINE, Settings
from .db import check_db, ingestion_events, init_db
from .fhir import FhirClient, FhirUnavailable, outcome, outcome_issue, probe_fhir, summarize_outcome
from .ingest import ingest_observation
from .patients import patient_profile, list_patients
from . import detector, evaluation, scale2
from .risk import VITAL_LABEL, to_celsius
from .replay import store as replay_store
from .replay.engine import SPEEDS, ReplayConflict, ReplayManager
from .replay.persistence import SESSION_TAG_SYSTEM
from .replay.scenarios import SCENARIOS as REPLAY_SCENARIOS
from .simulator import DEFAULT_INTERVAL, DEFAULT_STEPS, SCENARIOS, Simulator
from .vitals import INGEST_TAG, LOINC, VITALS, validate_observation

MONITOR_LIMIT = 480   # newest Observations per monitor call: 120 per vital, enough for the detector's baseline window;
                      # stays under HAPI 5.7's 500-result paging cap (full histories use search_by_date)
FHIR_ID = re.compile(r"^[A-Za-z0-9\-.]{1,64}$")
FHIR_JSON = "application/fhir+json"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def fhir_error(status: int, code: str, diagnostics: str, expression: str | None = None) -> JSONResponse:
    return JSONResponse(outcome([outcome_issue("error", code, diagnostics, expression)]), status_code=status, media_type=FHIR_JSON)


class StartRequest(BaseModel):
    patientId: str
    scenario: str
    steps: int = Field(DEFAULT_STEPS, ge=2, le=200)
    intervalSeconds: float = Field(DEFAULT_INTERVAL, ge=0, le=60)


class PatientRequest(BaseModel):
    patientId: str


class Scale2Request(BaseModel):
    prescribedBy: str = Field(..., min_length=2, max_length=120)
    reason: str = Field(..., min_length=5, max_length=300)


class EvaluationRequest(BaseModel):
    patientId: str
    durationMinutes: int = Field(240, ge=30, le=24 * 60)
    intervalSeconds: int = Field(60, ge=15, le=600)
    scenarios: list[str] = ["stable", "deterioration", "artifact", "deterioration_artifact"]


class ReplayCreate(BaseModel):
    patientId: str
    scenario: str
    speed: str = "10x"
    seed: int | None = None
    durationMinutes: int | None = Field(None, ge=1, le=7 * 24 * 60)
    intervalSeconds: int | None = Field(None, ge=1, le=3600)
    anchor: datetime | None = None
    batchSize: int = Field(200, ge=1, le=1000)


def _z(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def create_app(
    settings: Settings | None = None,
    fhir_transport: httpx.AsyncBaseTransport | None = None,
    simulator_in_process: bool = False,
) -> FastAPI:
    settings = settings or Settings.from_env()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        init_db(settings.sqlite_path)
        app.state.fhir = FhirClient(settings.fhir_base_url, settings.fhir_request_timeout_seconds, fhir_transport)
        # The simulator posts to the real ingestion endpoint over HTTP (or in-process ASGI in tests).
        sim_transport = httpx.ASGITransport(app=app) if simulator_in_process else None
        base = "http://in-process" if simulator_in_process else settings.simulator_api_url
        app.state.sim_client = httpx.AsyncClient(base_url=base, transport=sim_transport, timeout=60)
        app.state.simulator = Simulator(app.state.sim_client)
        app.state.windows = {}  # patientId -> {"since": UTC Z, "session": replay session id or None}
        app.state.replay = ReplayManager(app.state.fhir, settings.sqlite_path,
                                         legacy_busy=lambda: app.state.simulator.state.running)
        yield
        await app.state.replay.shutdown()
        await app.state.simulator.stop()
        await app.state.sim_client.aclose()
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

    @app.get("/api/fhir/Observation/{oid}")
    async def read_observation(oid: str, request: Request):
        """The stored Observation exactly as HAPI returns it (no local copy exists)."""
        if not FHIR_ID.match(oid):
            return fhir_error(400, "invalid", "observation id must be a FHIR id")
        stored = await fhir(request).read("Observation", oid)
        if stored is None:
            return fhir_error(404, "not-found", f"Observation/{oid} not found")
        return JSONResponse(stored, media_type=FHIR_JSON)

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

    # ------------------------------------------------------------ demo: simulator + monitor
    @app.get("/api/demo/simulator")
    async def simulator_status(request: Request) -> dict:
        return request.app.state.simulator.state.public()

    @app.post("/api/demo/simulator/start")
    async def simulator_start(body: StartRequest, request: Request):
        if not FHIR_ID.match(body.patientId):
            return fhir_error(400, "invalid", "patientId must be a FHIR id")
        if body.scenario not in SCENARIOS:
            return fhir_error(400, "not-supported", f"scenario must be one of {sorted(SCENARIOS)}")
        if await fhir(request).read("Patient", body.patientId) is None:
            return fhir_error(404, "not-found", f"Patient/{body.patientId} not found")
        active = request.app.state.replay.active()
        if active:
            return fhir_error(409, "conflict", f"replay session {active.id} is {active.state}; stop it first")
        state = await request.app.state.simulator.start(body.patientId, body.scenario, body.steps, body.intervalSeconds)
        request.app.state.windows[body.patientId] = {"since": _z(datetime.fromisoformat(state["startedAt"])), "session": None}
        return state

    @app.post("/api/demo/simulator/stop")
    async def simulator_stop(request: Request) -> dict:
        return await request.app.state.simulator.stop()

    @app.post("/api/demo/reset")
    async def demo_reset(body: PatientRequest, request: Request):
        if not FHIR_ID.match(body.patientId):
            return fhir_error(400, "invalid", "patientId must be a FHIR id")
        state = await request.app.state.simulator.stop()
        request.app.state.windows[body.patientId] = {"since": _z(datetime.now(timezone.utc)), "session": None}
        return {"patientId": body.patientId, "windowStart": request.app.state.windows[body.patientId]["since"], "simulator": state}

    @app.get("/api/demo/monitor/{pid}")
    async def monitor(pid: str, request: Request, mode: str = Query("personalized", pattern="^(fixed|personalized)$")):
        """Everything the dashboard shows for one patient, computed from observations stored in HAPI."""
        if not FHIR_ID.match(pid):
            return fhir_error(400, "invalid", "patient id must be a FHIR id")
        view = request.app.state.windows.get(pid) or {"since": _z(datetime.now(timezone.utc) - timedelta(minutes=30)), "session": None}
        window = view["since"]
        params = {
            "subject": f"Patient/{pid}",
            "code": ",".join(f"{LOINC}|{c}" for c in VITALS),
            # A replay view shows only that session's Observations (measurement times may overlap other runs).
            "_tag": f"{SESSION_TAG_SYSTEM}|{view['session']}" if view["session"] else f"{INGEST_TAG['system']}|{INGEST_TAG['code']}",
            # Never show readings timestamped in the future (they cannot be real measurements;
            # the ingestion endpoint already rejects them, but HAPI may hold data written by other clients).
            "date": [f"ge{window}", f"le{_z(datetime.now(timezone.utc) + timedelta(minutes=5))}"],
            "_sort": "-date",   # newest first, so long sessions show their latest readings
            "_count": 200,
        }
        stored = await fhir(request).search("Observation", params, limit=MONITOR_LIMIT)
        readings, vitals = [], {k: {"label": l, "unit": u, "series": [], "latest": None} for k, (l, u) in VITAL_LABEL.items()}
        for o in stored:
            code = next((c["code"] for c in o.get("code", {}).get("coding", []) if c.get("system") == LOINC and c.get("code") in VITALS), None)
            q = o.get("valueQuantity") or {}
            if code is None or "value" not in q:
                continue
            key = VITALS[code].key
            value = to_celsius(float(q["value"]), q.get("code", "")) if key == "body_temperature" else float(q["value"])
            point = {"effective": o["effectiveDateTime"], "value": value, "observation": f"Observation/{o['id']}"}
            readings.append({"vital": key, **point})
            vitals[key]["series"].append(point)
        for v in vitals.values():
            v["series"].sort(key=lambda p: (p["effective"], p["observation"]))
            v["latest"] = v["series"][-1] if v["series"] else None
        latest = max(stored, key=lambda o: (o.get("meta", {}).get("lastUpdated", ""), o["id"]), default=None)
        proof = None
        if latest:
            ev = ingestion_events(settings.sqlite_path, observation_id=latest["id"])
            proof = {
                "observation": f"Observation/{latest['id']}",
                "id": latest["id"],
                "versionId": latest.get("meta", {}).get("versionId"),
                "lastUpdated": latest.get("meta", {}).get("lastUpdated"),
                "hapiUrl": f"{settings.fhir_base_url}/Observation/{latest['id']}",
                "readBackMatches": ev[0]["read_back_matches"] if ev else None,
                "hapiValidationErrors": (ev[0].get("hapiValidation") or {}).get("errors") if ev else None,
                "replay": None,
            }
            rep = replay_store.event_by_observation(settings.sqlite_path, latest["id"]) if not ev else None
            if rep:
                proof["replay"] = {
                    "sessionId": rep["session_id"], "seq": rep["seq"], "batch": rep["batch_no"],
                    "persistStatus": rep["persist_status"], "measuredAt": rep["measured_at"], "ingestedAt": rep["ingested_at"],
                    "validation": "local strict validation" + ("; HAPI $validate (first of this vital in the session)" if rep["hapi_shape_validated"] else
                                                              "; HAPI $validate done once per vital per session"),
                }
        s2 = await scale2.status(fhir(request), pid)
        sim = request.app.state.simulator.state.public()
        rs = request.app.state.replay.get(view["session"]) if view["session"] else None
        return {
            "replay": rs.public() if rs else None,
            "patientId": pid,
            "windowStart": window,
            "evaluatedAt": _now(),
            "observationCount": len(readings),
            "truncated": len(stored) >= MONITOR_LIMIT,
            "vitals": vitals,
            "risk": detector.evaluate(readings, mode=mode, scale2=s2["eligible"]),
            "scale2": s2,
            "fhirProof": proof,
            "simulator": sim if sim["patientId"] == pid else None,
        }

    # ------------------------------------------------------------ SpO2 Scale 2 (FHIR Flag)
    @app.get("/api/patients/{pid}/scale2")
    async def scale2_get(pid: str, request: Request):
        if not FHIR_ID.match(pid):
            return fhir_error(400, "invalid", "patient id must be a FHIR id")
        return await scale2.status(fhir(request), pid)

    @app.post("/api/patients/{pid}/scale2")
    async def scale2_set(pid: str, body: Scale2Request, request: Request):
        if not FHIR_ID.match(pid):
            return fhir_error(400, "invalid", "patient id must be a FHIR id")
        if await fhir(request).read("Patient", pid) is None:
            return fhir_error(404, "not-found", f"Patient/{pid} not found")
        try:
            return await scale2.set_flag(fhir(request), pid, body.prescribedBy, body.reason)
        except ValueError as exc:
            return fhir_error(502, "exception", str(exc))

    @app.delete("/api/patients/{pid}/scale2")
    async def scale2_clear(pid: str, request: Request):
        if not FHIR_ID.match(pid):
            return fhir_error(400, "invalid", "patient id must be a FHIR id")
        return await scale2.clear_flag(fhir(request), pid)

    # ------------------------------------------------------------ evaluation
    @app.post("/api/evaluation/run")
    async def evaluation_run(body: EvaluationRequest, request: Request):
        """Replay each scenario in batch mode, then evaluate fixed vs personalized on what HAPI stored."""
        mgr = request.app.state.replay
        if mgr.active():
            return fhir_error(409, "conflict", "a replay session is active; stop it first")
        if await fhir(request).read("Patient", body.patientId) is None:
            return fhir_error(404, "not-found", f"Patient/{body.patientId} not found")
        # Evaluation data is anchored 3 days back so it never overlaps live monitoring windows.
        anchor = (datetime.now(timezone.utc) - timedelta(days=3, minutes=body.durationMinutes)).replace(second=0, microsecond=0)
        s2 = (await scale2.status(fhir(request), body.patientId))["eligible"]
        results = []
        for sc in body.scenarios:
            try:
                s = await mgr.create(body.patientId, sc, None, anchor, body.durationMinutes, body.intervalSeconds, "batch", 400)
            except ValueError as exc:
                return _replay_error(exc)
            await mgr.start(s.id)
            await s.wait()
            if s.state != "completed":
                return fhir_error(502, "exception", f"replay of {sc} did not complete: {s.last_error}")
            try:
                result = await evaluation.evaluate_session(fhir(request), settings.sqlite_path, s.id, s2)
            except RuntimeError as exc:
                return fhir_error(502, "incomplete", str(exc))
            results.append({"scenario": sc, "scenarioName": REPLAY_SCENARIOS[sc].name, "seed": s.params["seed"],
                            "fingerprint": s.fingerprint, **result})
        report = {
            "generatedAt": _now(), "patientId": body.patientId, "durationMinutes": body.durationMinutes,
            "intervalSeconds": body.intervalSeconds, "spo2Scale": 2 if s2 else 1, "dataSource": "simulated (seeded scenarios)",
            "detectorLabel": detector.LABEL, "definitions": evaluation.__doc__, "scenarios": results,
        }
        out = Path(settings.sqlite_path).parent / "reports"
        out.mkdir(parents=True, exist_ok=True)
        (out / "evaluation-latest.json").write_text(json.dumps(report, indent=2, default=str))
        request.app.state.latest_report = report
        return JSONResponse(json.loads(json.dumps(report, default=str)))

    @app.get("/api/evaluation/latest")
    async def evaluation_latest(request: Request):
        rep = getattr(request.app.state, "latest_report", None)
        if rep is None:
            p = Path(settings.sqlite_path).parent / "reports" / "evaluation-latest.json"
            if not p.exists():
                return fhir_error(404, "not-found", "no evaluation has been run yet")
            return JSONResponse(json.loads(p.read_text()))
        return JSONResponse(json.loads(json.dumps(rep, default=str)))

    # ------------------------------------------------------------ replay engine
    def _replay_error(exc: Exception) -> JSONResponse:
        if isinstance(exc, ReplayConflict):
            return fhir_error(409, "conflict", str(exc))
        if isinstance(exc, KeyError):
            return fhir_error(404, "not-found", f"replay session {exc.args[0]} not found")
        return fhir_error(400, "invalid", str(exc))

    def _show(request: Request, s) -> dict:
        request.app.state.windows[s.patient_id] = {"since": _z(s.anchor), "session": s.id}
        return s.public()

    @app.get("/api/replay/scenarios")
    async def replay_scenarios() -> dict:
        return {"scenarios": [s.public() for s in REPLAY_SCENARIOS.values()], "speeds": list(SPEEDS)}

    @app.get("/api/replay/sessions")
    async def replay_sessions(request: Request) -> dict:
        mgr = request.app.state.replay
        active = mgr.active()
        return {"active": active.id if active else None, "sessions": [s.public() for s in mgr.sessions.values()]}

    @app.post("/api/replay/sessions", status_code=201)
    async def replay_create(body: ReplayCreate, request: Request):
        if not FHIR_ID.match(body.patientId):
            return fhir_error(400, "invalid", "patientId must be a FHIR id")
        if body.speed not in SPEEDS:
            return fhir_error(400, "invalid", f"speed must be one of {list(SPEEDS)}")
        if await fhir(request).read("Patient", body.patientId) is None:
            return fhir_error(404, "not-found", f"Patient/{body.patientId} not found")
        anchor = body.anchor.astimezone(timezone.utc) if body.anchor else None
        try:
            s = await request.app.state.replay.create(body.patientId, body.scenario, body.seed, anchor,
                                                      body.durationMinutes, body.intervalSeconds, body.speed, body.batchSize)
        except ValueError as exc:
            return _replay_error(exc)
        last = s.events[-1].measured_at if s.events else s.anchor
        if last > datetime.now(timezone.utc) + timedelta(minutes=5):
            return fhir_error(400, "invalid", "anchor + duration ends in the future; measurement times must not be in the future")
        return _show(request, s)

    @app.get("/api/replay/sessions/{sid}")
    async def replay_get(sid: str, request: Request):
        s = request.app.state.replay.get(sid)
        return s.public() if s else _replay_error(KeyError(sid))

    @app.post("/api/replay/sessions/{sid}/{action}")
    async def replay_action(sid: str, action: str, request: Request, wait: bool = False):
        mgr = request.app.state.replay
        try:
            if action == "start":
                s = await mgr.start(sid)
                if wait:
                    await s.wait()
            elif action == "reset":
                s = await mgr.reset(sid)
            elif action in ("pause", "resume", "stop"):
                s = mgr._require(sid)
                if action == "resume" and s.state == "error":
                    other = mgr.active()
                    if other and other.id != s.id:
                        raise ReplayConflict(f"replay session {other.id} is {other.state}; stop it first")
                await getattr(s, action)()
                if action == "resume" and wait:
                    await s.wait()
            else:
                return fhir_error(404, "not-found", f"unknown action {action!r}")
        except (ReplayConflict, KeyError, ValueError) as exc:
            return _replay_error(exc)
        return _show(request, s)

    @app.get("/api/replay/sessions/{sid}/persistence")
    async def replay_persistence(sid: str, request: Request):
        """What HAPI has confirmed for this session, cross-checked against HAPI itself."""
        s = request.app.state.replay.get(sid)
        if s is None:
            return _replay_error(KeyError(sid))
        hapi_count = await fhir(request).count("Observation", {"_tag": f"{SESSION_TAG_SYSTEM}|{sid}"})
        events = replay_store.event_rows(settings.sqlite_path, sid)
        return {
            "sessionId": sid,
            "eventsTotal": len(s.events),
            "confirmedByHapi": s.created + s.existing,
            "hapiCountForSessionTag": hapi_count,
            # consistent: HAPI, the engine and the event log agree; complete: every event is confirmed
            "consistent": hapi_count == s.created + s.existing == len(events),
            "complete": s.created + s.existing == len(s.events) and hapi_count == len(s.events),
            "batches": replay_store.batch_rows(settings.sqlite_path, sid),
            "sample": events[:3] + events[-1:] if events else [],
        }

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
