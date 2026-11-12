"""Doctor notifications, acknowledgements, patient management validation, CSV safety and access control."""

from __future__ import annotations

import csv
import io
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app import auth, datamgmt, detector, monitoring, notifications
from app.config import Settings
from app.db import init_db
from app.main import create_app
from fake_hapi import FakeHapi

NOW = datetime(2026, 11, 12, 12, 0, tzinfo=timezone.utc)


def _event(db, pid, hr):
    r = [{"vital": v, "value": x, "effective": NOW.isoformat(), "observation": f"Observation/{v}-{hr}", "source": "sim"}
         for v, x in [("heart_rate", hr), ("spo2", 97 if hr < 120 else 88), ("respiratory_rate", 15 if hr < 120 else 30), ("body_temperature", 36.8)]]
    risk = detector.evaluate(r)
    return monitoring.record_transition(db, pid, risk, monitoring.summarize(r, risk, NOW), "personalized", NOW)


@pytest.fixture()
def db(tmp_path):
    p = str(tmp_path / "n.db"); init_db(p); monitoring.init(p); notifications.init(p)
    return p


def test_baseline_hides_history_and_new_events_are_unread(db):
    _event(db, "p1", 72); _event(db, "p1", 135)          # history before the doctor first looks
    f = notifications.feed(db, "doctor")
    assert f["unread"] == 0 and all(i["read"] for i in f["items"])
    e = _event(db, "p2", 135)                              # a new event
    f2 = notifications.feed(db, "doctor", after=f["latestId"])
    assert [i["id"] for i in f2["items"]] == [e["id"]] and f2["unread"] == 1 and f2["items"][0]["read"] is False
    assert "URGENT" in f2["items"][0]["summary"]
    assert notifications.feed(db, "other.doctor")["unread"] == 0   # each account has its own baseline


def test_read_ack_are_separate_and_never_modify_events(db):
    notifications.feed(db, "doctor")
    a = _event(db, "p1", 135); b = _event(db, "p2", 135)
    before = monitoring.alert_events(db, None, 10)
    assert notifications.mark_read(db, "doctor", [a["id"]]) == 1
    f = notifications.feed(db, "doctor")
    assert f["unread"] == 1
    ack = notifications.acknowledge(db, "doctor", b["id"])
    assert ack["username"] == "doctor" and ack["eventId"] == b["id"]
    f = notifications.feed(db, "doctor")
    item = next(i for i in f["items"] if i["id"] == b["id"])
    assert f["unread"] == 0 and item["acknowledgedByMe"] and item["acknowledgements"][0]["username"] == "doctor"
    assert monitoring.alert_events(db, None, 10) == before             # alert history unchanged
    assert notifications.acknowledge(db, "doctor", 99999) is None
    _event(db, "p3", 135)
    assert notifications.mark_all_read(db, "doctor") >= 1 and notifications.feed(db, "doctor")["unread"] == 0


def test_patient_validation_messages():
    ok, errs = datamgmt.validate_patient({"name": "Test Person", "birth_date": "1980-02-03", "gender": "Female", "discharge_date": "2026-10-01"})
    assert not errs and ok["gender"] == "female" and ok["dischargeDate"] == "2026-10-01"
    _, errs = datamgmt.validate_patient({"name": "X", "birth_date": "2999-01-01", "gender": "robot", "discharge_date": "1970-01-01", "phone": "abc"}, 5)
    fields = {e["field"] for e in errs}
    assert {"name", "birth_date", "gender", "phone"} <= fields and all(e["row"] == 5 for e in errs)
    b = datamgmt.patient_bundle(ok, "portal-entry", "doctor", "req-12345678")
    assert [e["resource"]["resourceType"] for e in b["entry"]] == ["Patient", "Encounter"]
    assert b["entry"][0]["request"]["ifNoneExist"].endswith("|req-12345678")
    assert b["entry"][1]["resource"]["period"] == {"end": "2026-10-01"}


