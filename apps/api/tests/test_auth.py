"""Server-enforced sign-in and patient-record authorization."""

from __future__ import annotations

import asyncio

import httpx
import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app import auth
from app.config import Settings
from app.main import create_app

from fake_hapi import FakeHapi


@pytest.fixture()
def client(tmp_path):
    db = str(tmp_path / "a.db")
    settings = Settings(fhir_base_url="http://hapi.test/baseR4", fhir_timeout_seconds=2, sqlite_path=db,
                        cors_origins=("http://localhost:5173",), auth_required=True)
    with TestClient(create_app(settings, fhir_transport=FakeHapi().transport(), simulator_in_process=True)) as c:
        auth.upsert_user(db, "doctor", "doctor", "Demo clinician", "doc-pw-1")
        auth.upsert_user(db, "alex.lang", "patient", "Alex Lang", "pat-pw-1", patient_id="p-alex")
        auth.upsert_user(db, "bo.ray", "patient", "Bo Ray", "pat-pw-2", patient_id="p-bo")
        yield c


def login(c, u, p):
    return c.post("/api/auth/login", json={"username": u, "password": p})


def test_password_hashing_roundtrip():
    h = auth.hash_password("s3cret")
    assert h.startswith("pbkdf2_sha256$") and "s3cret" not in h
    assert auth.verify_password("s3cret", h) and not auth.verify_password("wrong", h)


def test_unauthenticated_requests_are_rejected_but_status_is_public(client):
    assert client.get("/api/v1/status").status_code == 200
    for path in ["/api/patients", "/api/clinical/overview", "/api/alerts", "/api/demo/monitor/p-alex",
                 "/api/patients/p-alex/profile", "/api/demo/simulator", "/api/evidence", "/api/fhir/Observation"]:
        assert client.get(path).status_code == 401, path
    assert client.get("/api/auth/me").json() == {"authRequired": True, "user": None}
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/ws/monitor/p-alex") as ws:
            ws.receive_json()


def test_wrong_password_and_throttle(client):
    assert login(client, "doctor", "nope").status_code == 401
    for _ in range(5):
        login(client, "bo.ray", "nope")
    assert login(client, "bo.ray", "pat-pw-2").status_code == 429


def test_doctor_session_cookie_is_httponly_and_grants_access(client):
    r = login(client, "Doctor", "doc-pw-1")
    assert r.status_code == 200 and r.json()["user"]["role"] == "doctor"
    sc = r.headers["set-cookie"].lower()
    assert "httponly" in sc and "samesite=strict" in sc
    assert client.get("/api/auth/me").json()["user"]["username"] == "doctor"
    assert client.get("/api/demo/simulator").status_code == 200
    assert client.post("/api/auth/logout").status_code == 200
    assert client.get("/api/demo/simulator").status_code == 401


def test_patient_can_read_only_own_record(client):
    assert login(client, "alex.lang", "pat-pw-1").status_code == 200
    me = client.get("/api/auth/me").json()["user"]
    assert me == {"username": "alex.lang", "role": "patient", "patientId": "p-alex", "displayName": "Alex Lang"}
    assert client.get("/api/patients/p-alex/profile").status_code != 403
    assert client.get("/api/demo/monitor/p-alex").status_code != 403
    for path in ["/api/patients/p-bo/profile", "/api/demo/monitor/p-bo", "/api/patients", "/api/clinical/overview",
                 "/api/alerts?patient=p-alex", "/api/patients/p-alex/scale2", "/api/monitoring/status", "/api/inspector/ingestions"]:
        assert client.get(path).status_code == 403, path
    assert client.post("/api/demo/simulator/start", json={"patientId": "p-alex", "scenario": "stable"}).status_code == 403
    assert client.post("/api/demo/reset", json={"patientId": "p-alex"}).status_code == 403
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/ws/monitor/p-bo") as ws:
            ws.receive_json()


def test_decide_is_deny_by_default():
    pat = {"role": "patient", "patientId": "p1"}
    assert auth.decide("/api/anything/new", "GET", pat, False)[0] is False
    assert auth.decide("/api/demo/monitor/p1", "POST", pat, False)[0] is False
    assert auth.decide("/api/demo/monitor/p1", "WEBSOCKET", None, False)[1] == 401
    assert auth.decide("/api/fhir/Observation", "POST", None, True)[0] is True        # in-process simulator only
    assert auth.decide("/api/fhir/Observation", "GET", None, True)[0] is False
