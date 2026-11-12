"""Unit tests for the strict local Observation validator (no HAPI needed)."""

from __future__ import annotations

import copy
from datetime import datetime, timedelta, timezone

import pytest

from app.vitals import VITALS, example_observation, normalize, validate_observation

NOW = datetime(2026, 11, 12, 8, 0, tzinfo=timezone.utc)
WHEN = NOW - timedelta(minutes=10)

VALID_CASES = [
    ("8867-4", 88, "/min", "heart_rate", "http://hl7.org/fhir/StructureDefinition/heartrate"),
    ("2708-6", 95, "%", "spo2", "http://hl7.org/fhir/StructureDefinition/oxygensat"),
    ("9279-1", 18, "/min", "respiratory_rate", "http://hl7.org/fhir/StructureDefinition/resprate"),
    ("8310-5", 37.2, "Cel", "body_temperature", "http://hl7.org/fhir/StructureDefinition/bodytemp"),
    ("8310-5", 99.1, "[degF]", "body_temperature", "http://hl7.org/fhir/StructureDefinition/bodytemp"),
]


@pytest.mark.parametrize("loinc,value,ucum,key,profile", VALID_CASES)
def test_all_four_vitals_are_accepted(loinc, value, ucum, key, profile):
    obs = example_observation(loinc, "p1", value, WHEN, ucum)
    r = validate_observation(obs, NOW)
    assert r.ok, r.issues
    assert r.spec.key == key and r.spec.profile == profile
    assert r.patient_id == "p1"


def test_supported_codes_are_exactly_the_four():
    assert set(VITALS) == {"8867-4", "2708-6", "9279-1", "8310-5"}


def test_normalize_declares_profile_and_tag_without_mutating_input():
    obs = example_observation("8867-4", "p1", 70, WHEN)
    before = copy.deepcopy(obs)
    out = normalize(obs, VITALS["8867-4"])
    assert obs == before
    assert out["meta"]["profile"] == ["http://hl7.org/fhir/StructureDefinition/heartrate"]
    assert out["meta"]["tag"][0]["code"] == "api-ingest"
    assert normalize(out, VITALS["8867-4"])["meta"]["profile"] == out["meta"]["profile"]  # idempotent


def _hr():
    return example_observation("8867-4", "p1", 80, WHEN)


def mutate(fn):
    obs = _hr()
    fn(obs)
    return obs