def test_observation_rows_validation():
    known = {"p1"}
    now = datetime.now(timezone.utc)
    t = (now - timedelta(hours=1)).isoformat(timespec="seconds")
    planned, errs = datamgmt.validate_observation_rows([{"patient_id": "p1", "timestamp": t, "heart_rate_bpm": "82", "spo2_percent": "97"}], known, now)
    assert not errs and {p["loinc"] for p in planned} == {"8867-4", "2708-6"}
    _, errs = datamgmt.validate_observation_rows([
        {"patient_id": "nope", "timestamp": "2026-11-12 10:00", "heart_rate_bpm": "abc"},
        {"patient_id": "p1", "timestamp": (now + timedelta(days=1)).isoformat(), "spo2_percent": "140"},
    ], known, now)
    msgs = " | ".join(e["message"] for e in errs)
    assert "No patient with id" in msgs and "timezone" in msgs and "not a number" in msgs and "future" in msgs and "outside the accepted range" in msgs
    _, errs = datamgmt.validate_observation_rows([{"patient_id": "p1", "timestamp": t, "pulse": "80"}], known, now)
    assert any("Unknown column" in e["message"] for e in errs)
    obs = datamgmt.import_observation(planned[0], "doctor", "f.csv", "imp-12345678")
    assert obs["device"]["display"].startswith("CSV import") and "wearable" not in obs["meta"]["tag"][0]["display"].lower()


def test_csv_escapes_formulas_and_quotes():
    text = datamgmt.to_csv(["a", "b", "c"], [["=HYPERLINK(\"x\")", "Doe, \"Jo\"", -3.5], ["@cmd", None, 0]])
    rows = list(csv.reader(io.StringIO(text)))
    assert rows[0] == ["a", "b", "c"] and rows[1] == ["'=HYPERLINK(\"x\")", 'Doe, "Jo"', "-3.5"] and rows[2] == ["'@cmd", "", "0"]
    assert datamgmt.to_csv(["x"], []) == "x\r\n"


@pytest.fixture()
def client(tmp_path):
    p = str(tmp_path / "a.db")
    s = Settings(fhir_base_url="http://hapi.test/baseR4", fhir_timeout_seconds=2, sqlite_path=p, cors_origins=(), auth_required=True)
    with TestClient(create_app(s, fhir_transport=FakeHapi().transport(), simulator_in_process=True)) as c:
        auth.upsert_user(p, "doctor", "doctor", "Demo clinician", "doc-pw-1")
        auth.upsert_user(p, "alex.lang", "patient", "Alex Lang", "pat-pw-1", patient_id="p-alex")
        yield c


def test_patient_accounts_cannot_use_doctor_features(client):
    assert client.post("/api/auth/login", json={"username": "alex.lang", "password": "pat-pw-1"}).status_code == 200
    for method, path, body in [("get", "/api/notifications", None), ("post", "/api/notifications/read-all", None),
                               ("post", "/api/alerts/1/acknowledge", None), ("post", "/api/patients", {"name": "A B"}),
                               ("post", "/api/patients/p-alex/account", {}), ("post", "/api/import/patients", {"rows": []}),
                               ("post", "/api/import/observations", {"rows": []}), ("get", "/api/export/patients.csv", None),
                               ("get", "/api/export/patients/p-alex/observations.csv", None), ("get", "/api/export/patients/p-alex/record.csv", None)]:
        r = getattr(client, method)(path, **({"json": body} if body is not None else {}))
        assert r.status_code == 403, (path, r.status_code)
    from starlette.websockets import WebSocketDisconnect
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/ws/notifications") as ws:
            ws.receive_json()


def test_doctor_notification_endpoints_and_socket(client):
    assert client.post("/api/auth/login", json={"username": "doctor", "password": "doc-pw-1"}).status_code == 200
    f = client.get("/api/notifications").json()
    assert f["unread"] == 0 and "items" in f
    assert client.post("/api/alerts/999/acknowledge").status_code == 404
    with client.websocket_connect("/ws/notifications") as ws:
        hello = ws.receive_json()
        assert hello["type"] == "hello" and hello["cursor"] == f["latestId"]
    r = client.post("/api/patients", json={"name": "X", "birthDate": "bad", "gender": "robot", "requestId": "req-12345678"})
    assert r.status_code == 422 and {e["field"] for e in r.json()["errors"]} >= {"name", "birth_date", "gender"}
