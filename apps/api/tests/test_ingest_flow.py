"""API control-flow tests for ingestion with a fake HAPI (no validation claims here)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.vitals import example_observation
from fake_hapi import FakeHapi

WHEN = datetime.now(timezone.utc) - timedelta(minutes=5)


def client_for(tmp_path, hapi: FakeHapi) -> TestClient:
    settings = Settings("http://hapi.test/fhir", 1, str(tmp_path / "app.db"), ("http://localhost:5173",))
    return TestClient(create_app(settings, fhir_transport=hapi.transport()))


@pytest.mark.parametrize("loinc,value,profile", [
    ("8867-4", 72, "heartrate"), ("2708-6", 97, "oxygensat"), ("9279-1", 16, "resprate"), ("8310-5", 36.9, "bodytemp"),
])
def test_valid_vital_is_validated_by_hapi_stored_and_read_back(tmp_path, loinc, value, profile):
    hapi = FakeHapi()
    with client_for(tmp_path, hapi) as c:
        r = c.post("/api/fhir/Observation", json=example_observation(loinc, "p1", value, WHEN))
        assert r.status_code == 201, r.json()
        body = r.json()
        assert body["readBack"] == {"found": True, "matches": True, "differingFields": [], "lastUpdated": "2026-11-12T08:00:00Z"}
        assert r.headers["location"].endswith(f"/Observation/{body['id']}/_history/1")
        assert hapi.validate_calls[0][0] == f"http://hl7.org/fhir/StructureDefinition/{profile}"
        # HAPI 5.7 enforces only profiles declared in meta.profile, so it must be there.
        assert hapi.validate_calls[0][1]["meta"]["profile"] == [f"http://hl7.org/fhir/StructureDefinition/{profile}"]
        stored = hapi.observations[body["id"]]
        assert stored["meta"]["profile"] == [f"http://hl7.org/fhir/StructureDefinition/{profile}"]
        events = c.get("/api/inspector/ingestions").json()["events"]
        assert events[0]["outcome"] == "accepted" and events[0]["observation_id"] == body["id"]


def test_locally_invalid_payload_never_reaches_hapi(tmp_path):
    hapi = FakeHapi()
    bad = example_observation("8867-4", "p1", 72, WHEN)
    bad["valueQuantity"]["code"] = "bpm"
    with client_for(tmp_path, hapi) as c:
        r = c.post("/api/fhir/Observation", json=bad)
        assert r.status_code == 422
        assert r.json()["resourceType"] == "OperationOutcome"
        assert r.headers["content-type"].startswith("application/fhir+json")
        ev = c.get("/api/inspector/ingestions").json()["events"][0]
    assert hapi.observations == {} and hapi.validate_calls == []
    assert ev["outcome"] == "rejected" and ev["stage"] == "local-validation"
    assert len(ev["payload_sha256"]) == 64


def test_non_json_body_is_400(tmp_path):
    with client_for(tmp_path, FakeHapi()) as c:
        r = c.post("/api/fhir/Observation", content=b"{not json", headers={"Content-Type": "application/fhir+json"})
    assert r.status_code == 400 and r.json()["issue"][0]["code"] == "structure"


def test_unknown_patient_is_rejected(tmp_path):
    hapi = FakeHapi(patients=())
    with client_for(tmp_path, hapi) as c:
        r = c.post("/api/fhir/Observation", json=example_observation("8867-4", "ghost", 72, WHEN))
    assert r.status_code == 422 and r.json()["issue"][0]["code"] == "not-found"
    assert hapi.observations == {}


def test_hapi_validation_errors_reject_and_are_reported(tmp_path):
    hapi = FakeHapi(validate_errors=["Observation.category: minimum required = 1"])
    with client_for(tmp_path, hapi) as c:
        r = c.post("/api/fhir/Observation", json=example_observation("8867-4", "p1", 72, WHEN))
        ev = c.get("/api/inspector/ingestions").json()["events"][0]
    assert r.status_code == 422
    assert "HAPI $validate" in r.json()["issue"][0]["diagnostics"]
    assert hapi.observations == {}
    assert ev["stage"] == "hapi-validation" and ev["hapiValidation"]["errors"] == 1


def test_read_back_mismatch_is_reported_not_hidden(tmp_path):
    hapi = FakeHapi(alter_on_store=lambda o: o["valueQuantity"].update(value=999))
    with client_for(tmp_path, hapi) as c:
        r = c.post("/api/fhir/Observation", json=example_observation("8867-4", "p1", 72, WHEN))
    assert r.status_code == 502
    assert r.json()["readBack"]["differingFields"] == ["valueQuantity"]


def test_hapi_down_gives_503_operation_outcome(tmp_path):
    with client_for(tmp_path, FakeHapi(down=True)) as c:
        r = c.post("/api/fhir/Observation", json=example_observation("8867-4", "p1", 72, WHEN))
    assert r.status_code == 503 and r.json()["issue"][0]["code"] == "transient"


def test_bad_ids_are_rejected_before_any_fhir_call(tmp_path):
    with client_for(tmp_path, FakeHapi(down=True)) as c:
        assert c.get("/api/patients/bad id!/profile").status_code == 400
        assert c.get("/api/inspector/observations/..%2F..").status_code in (400, 404)
        assert c.get("/api/fhir/Observation", params={"patient": "p1", "code": "1234-5"}).status_code == 400
