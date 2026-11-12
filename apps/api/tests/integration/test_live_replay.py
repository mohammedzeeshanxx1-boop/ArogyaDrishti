"""Phase 1 replay engine against a real HAPI FHIR R4 server (skipped as BLOCKED without one)."""

from __future__ import annotations

import asyncio
import json
import os
import time
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.fhir import FhirClient
from app.main import create_app
from app.replay.persistence import REPLAY_ID_SYSTEM, SESSION_TAG_SYSTEM, persist_batch
from app.replay.scenarios import SCENARIOS, generate

BASE = (os.environ.get("HAPI_TEST_FHIR_BASE") or os.environ.get("FHIR_BASE_URL") or "http://localhost:8090/baseR4").rstrip("/")
FHIR = {"Accept": "application/fhir+json"}
pytestmark = pytest.mark.live

try:
    _up = httpx.get(f"{BASE}/metadata", headers=FHIR, timeout=10).status_code == 200
except httpx.HTTPError:
    _up = False
if not _up:
    pytest.skip(f"BLOCKED: HAPI FHIR not reachable at {BASE}/metadata", allow_module_level=True)


@pytest.fixture(scope="module")
def api(tmp_path_factory):
    db = tmp_path_factory.mktemp("live-replay") / "app.db"
    with TestClient(create_app(Settings(BASE, 10, str(db), ("http://localhost:5173",), fhir_request_timeout_seconds=120))) as c:
        yield c


@pytest.fixture(scope="module")
def patient_id(api):
    pts = api.get("/api/patients").json()["patients"]
    if not pts:
        pytest.skip("BLOCKED: no Synthea patients in HAPI; run scripts/dev/seed.sh")
    return pts[1]["id"] if len(pts) > 1 else pts[0]["id"]


def session_observations(sid: str) -> list[dict]:
    out, url = [], f"{BASE}/Observation"
    params = {"_tag": f"{SESSION_TAG_SYSTEM}|{sid}", "_sort": "date", "_count": 500}
    with httpx.Client(headers=FHIR, timeout=120) as c:
        r = c.get(url, params=params).json()
        while True:
            out += [e["resource"] for e in r.get("entry", [])]
            nxt = next((l["url"] for l in r.get("link", []) if l["relation"] == "next"), None)
            if not nxt:
                return out
            r = c.get(nxt).json()


def canonical(obs: list[dict]) -> list[tuple]:
    return sorted((o["code"]["coding"][0]["code"], o["effectiveDateTime"], float(o["valueQuantity"]["value"]),
                   o["valueQuantity"]["code"], o["subject"]["reference"]) for o in obs)


ANCHOR = (datetime.now(timezone.utc) - timedelta(days=2)).replace(second=0, microsecond=0)


@pytest.fixture(scope="module")
def batch_session(api, patient_id):
    body = {"patientId": patient_id, "scenario": "deterioration", "speed": "batch", "durationMinutes": 60,
            "intervalSeconds": 60, "anchor": ANCHOR.isoformat(), "batchSize": 100}
    sid = api.post("/api/replay/sessions", json=body).json()["sessionId"]
    t0 = time.time()
    done = api.post(f"/api/replay/sessions/{sid}/start", params={"wait": True}).json()
    done["wallSeconds"] = time.time() - t0
    return done


def test_batch_replay_is_confirmed_by_hapi(api, batch_session):
    s = batch_session
    assert s["state"] == "completed" and s["persisted"] == s["eventsTotal"] == 244, s
    p = api.get(f"/api/replay/sessions/{s['sessionId']}/persistence").json()
    assert p["hapiCountForSessionTag"] == 244 and p["consistent"] is True and p["complete"] is True
    assert all(b["outcome"] == "confirmed" for b in p["batches"])


