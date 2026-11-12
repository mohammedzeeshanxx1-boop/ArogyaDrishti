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

import asyncio
import json
import re
import secrets
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
from . import auth, detector, evaluation, monitoring, scale2
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


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=200)


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


def window_since(app_, pid: str) -> datetime | None:
    """Start of the current-run view for a patient (set by simulator start / reset / replay), or None."""
    w = getattr(app_.state, "windows", {}).get(pid)
    return datetime.fromisoformat(w["since"].replace("Z", "+00:00")) if w and not w.get("session") else None


def overview_cache_clear(app_) -> None:
    app_.state.overview_cache = None


def _z(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def create_app(
    settings: Settings | None = None,
    fhir_transport: httpx.AsyncBaseTransport | None = None,
    simulator_in_process: bool = False,
) -> FastAPI:
    settings = settings or Settings.from_env()
    internal_token = secrets.token_urlsafe(32)   # lets the in-process simulator post observations; never leaves this process
    throttle = auth.LoginThrottle()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        init_db(settings.sqlite_path)
        auth.init(settings.sqlite_path)
        app.state.fhir = FhirClient(settings.fhir_base_url, settings.fhir_request_timeout_seconds, fhir_transport)
        # The simulator posts to the real ingestion endpoint over HTTP (or in-process ASGI in tests).
        sim_transport = httpx.ASGITransport(app=app) if simulator_in_process else None
        base = "http://in-process" if simulator_in_process else settings.simulator_api_url
        app.state.sim_client = httpx.AsyncClient(base_url=base, transport=sim_transport, timeout=60,
                                                 headers={auth.INTERNAL_HEADER: internal_token})
        app.state.simulator = Simulator(app.state.sim_client)
        app.state.windows = {}  # patientId -> {"since": UTC Z, "session": replay session id or None}
        monitoring.init(settings.sqlite_path)
        app.state.assessor = monitoring.Assessor(app.state.fhir, settings.sqlite_path, since_for=lambda pid: window_since(app, pid))
        async def _warm():
            try:
                await cached_patients(app)
            except Exception:
                pass   # HAPI may still be starting; the first request will load it
        app.state.warmup = asyncio.create_task(_warm())
        app.state.replay = ReplayManager(app.state.fhir, settings.sqlite_path,
                                         legacy_busy=lambda: app.state.simulator.state.running,
                                         on_batch=app.state.assessor.request)
        yield
        await app.state.replay.shutdown()
        await app.state.assessor.idle()
        await app.state.simulator.stop()
        await app.state.sim_client.aclose()
        await app.state.fhir.aclose()

    app = FastAPI(title=f"{BRAND_NAME} API", version=__version__, lifespan=lifespan)
    app.add_middleware(CORSMiddleware, allow_origins=list(settings.cors_origins), allow_methods=["*"], allow_headers=["*"],
                       allow_credentials=True)
    app.add_middleware(auth.AuthMiddleware, db_path=settings.sqlite_path, internal_token=internal_token, enabled=settings.auth_required)

    @app.exception_handler(FhirUnavailable)
    async def _fhir_down(_: Request, exc: FhirUnavailable) -> JSONResponse:
        return fhir_error(503, "transient", f"FHIR server unavailable: {exc}")

    def fhir(request: Request) -> FhirClient:
        return request.app.state.fhir

    @app.get("/health")
    async def health() -> dict:
        return {"status": "ok"}

    # ------------------------------------------------------------ authentication
    @app.post("/api/auth/login")
    async def login(body: LoginRequest):
        username = body.username.strip().lower()
        if throttle.blocked(username):
            return fhir_error(429, "throttled", "Too many failed sign-in attempts. Try again in a few minutes.")
        user = await asyncio.to_thread(auth.authenticate, settings.sqlite_path, username, body.password)
        if user is None:
            throttle.fail(username)
            return fhir_error(401, "login", "Incorrect username or password.")
        throttle.clear(username)
        token = auth.create_session(settings.sqlite_path, user["username"])
        resp = JSONResponse({"user": user, "authRequired": settings.auth_required})
        resp.set_cookie(auth.SESSION_COOKIE, token, max_age=auth.SESSION_SECONDS, httponly=True, samesite="strict",
                        secure=settings.cookie_secure, path="/")
        return resp

    @app.post("/api/auth/logout")
    async def logout(request: Request):
        auth.delete_session(settings.sqlite_path, request.cookies.get(auth.SESSION_COOKIE))
        resp = JSONResponse({"signedOut": True})
        resp.delete_cookie(auth.SESSION_COOKIE, path="/")
        return resp

    @app.get("/api/auth/me")
    async def me(request: Request):
        if not settings.auth_required:
            return {"authRequired": False,
                    "user": {"username": "local", "role": "doctor", "patientId": None, "displayName": "Local (sign-in disabled)"}}
        user = auth.session_user(settings.sqlite_path, request.cookies.get(auth.SESSION_COOKIE))
        return {"authRequired": True, "user": user}   # user is null when not signed in

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
        if result.http_status == 201 and str(result.body.get("subject", "")).startswith("Patient/"):
            request.app.state.assessor.request(result.body["subject"].split("/", 1)[1])   # monitoring workflow
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
    async def patients(request: Request, refresh: bool = False) -> dict:
        return await cached_patients(request.app, refresh)

    async def cached_patients(app_: FastAPI, refresh: bool = False) -> dict:
        # The cohort changes only when seed.sh runs; cache the 8x3 HAPI queries for 10 min (?refresh=true to force).
        hit = getattr(app_.state, "patients_cache", None)
        if hit and not refresh and (datetime.now(timezone.utc) - hit[0]).total_seconds() < 600:
            return hit[1]
        items = await list_patients(app_.state.fhir)
        body = {"count": len(items), "synthetic": True, "patients": items}
        app_.state.patients_cache = (datetime.now(timezone.utc), body)
        return body

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
        monitoring.reset_state(settings.sqlite_path, body.patientId)
        overview_cache_clear(request.app)
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
        monitoring.reset_state(settings.sqlite_path, body.patientId)
        overview_cache_clear(request.app)
        return {"patientId": body.patientId, "windowStart": request.app.state.windows[body.patientId]["since"], "simulator": state}

    async def build_monitor(app_: FastAPI, pid: str, mode: str) -> dict:
        """Everything the dashboard shows for one patient, computed from observations stored in HAPI."""
        view = app_.state.windows.get(pid) or {"since": _z(datetime.now(timezone.utc) - timedelta(minutes=monitoring.RECENT_MINUTES)), "session": None}
        window = view["since"]
        if not view["session"]:   # a current-run view narrows the recent window; it never shows readings older than it
            window = max(window, _z(datetime.now(timezone.utc) - timedelta(minutes=monitoring.RECENT_MINUTES)))
        params = {
            "subject": f"Patient/{pid}",
            # A replay view shows only that session's Observations (measurement times may overlap other runs).
            # The live view filters the ingestion tag and LOINC codes in Python (much faster on HAPI 5.7/H2).
            **({"_tag": f"{SESSION_TAG_SYSTEM}|{view['session']}"} if view["session"] else {}),
            # Never show readings timestamped in the future (they cannot be real measurements;
            # the ingestion endpoint already rejects them, but HAPI may hold data written by other clients).
            "date": [f"ge{window}", f"le{_z(datetime.now(timezone.utc) + timedelta(minutes=5))}"],
            "_sort": "-date",   # newest first, so long sessions show their latest readings
            "_count": 200,
        }
        stored = await app_.state.fhir.search("Observation", params, limit=MONITOR_LIMIT * (1 if view["session"] else 2))
        if not view["session"]:
            stored = [o for o in stored if monitoring.is_ingested(o)][:MONITOR_LIMIT]
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
        s2 = await scale2.cached_status(app_.state.fhir, pid)
        risk = detector.evaluate(readings, mode=mode, scale2=s2["eligible"])
        sim = app_.state.simulator.state.public()
        rs = app_.state.replay.get(view["session"]) if view["session"] else None
        return {
            "replay": rs.public() if rs else None,
            "patientId": pid,
            "windowStart": window,
            "evaluatedAt": _now(),
            "observationCount": len(readings),
            "truncated": len(stored) >= MONITOR_LIMIT,
            "vitals": vitals,
            "risk": risk,
            "assessment": monitoring.summarize(readings, risk, datetime.now(timezone.utc)),
            "scale2": s2,
            "fhirProof": proof,
            "simulator": sim if sim["patientId"] == pid else None,
        }

    @app.get("/api/demo/monitor/{pid}")
    async def monitor(pid: str, request: Request, mode: str = Query("personalized", pattern="^(fixed|personalized)$")):
        if not FHIR_ID.match(pid):
            return fhir_error(400, "invalid", "patient id must be a FHIR id")
        return await build_monitor(request.app, pid, mode)

    @app.websocket("/ws/monitor/{pid}")
    async def monitor_ws(ws: WebSocket, pid: str, mode: str = "personalized", interval: float = 1.5):
        """Pushes the same payload as GET /api/demo/monitor/{pid} every `interval` seconds."""
        await ws.accept()
        if not FHIR_ID.match(pid) or mode not in ("fixed", "personalized"):
            await ws.send_json({"type": "error", "detail": "invalid patient id or mode"})
            await ws.close()
            return
        interval = min(max(interval, 0.5), 30.0)
        seq = 0
        try:
            while True:
                try:
                    data = await build_monitor(ws.app, pid, mode)
                    seq += 1
                    await ws.send_json({"type": "monitor", "seq": seq, "data": json.loads(json.dumps(data, default=str))})
                except FhirUnavailable as exc:
                    await ws.send_json({"type": "error", "detail": f"FHIR server unavailable: {exc}"})
                await asyncio.sleep(interval)
        except (WebSocketDisconnect, RuntimeError):
            return

    # ------------------------------------------------------------ clinical views
    @app.get("/api/clinical/overview")
    async def clinical_overview(request: Request) -> dict:
        """Every discharged patient with current monitoring status, computed from recent HAPI data (no state change)."""
        hit = getattr(request.app.state, "overview_cache", None)
        now = datetime.now(timezone.utc)
        if hit and (now - hit[0]).total_seconds() < 5:
            return hit[1]
        pts = (await cached_patients(request.app))["patients"]
        sem = asyncio.Semaphore(4)

        async def one(p):
            async with sem:
                try:
                    a = await monitoring.assess(fhir(request), settings.sqlite_path, p["id"], record=False, now=now, since=window_since(request.app, p["id"]))
                except FhirUnavailable as exc:
                    a = {"assessable": False, "level": None, "monitoringStatus": "unavailable", "error": str(exc), "latest": {}}
                return {**p, "monitoring": a}

        body = {"generatedAt": now.isoformat(), "recentWindowMinutes": monitoring.RECENT_MINUTES,
                "staleAfterMinutes": monitoring.STALE_MINUTES, "patients": list(await asyncio.gather(*(one(p) for p in pts)))}
        request.app.state.overview_cache = (now, body)
        return body

    @app.get("/api/alerts")
    async def alerts(request: Request, patient: str | None = None, limit: int = Query(50, ge=1, le=500)):
        if patient is not None and not FHIR_ID.match(patient):
            return fhir_error(400, "invalid", "patient must be a FHIR id")
        return {"alerts": monitoring.alert_events(settings.sqlite_path, patient, limit),
                "note": "Recorded when the assessed risk level changes. No acknowledgement workflow exists."}

    @app.get("/api/monitoring/status")
    async def monitoring_status(request: Request) -> dict:
        """Which observation sources are delivering data. Never claims a physical device is connected."""
        with replay_store.connect(settings.sqlite_path) as c:
            last_ing = c.execute("SELECT received_at, observation_id FROM ingestion_events WHERE outcome = 'accepted' ORDER BY id DESC LIMIT 1").fetchone()
            last_rep = c.execute("SELECT MAX(ingested_at) AS t FROM replay_events").fetchone()
        times = [t for t in ((last_ing or {}) and last_ing["received_at"], last_rep["t"] if last_rep else None) if t]
        last = max(times) if times else None
        label = None
        if last_ing and last_ing["observation_id"]:
            cache = getattr(request.app.state, "source_label", {})
            if last_ing["observation_id"] not in cache:
                try:
                    o = await fhir(request).read("Observation", last_ing["observation_id"])
                    cache[last_ing["observation_id"]] = ((o or {}).get("device") or {}).get("display")
                except FhirUnavailable:
                    cache[last_ing["observation_id"]] = None
                request.app.state.source_label = cache
            label = cache.get(last_ing["observation_id"])
        age = (datetime.now(timezone.utc) - datetime.fromisoformat(last)).total_seconds() if last else None
        sim = request.app.state.simulator.state
        rep = request.app.state.replay.active()
        return {
            "status": "receiving" if age is not None and age <= 120 else ("idle" if last else "none"),
            "lastIngestionAt": last,
            "secondsSinceLastIngestion": round(age, 1) if age is not None else None,
            "latestSourceLabel": label,
            "simulatedSourcesRunning": [s for s in (
                f"Simulated wearable (development) for Patient/{sim.patient_id}" if sim.running else None,
                f"Replay (development) for Patient/{rep.patient_id}" if rep else None) if s],
            "physicalDevicesConnected": 0,
            "assessments": request.app.state.assessor.assessments,
            "lastAssessmentError": request.app.state.assessor.last_error,
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

    @app.get("/api/evidence")
    async def evidence(request: Request) -> dict:
        """Judge Evidence Console: every status below is computed now from HAPI, SQLite and saved reports."""
        client = fhir(request)
        reports = Path(settings.sqlite_path).parent / "reports"
        def load(name):
            p = reports / name
            return json.loads(p.read_text()) if p.exists() else None
        evalr, acc = load("evaluation-latest.json"), load("acceptance-latest.json")
        probe = await probe_fhir(settings.fhir_base_url, settings.fhir_timeout_seconds, fhir_transport)
        hapi_ok = probe.get("status") == "ok" and probe.get("isR4")
        ingested = await client.count("Observation", {"_tag": f"{INGEST_TAG['system']}|{INGEST_TAG['code']}"}) if hapi_ok else 0
        pts = await list_patients(client) if hapi_ok else []
        events = ingestion_events(settings.sqlite_path, limit=200)
        accepted = [e for e in events if e["outcome"] == "accepted"]
        with replay_store.connect(settings.sqlite_path) as c:
            sessions = c.execute("SELECT COUNT(*), COALESCE(SUM(events_created + events_existing), 0) FROM replay_sessions WHERE state = 'completed'").fetchone()
        bidmc_dir = Path(__file__).resolve().parents[3] / "services" / "bidmc" / "data"
        bidmc_files = sorted(p.name for p in bidmc_dir.glob("*.csv")) if bidmc_dir.exists() else []
        sc = {s["scenario"]: s for s in (evalr or {}).get("scenarios", [])}
        art = sc.get("artifact", {}).get("modes", {})
        det = sc.get("deterioration", {}).get("modes", {})

        def item(rid, name, status, evidence, how):
            return {"id": rid, "requirement": name, "status": status, "evidence": evidence, "verify": how}

        reqs = [
            item(1, "FHIR R4 Vital Signs ingestion and HAPI storage",
                 "PASS" if hapi_ok and ingested and accepted else ("BLOCKED" if not hapi_ok else "FAIL"),
                 [f"HAPI {probe.get('software')} FHIR {probe.get('fhirVersion')}", f"{ingested} ingested Observations stored in HAPI",
                  f"{len(accepted)} recent accepted ingestions, HAPI $validate errors: {sum((e.get('hapiValidation') or {}).get('errors', 0) for e in accepted)}"],
                 "GET /api/fhir/Observation/{id}; GET /api/inspector/ingestions"),
            item(2, "Virtual wearable simulator and real BIDMC replay",
                 "PASS" if bidmc_files and sessions[0] else "PARTIAL",
                 [f"{sessions[0]} completed replay sessions, {sessions[1]} Observations confirmed by HAPI",
                  f"BIDMC files: {len(bidmc_files)}" + ("" if bidmc_files else " (BLOCKED: no PhysioNet BIDMC CSVs in services/bidmc/data)")],
                 "POST /api/replay/sessions; services/bidmc/data"),
            item(3, "At least 5 Synthea discharge profiles with conditions and medications",
                 "PASS" if len(pts) >= 5 and all(p["activeConditions"] and p["activeMedications"] for p in pts) else ("BLOCKED" if not hapi_ok else "FAIL"),
                 [f"{len(pts)} Synthea patients in HAPI", ", ".join(f"{p['activeConditions']}c/{p['activeMedications']}m" for p in pts)],
                 "GET /api/patients; GET /api/patients/{id}/profile"),
            item(4, "NEWS2-style baseline, SpO2 Scale 2, personalized baselines",
                 "PARTIAL",
                 ["NEWS2-style score from 4 of 7 parameters (BP, oxygen, consciousness not measured)",
                  "Band transcription from RCP 2017 NOT verified against the chart PDF (BLOCKED: PDF not available)",
                  "Scale 2 only via attributed FHIR Flag; 2 personalization rules with a safety floor (unit-tested)"],
                 "apps/api/tests/test_detector.py; GET/POST /api/patients/{id}/scale2"),
            item(5, "Sensor artifact detection and false alert suppression",
                 "PASS" if art and art["personalized"]["falseAlertEpisodes"] < art["fixed"]["falseAlertEpisodes"] else ("BLOCKED" if not art else "FAIL"),
                 [f"artifact scenario false alert episodes: fixed {art['fixed']['falseAlertEpisodes']} vs personalized {art['personalized']['falseAlertEpisodes']}" if art else "no evaluation report yet"],
                 "POST /api/evaluation/run"),
            item(6, "Clinician dashboard with explainable Watch/Review/Urgent alerts",
                 "PASS" if (acc or {}).get("checks", {}).get("levels_seen", {}).get("status") == "PASS" else "PARTIAL",
                 ["live updates via WebSocket /ws/monitor/{id} (polling fallback)",
                  f"levels observed in last acceptance run: {(acc or {}).get('checks', {}).get('levels_seen', {}).get('evidence', 'not run')}"],
                 "scripts/acceptance.py"),
            item(7, "Scenario replay and comparative report vs fixed thresholds",
                 "PASS" if evalr else "BLOCKED",
                 [f"report {evalr['generatedAt'][:19]} UTC, {len(sc)} scenarios, seeds {[s['seed'] for s in sc.values()]}" if evalr else "no report",
                  f"deterioration lead before critical: fixed {det['fixed']['leadTimeBeforeCriticalMin']} min, personalized {det['personalized']['leadTimeBeforeCriticalMin']} min" if det else ""],
                 "POST /api/evaluation/run; GET /api/evaluation/latest"),
        ]
        return {"generatedAt": _now(), "requirements": reqs, "evaluation": evalr, "acceptance": acc,
                "dataProvenance": {"patients": "synthetic (Synthea v3.4.0)", "vitals": "simulated (seeded scenarios)",
                                   "bidmc": f"{len(bidmc_files)} real recordings" if bidmc_files else "not available"}}

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
