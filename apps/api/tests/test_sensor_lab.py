"""Sensor Reliability Lab metrics: measured against the scenario's ground-truth labels."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from app import auth, early_detection, sensor_lab
from app.config import Settings
from app.main import create_app
from app.replay.scenarios import SCENARIOS, event_dict, generate
from fake_hapi import FakeHapi

ANCHOR = datetime(2026, 11, 12, 10, 0, tzinfo=timezone.utc)


def run(scenario: str) -> tuple[dict, dict]:
    spec = SCENARIOS[scenario]
    events, truth = generate(spec, spec.default_seed, ANCHOR, spec.default_duration_minutes, spec.default_interval_seconds)
    readings = [{"vital": d["vital"], "value": d["value"], "effective": d["measured_at"], "observation": f"Observation/{i}"}
                for i, d in enumerate(map(event_dict, events))]
    a = early_detection.analyse(readings)                                  # detection first
    tr = [{"label": t.label, "start_at": t.start.isoformat(), "end_at": t.end.isoformat() if t.end else None, "detail": t.detail} for t in truth]
    return a, sensor_lab.metrics(a, tr)


def test_sensor_fault_scenario_counts():
    a, m = run("artifact")
    f, e = m["fixed"], m["engine"]
    assert m["labelledArtifactReadings"] > 0 and not m["scenarioHasDeterioration"]
    # every comparator alert in a stable scenario with faults is false; counts equal the comparator's alarm onsets
    onsets = sum(1 for i, s in enumerate(a["steps"]) if s["comparator"]["alarm"] and not (i and a["steps"][i - 1]["comparator"]["alarm"]))
    assert f["clinicalAlerts"] == onsets == f["falseClinicalAlerts"] > 0
    assert all(ep["artifactOnly"] for ep in f["episodes"])
    assert e["clinicalAlerts"] == 0 and e["falseClinicalAlerts"] == 0
    assert e["artifactsDetected"] == m["labelledArtifactReadings"] and e["readingsFlaggedNotLabelled"] == 0
    assert m["falseAlertsAvoided"] == f["falseClinicalAlerts"] - e["falseClinicalAlerts"]
    assert f["artifactsDetected"] is None and f["genuineDeterioration"]["applicable"] is False


def test_genuine_deterioration_is_not_suppressed():
    a, m = run("deterioration")
    e = m["engine"]
    assert m["labelledArtifactReadings"] == 0 and e["artifactsDetected"] == 0
    assert e["genuineDeterioration"]["detected"] and e["peakLevel"] in ("REVIEW", "URGENT") and e["falseClinicalAlerts"] == 0
    assert m["fixed"]["genuineDeterioration"]["detected"]


def test_faults_during_deterioration_keep_genuine_alerts():
    _, m = run("deterioration_artifact")
    assert m["engine"]["genuineDeterioration"]["detected"] and m["engine"]["falseClinicalAlerts"] == 0
    assert m["fixed"]["falseClinicalAlerts"] > 0


def test_sensor_lab_is_doctor_only(tmp_path):
    p = str(tmp_path / "a.db")
    s = Settings(fhir_base_url="http://hapi.test/baseR4", fhir_timeout_seconds=2, sqlite_path=p, cors_origins=(), auth_required=True)
    with TestClient(create_app(s, fhir_transport=FakeHapi().transport(), simulator_in_process=True)) as c:
        auth.upsert_user(p, "alex.lang", "patient", "Alex Lang", "pat-pw-1", patient_id="p-alex")
        assert c.get("/api/sensor-lab/runs/x").status_code == 401
        c.post("/api/auth/login", json={"username": "alex.lang", "password": "pat-pw-1"})
        assert c.get("/api/sensor-lab/runs/x").status_code == 403