def test_replayed_observations_read_back_with_correct_coding_and_times(batch_session, patient_id):
    obs = session_observations(batch_session["sessionId"])
    assert len(obs) == 244
    events, _ = generate(SCENARIOS["deterioration"], SCENARIOS["deterioration"].default_seed, ANCHOR, 60, 60)
    expected = sorted((e.loinc, e.measured_at.isoformat(), e.value, e.ucum, f"Patient/{patient_id}") for e in events)
    got = canonical(obs)
    # HAPI may render the timezone as +00:00 or Z; compare as instants.
    norm = lambda rows: [(a, datetime.fromisoformat(b.replace("Z", "+00:00")), c, d, e) for a, b, c, d, e in rows]
    assert norm(got) == norm(expected)
    for o in obs[:8]:
        assert o["status"] == "final" and o["category"][0]["coding"][0]["code"] == "vital-signs"
        assert o["identifier"][0]["system"] == REPLAY_ID_SYSTEM
        measured = datetime.fromisoformat(o["effectiveDateTime"].replace("Z", "+00:00"))
        ingested = datetime.fromisoformat(o["meta"]["lastUpdated"].replace("Z", "+00:00"))
        assert ingested - measured > timedelta(days=1)          # measurement time is not the ingestion time
        assert any(p.endswith(("heartrate", "oxygensat", "resprate", "bodytemp")) for p in o["meta"]["profile"])


def test_reset_reproduces_identical_observations(api, batch_session):
    new = api.post(f"/api/replay/sessions/{batch_session['sessionId']}/reset").json()
    assert new["fingerprint"] == batch_session["fingerprint"]
    done = api.post(f"/api/replay/sessions/{new['sessionId']}/start", params={"wait": True}).json()
    assert done["state"] == "completed"
    assert canonical(session_observations(new["sessionId"])) == canonical(session_observations(batch_session["sessionId"]))


def test_resending_a_confirmed_batch_creates_no_duplicates(batch_session, patient_id):
    events, _ = generate(SCENARIOS["deterioration"], SCENARIOS["deterioration"].default_seed, ANCHOR, 60, 60)

    async def resend():
        client = FhirClient(BASE, 120)
        try:
            return await persist_batch(client, events[:40], patient_id, batch_session["sessionId"], set(), datetime.now(timezone.utc))
        finally:
            await client.aclose()

    res = asyncio.run(resend())
    assert res.created == 0 and res.existing == 40
    assert len(session_observations(batch_session["sessionId"])) == 244


def test_accelerated_playback_at_10x(api, patient_id):
    # 4 simulated minutes at 30 s intervals -> 9 steps; at 10x the last step is due after ~24 s wall.
    anchor = (datetime.now(timezone.utc) - timedelta(hours=3)).replace(microsecond=0)
    sid = api.post("/api/replay/sessions", json={"patientId": patient_id, "scenario": "stable", "speed": "10x",
                                                 "durationMinutes": 4, "intervalSeconds": 30, "anchor": anchor.isoformat()}).json()["sessionId"]
    t0 = time.time()
    api.post(f"/api/replay/sessions/{sid}/start")
    time.sleep(10)
    mid = api.get(f"/api/replay/sessions/{sid}").json()
    assert mid["state"] == "running" and 0 < mid["cursor"] < mid["eventsTotal"]
    api.post(f"/api/replay/sessions/{sid}/pause")
    paused_cursor = api.get(f"/api/replay/sessions/{sid}").json()["cursor"]
    time.sleep(4)
    assert api.get(f"/api/replay/sessions/{sid}").json()["cursor"] == paused_cursor
    api.post(f"/api/replay/sessions/{sid}/resume")
    while api.get(f"/api/replay/sessions/{sid}").json()["state"] == "running" and time.time() - t0 < 90:
        time.sleep(1)
    end = api.get(f"/api/replay/sessions/{sid}").json()
    wall = time.time() - t0
    assert end["state"] == "completed" and end["persisted"] == 36
    assert 24 <= wall <= 24 + 4 + 15, wall                     # ~24 s of playback + 4 s paused + overhead
    assert len(session_observations(sid)) == 36


def test_monitor_shows_only_the_replay_session(api, patient_id, batch_session):
    sid = api.get("/api/replay/sessions").json()["sessions"][-1]["sessionId"]
    m = api.get(f"/api/demo/monitor/{patient_id}").json()
    assert m["replay"]["sessionId"] == sid
    tags = {o.split("/")[1] for v in m["vitals"].values() for o in [p["observation"] for p in v["series"]]}
    sess_ids = {o["id"] for o in session_observations(sid)}
    assert tags <= sess_ids and m["observationCount"] == len(sess_ids)
    assert "onset" not in json.dumps(m).lower()
