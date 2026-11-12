"""Live tests against a real HAPI FHIR R4 server and the imported Synthea cohort.

Configure with HAPI_TEST_FHIR_BASE, else FHIR_BASE_URL, else http://localhost:8090/baseR4 (local HAPI).
If HAPI or the cohort is missing, tests are skipped with a reason starting
"BLOCKED:" so the gap is visible (run pytest with -rs). They never pass
without a live server.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.vitals import INGEST_TAG, LOINC, VITALS, example_observation

BASE = (os.environ.get("HAPI_TEST_FHIR_BASE") or os.environ.get("FHIR_BASE_URL") or "http://localhost:8090/baseR4").rstrip("/")
MANIFEST = Path(__file__).resolve().parents[4] / "services" / "synthea" / "output" / "manifest.json"
FHIR = {"Accept": "application/fhir+json", "Content-Type": "application/fhir+json"}

pytestmark = pytest.mark.live


def _metadata() -> dict | None:
    try:
        r = httpx.get(f"{BASE}/metadata", headers=FHIR, timeout=10)
        return r.json() if r.status_code == 200 else None
    except (httpx.HTTPError, ValueError):
        return None


META = _metadata()
if META is None:
    pytest.skip(f"BLOCKED: HAPI FHIR not reachable at {BASE}/metadata", allow_module_level=True)


@pytest.fixture(scope="module")
def hapi():
    with httpx.Client(base_url=BASE, headers=FHIR, timeout=120) as c:
        yield c


@pytest.fixture(scope="module")
def api(tmp_path_factory):
    db = tmp_path_factory.mktemp("live") / "app.db"
    settings = Settings(BASE, 10, str(db), ("http://localhost:5173",), fhir_request_timeout_seconds=120)
    with TestClient(create_app(settings)) as c:
        yield c


@pytest.fixture(scope="module")
def cohort(api):
    body = api.get("/api/patients").json()
    if body.get("count", 0) < 5:
        pytest.skip(f"BLOCKED: fewer than 5 Synthea patients in HAPI ({body.get('count', 0)}); run services/synthea/pipeline.py all")
    return body["patients"]


@pytest.fixture(scope="module")
def patient_id(cohort):
    return cohort[0]["id"]


def _now():
    return datetime.now(timezone.utc).replace(microsecond=0)


def _ingested_count(hapi, pid: str) -> int:
    r = hapi.get("Observation", params={"subject": f"Patient/{pid}", "_tag": f"{INGEST_TAG['system']}|{INGEST_TAG['code']}", "_summary": "count"})
    return r.json()["total"]


# ------------------------------------------------------------------ server
def test_hapi_responds_as_fhir_r4():
    assert META["resourceType"] == "CapabilityStatement"
    assert META["fhirVersion"].startswith("4.0")


def test_api_status_sees_r4(api):
    fhir = api.get("/api/v1/status").json()["services"]["fhir"]
    assert fhir["status"] == "ok" and fhir["isR4"] is True


# ------------------------------------------------------------------ vitals
@pytest.mark.parametrize("loinc,value,ucum", [
    ("8867-4", 84, "/min"), ("2708-6", 93, "%"), ("9279-1", 22, "/min"), ("8310-5", 38.1, "Cel"), ("8310-5", 100.4, "[degF]"),
])
def test_vital_is_stored_in_hapi_and_read_back(api, hapi, patient_id, loinc, value, ucum):
    obs = example_observation(loinc, patient_id, value, _now() - timedelta(minutes=1), ucum)
    r = api.post("/api/fhir/Observation", json=obs)
    assert r.status_code == 201, r.json()
    body = r.json()
    assert body["validation"]["hapi"]["errors"] == 0
    assert body["readBack"]["matches"] is True

    # Read straight from HAPI, bypassing the API.
    stored = hapi.get(f"Observation/{body['id']}").json()
    assert stored["resourceType"] == "Observation"
    assert stored["status"] == "final"
    assert stored["subject"]["reference"] == f"Patient/{patient_id}"
    assert {"system": LOINC, "code": loinc} == {k: stored["code"]["coding"][0][k] for k in ("system", "code")}
    assert stored["valueQuantity"]["code"] == ucum and float(stored["valueQuantity"]["value"]) == value
    assert VITALS[loinc].profile in stored["meta"]["profile"]

    # Retrieve it by id through the API (which reads from HAPI).
    via_api = api.get(f"/api/fhir/Observation/{body['id']}")
    assert via_api.status_code == 200 and via_api.json() == stored

    # And find it through a FHIR search on patient + code.
    found = api.get("/api/fhir/Observation", params={"patient": patient_id, "code": loinc, "_count": 200}).json()
    assert body["id"] in {o["id"] for o in found["observations"]}


def _hapi_errors(obs: dict) -> list[str]:
    """Run the app's FhirClient.validate (declares the profile) against live HAPI."""
    import asyncio

    from app.fhir import FhirClient, summarize_outcome

    async def run():
        client = FhirClient(BASE, 120)
        try:
            return summarize_outcome(await client.validate(obs, VITALS[obs["code"]["coding"][0]["code"]].profile))
        finally:
            await client.aclose()

    return [i["diagnostics"] for i in asyncio.run(run())["issues"] if i["severity"] in ("error", "fatal")]