INVALID = {
    "not an object": ([], "Observation"),
    "wrong resourceType": (mutate(lambda o: o.update(resourceType="Patient")), "resourceType"),
    "unknown element": (mutate(lambda o: o.update(heartRate=80)), "Observation.heartRate"),
    "client-supplied id": (mutate(lambda o: o.update(id="abc")), "Observation.id"),
    "missing status": (mutate(lambda o: o.pop("status")), "Observation.status"),
    "status not in R4 value set": (mutate(lambda o: o.update(status="done")), "Observation.status"),
    "status entered-in-error": (mutate(lambda o: o.update(status="entered-in-error")), "Observation.status"),
    "status cancelled": (mutate(lambda o: o.update(status="cancelled")), "Observation.status"),
    "missing category": (mutate(lambda o: o.pop("category")), "Observation.category"),
    "category not vital-signs": (mutate(lambda o: o["category"][0]["coding"][0].update(code="laboratory")), "Observation.category"),
    "category wrong system": (mutate(lambda o: o["category"][0]["coding"][0].update(system="http://example.org")), "Observation.category"),
    "missing code": (mutate(lambda o: o.pop("code")), "Observation.code"),
    "unsupported LOINC (blood pressure)": (mutate(lambda o: o["code"]["coding"][0].update(code="85354-9")), "Observation.code"),
    "right code wrong system": (mutate(lambda o: o["code"]["coding"][0].update(system="http://snomed.info/sct")), "Observation.code"),
    "two supported LOINC codes": (mutate(lambda o: o["code"]["coding"].append({"system": "http://loinc.org", "code": "9279-1"})), "Observation.code"),
    "missing subject": (mutate(lambda o: o.pop("subject")), "Observation.subject"),
    "subject is not a Patient": (mutate(lambda o: o.update(subject={"reference": "Group/1"})), "Observation.subject.reference"),
    "subject absolute URL": (mutate(lambda o: o.update(subject={"reference": "http://x/fhir/Patient/1"})), "Observation.subject.reference"),
    "subject display only": (mutate(lambda o: o.update(subject={"display": "Jane"})), "Observation.subject.reference"),
    "missing effective": (mutate(lambda o: o.pop("effectiveDateTime")), "Observation.effectiveDateTime"),
    "effective without timezone": (mutate(lambda o: o.update(effectiveDateTime="2026-11-12T07:00:00")), "Observation.effectiveDateTime"),
    "effective date only": (mutate(lambda o: o.update(effectiveDateTime="2026-11-12")), "Observation.effectiveDateTime"),
    "effective impossible date": (mutate(lambda o: o.update(effectiveDateTime="2026-02-30T07:00:00Z")), "Observation.effectiveDateTime"),
    "effective in the future": (mutate(lambda o: o.update(effectiveDateTime=(NOW + timedelta(hours=1)).isoformat())), "Observation.effectiveDateTime"),
    "effectivePeriod": (mutate(lambda o: o.update(effectivePeriod={"start": WHEN.isoformat()})), "Observation.effectivePeriod"),
    "missing valueQuantity": (mutate(lambda o: o.pop("valueQuantity")), "Observation.valueQuantity"),
    "valueString instead": (mutate(lambda o: o.update(valueString="80")), "Observation.valueString"),
    "value is a string": (mutate(lambda o: o["valueQuantity"].update(value="80")), "Observation.valueQuantity.value"),
    "value is boolean": (mutate(lambda o: o["valueQuantity"].update(value=True)), "Observation.valueQuantity.value"),
    "value missing": (mutate(lambda o: o["valueQuantity"].pop("value")), "Observation.valueQuantity.value"),
    "unit system not UCUM": (mutate(lambda o: o["valueQuantity"].update(system="http://example.org/units")), "Observation.valueQuantity.system"),
    "wrong UCUM code for HR": (mutate(lambda o: o["valueQuantity"].update(code="bpm")), "Observation.valueQuantity.code"),
    "missing human unit": (mutate(lambda o: o["valueQuantity"].pop("unit")), "Observation.valueQuantity.unit"),
    "negative heart rate": (mutate(lambda o: o["valueQuantity"].update(value=-5)), "Observation.valueQuantity.value"),
    "comparator": (mutate(lambda o: o["valueQuantity"].update(comparator=">")), "Observation.valueQuantity.comparator"),
    "dataAbsentReason": (mutate(lambda o: o.update(dataAbsentReason={"text": "probe off"})), "Observation.dataAbsentReason"),
}


@pytest.mark.parametrize("name", sorted(INVALID))
def test_invalid_payload_is_rejected_at_the_right_path(name):
    payload, path = INVALID[name]
    r = validate_observation(payload, NOW)
    assert not r.ok
    assert path in {i.expression for i in r.issues}, [i.expression for i in r.issues]


def test_spo2_above_100_and_celsius_code_for_spo2_rejected():
    over = example_observation("2708-6", "p1", 101, WHEN)
    assert not validate_observation(over, NOW).ok
    bad_unit = example_observation("2708-6", "p1", 95, WHEN)
    bad_unit["valueQuantity"]["code"] = "Cel"
    assert not validate_observation(bad_unit, NOW).ok


def test_possible_but_implausible_readings_are_accepted_for_artifact_detection():
    # A detached probe can report 0 bpm or 0 % SpO2. These are sensor artifacts, not
    # malformed data, so ingestion keeps them for the C5 artifact detector.
    assert validate_observation(example_observation("8867-4", "p1", 0, WHEN), NOW).ok
    assert validate_observation(example_observation("2708-6", "p1", 0, WHEN), NOW).ok


def test_errors_carry_fhir_issue_structure():
    r = validate_observation(mutate(lambda o: o.pop("status")), NOW)
    issue = r.issues[0].as_fhir()
    assert set(issue) == {"severity", "code", "diagnostics", "expression"}
    assert issue["severity"] == "error" and issue["code"] == "required"
