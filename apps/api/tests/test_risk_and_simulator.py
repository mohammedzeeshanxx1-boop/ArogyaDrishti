"""Round 1 MVP: prototype risk rules and the deterministic simulator."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import httpx
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.risk import evaluate
from app.simulator import SCENARIOS, Simulator, scenario_readings
from app.vitals import VITALS, validate_observation, example_observation
from fake_hapi import FakeHapi

KEY = {c: s.key for c, s in VITALS.items()}
T0 = datetime(2026, 11, 12, 8, 0, tzinfo=timezone.utc)


def as_readings(plan):
    out = []
    for i, step in enumerate(plan):
        for loinc, value in step.items():
            out.append({"vital": KEY[loinc], "value": value, "effective": (T0 + timedelta(seconds=10 * i)).isoformat(),
                        "observation": f"Observation/{i}-{loinc}"})
    return out


def levels_over_time(plan):
    return [evaluate(as_readings(plan[: i + 1]))["level"] for i in range(len(plan))]


def test_scenarios_are_deterministic_and_valid_fhir():
    for s in SCENARIOS:
        assert scenario_readings(s) == scenario_readings(s)
        for step in scenario_readings(s):
            for loinc, value in step.items():
                r = validate_observation(example_observation(loinc, "p1", value, T0), T0 + timedelta(minutes=1))
                assert r.ok, (s, loinc, value, r.issues)


def test_stable_recovery_stays_normal_throughout():
    assert set(levels_over_time(scenario_readings("stable"))) == {"NORMAL"}


def test_deterioration_escalates_monotonically_to_urgent():
    levels = levels_over_time(scenario_readings("deterioration"))
    ranks = [["NORMAL", "WATCH", "REVIEW", "URGENT"].index(l) for l in levels]
    assert levels[0] == "NORMAL" and levels[-1] == "URGENT"
    assert {"WATCH", "REVIEW"} <= set(levels)
    assert ranks == sorted(ranks)


def test_alerts_are_explainable():
    risk = evaluate(as_readings(scenario_readings("deterioration")))
    assert risk["level"] == "URGENT"
    top = risk["alerts"][0]
    assert top["ruleType"] == "threshold" and top["observation"].startswith("Observation/")
    for a in risk["alerts"]:
        assert a["rule"] and a["reason"] and a["observation"] and a["level"] in ("WATCH", "REVIEW", "URGENT")
    assert any(a["ruleType"] == "trend" for a in risk["alerts"])
    assert "Not NEWS2" in risk["label"]


def test_risk_uses_only_values_not_scenario_labels():
    # Same numbers, no scenario anywhere: the result depends on values alone.
    readings = [{"vital": "spo2", "value": 90, "effective": T0.isoformat(), "observation": "Observation/x"}]
    risk = evaluate(readings)
    assert risk["level"] == "URGENT" and "SpO2 ≤ 91 %" in risk["alerts"][0]["rule"]
    assert evaluate([])["level"] == "NORMAL"


def test_temperature_rule_uses_celsius_and_trend_needs_three_readings():
    two = [{"vital": "heart_rate", "value": v, "effective": f"2026-11-12T08:0{i}:00+00:00", "observation": f"Observation/{i}"} for i, v in enumerate([70, 99])]
    assert evaluate(two)["level"] == "NORMAL"


def test_simulator_posts_every_reading_through_the_ingestion_endpoint(tmp_path):
    hapi = FakeHapi()
    settings = Settings("http://hapi.test/fhir", 1, str(tmp_path / "app.db"), ("http://localhost:5173",))
    with TestClient(create_app(settings, fhir_transport=hapi.transport(), simulator_in_process=True)) as c:
        r = c.post("/api/demo/simulator/start", json={"patientId": "p1", "scenario": "deterioration", "steps": 3, "intervalSeconds": 0})
        assert r.status_code == 200, r.json()
        for _ in range(100):
            st = c.get("/api/demo/simulator").json()
            if not st["running"]:
                break
            asyncio.run(asyncio.sleep(0.02))
        assert st["step"] == 3 and st["accepted"] == 12 and st["rejected"] == 0, st
        events = c.get("/api/inspector/ingestions").json()["events"]
    assert len(hapi.observations) == 12
    assert {e["outcome"] for e in events} == {"accepted"}


def test_simulator_rejects_unknown_patient_and_scenario(tmp_path):
    settings = Settings("http://hapi.test/fhir", 1, str(tmp_path / "app.db"), ("http://localhost:5173",))
    with TestClient(create_app(settings, fhir_transport=FakeHapi().transport(), simulator_in_process=True)) as c:
        assert c.post("/api/demo/simulator/start", json={"patientId": "ghost", "scenario": "stable"}).status_code == 404
        assert c.post("/api/demo/simulator/start", json={"patientId": "p1", "scenario": "made-up"}).status_code == 400