def test_official_validator_accepts_all_four_vital_examples(patient_id):
    for loinc, spec in VITALS.items():
        obs = example_observation(loinc, patient_id, 50, _now(), next(iter(spec.units)))
        assert _hapi_errors(obs) == [], loinc


def test_official_validator_enforces_vital_signs_profile(patient_id):
    no_category = example_observation("8867-4", patient_id, 70, _now())
    no_category.pop("category")
    errs = _hapi_errors(no_category)
    assert any("Observation.category" in e for e in errs), errs
    wrong_unit = example_observation("8867-4", patient_id, 70, _now())
    wrong_unit["valueQuantity"]["code"] = "%"
    errs = _hapi_errors(wrong_unit)
    assert any("/min" in e for e in errs), errs


@pytest.mark.parametrize("case", ["wrong-unit", "no-subject", "future", "bad-loinc", "no-timezone", "unknown-patient", "not-json-object"])
def test_invalid_payload_is_rejected_and_not_stored(api, hapi, patient_id, case):
    before = _ingested_count(hapi, patient_id)
    obs = example_observation("8867-4", patient_id, 70, _now())
    if case == "wrong-unit":
        obs["valueQuantity"]["code"] = "bpm"
    elif case == "no-subject":
        obs.pop("subject")
    elif case == "future":
        obs["effectiveDateTime"] = (_now() + timedelta(days=1)).isoformat()
    elif case == "bad-loinc":
        obs["code"]["coding"][0]["code"] = "8480-6"
    elif case == "no-timezone":
        obs["effectiveDateTime"] = _now().strftime("%Y-%m-%dT%H:%M:%S")
    elif case == "unknown-patient":
        obs["subject"] = {"reference": "Patient/does-not-exist-c1"}
    elif case == "not-json-object":
        obs = ["Observation"]
    r = api.post("/api/fhir/Observation", json=obs)
    assert r.status_code == 422, r.json()
    assert r.json()["resourceType"] == "OperationOutcome"
    assert _ingested_count(hapi, patient_id) == before


def test_inspector_exposes_stored_observation_and_validation(api, patient_id):
    created = api.post("/api/fhir/Observation", json=example_observation("2708-6", patient_id, 91, _now())).json()
    i = api.get(f"/api/inspector/observations/{created['id']}").json()
    assert i["observation"] == f"Observation/{created['id']}"
    assert i["source"] == "api-ingest" and i["vital"] == "spo2"
    assert i["validation"]["local"]["passed"] is True
    assert i["validation"]["hapi"]["errors"] == 0
    assert i["validation"]["hapi"]["profile"] == VITALS["2708-6"].profile
    assert i["ingestion"][0]["outcome"] == "accepted" and i["ingestion"][0]["read_back_matches"] is True
    assert i["resource"]["id"] == created["id"]


# ------------------------------------------------------------------ profiles
def test_at_least_five_synthetic_patients(cohort):
    assert len(cohort) >= 5
    assert all(p["synthetic"] for p in cohort)


def test_every_profile_is_complete_and_references_its_patient(api, cohort):
    for p in cohort:
        prof = api.get(f"/api/patients/{p['id']}/profile").json()
        c = prof["completeness"]
        assert c["complete"], (p["id"], c)
        assert prof["patient"]["reference"] == f"Patient/{p['id']}"
        assert prof["patient"]["syntheaId"] == p["id"]
        assert prof["discharge"]["discharged"]
        assert prof["activeConditions"] and all(x["coding"]["system"] == "http://snomed.info/sct" for x in prof["activeConditions"])
        assert prof["activeMedications"] and all(m["medication"] for m in prof["activeMedications"])


def test_cohort_matches_synthea_manifest(cohort):
    if not MANIFEST.exists():
        pytest.skip(f"BLOCKED: {MANIFEST} not found; run services/synthea/pipeline.py")
    manifest = json.loads(MANIFEST.read_text())
    assert {s["syntheaId"] for s in manifest["cohort"]} <= {p["id"] for p in cohort}
    assert manifest["synthea"]["version"] and len(manifest["synthea"]["sha256"]) == 64


def test_profile_for_unknown_patient_is_404(api):
    r = api.get("/api/patients/no-such-patient-c1/profile")
    assert r.status_code == 404 and r.json()["resourceType"] == "OperationOutcome"
