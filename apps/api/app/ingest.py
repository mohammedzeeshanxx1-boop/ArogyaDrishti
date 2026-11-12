"""Vital-sign ingestion: validate, store in HAPI FHIR, read back.

Pipeline for one Observation:
  1. local strict validation (vitals.validate_observation)
  2. subject must exist in HAPI (GET Patient/{id})
  3. HAPI $validate against the official R4 vital-sign profile; any error rejects
  4. create in HAPI (POST Observation)
  5. read back (GET Observation/{id}) and compare the clinically relevant fields
Every outcome is recorded in the app's SQLite event store.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone

from .db import record_ingestion
from .fhir import FhirClient, outcome, outcome_issue, summarize_outcome
from .vitals import normalize, validate_observation

COMPARED_FIELDS = ("status", "category", "code", "subject", "effectiveDateTime", "valueQuantity")


@dataclass
class IngestResult:
    http_status: int
    body: dict


def _sha(resource) -> str:
    return hashlib.sha256(json.dumps(resource, sort_keys=True, default=str).encode()).hexdigest()


def _effective_equal(a: str | None, b: str | None) -> bool:
    if a == b:
        return True
    try:
        return datetime.fromisoformat(a.replace("Z", "+00:00")) == datetime.fromisoformat(b.replace("Z", "+00:00"))
    except (AttributeError, ValueError):
        return False


def compare_read_back(sent: dict, stored: dict) -> list[str]:
    """Names of compared fields whose stored value differs from what was sent."""
    diffs = []
    for f in COMPARED_FIELDS:
        if f == "effectiveDateTime":
            if not _effective_equal(sent.get(f), stored.get(f)):
                diffs.append(f)
        elif f == "valueQuantity":
            s, t = sent.get(f, {}), stored.get(f, {})
            if any(s.get(k) != t.get(k) for k in ("system", "code", "unit")) or float(s.get("value", "nan")) != float(t.get("value", "nan")):
                diffs.append(f)
        elif sent.get(f) != stored.get(f):
            diffs.append(f)
    return diffs


async def ingest_observation(resource, fhir: FhirClient, db_path: str, now: datetime | None = None) -> IngestResult:
    now = now or datetime.now(timezone.utc)
    received = now.isoformat()
    base_event = {"received_at": received, "payload_sha256": _sha(resource)}

    def reject(stage: str, status: int, issues: list[dict], **extra) -> IngestResult:
        record_ingestion(db_path, {**base_event, "outcome": "rejected", "stage": stage, "issues": issues, **extra})
        return IngestResult(status, outcome(issues))

    # 1. local strict validation
    v = validate_observation(resource, now)
    loinc = v.spec.loinc if v.spec else None
    patient_ref = f"Patient/{v.patient_id}" if v.patient_id else None
    if not v.ok:
        return reject("local-validation", 422, [i.as_fhir() for i in v.issues], loinc=loinc, patient_ref=patient_ref)

    # 2. subject exists
    if await fhir.read("Patient", v.patient_id) is None:
        return reject("subject", 422, [outcome_issue("error", "not-found", f"{patient_ref} does not exist on the FHIR server", "Observation.subject")],
                      loinc=loinc, patient_ref=patient_ref)

    # 3. HAPI $validate against the official profile
    normalized = normalize(resource, v.spec)
    oo = await fhir.validate(normalized, v.spec.profile)
    hv = {"profile": v.spec.profile, **summarize_outcome(oo)}
    if hv["errors"]:
        issues = [outcome_issue("error", "invariant", f"HAPI $validate: {i['diagnostics']}", i["location"]) for i in hv["issues"] if i["severity"] in ("error", "fatal")]
        return reject("hapi-validation", 422, issues, loinc=loinc, patient_ref=patient_ref, hapi_validation=hv)

    # 4. store
    created = await fhir.create(normalized)
    if created.status != 201 or created.body.get("resourceType") != "Observation" or not created.body.get("id"):
        diag = "; ".join(i.get("diagnostics", "") for i in created.body.get("issue", [])) or f"HTTP {created.status}"
        return reject("store", 502, [outcome_issue("error", "exception", f"HAPI did not store the Observation: {diag}")],
                      loinc=loinc, patient_ref=patient_ref, hapi_validation=hv)
    oid = created.body["id"]
    version = created.body.get("meta", {}).get("versionId")

    # 5. read back
    stored = await fhir.read("Observation", oid)
    diffs = compare_read_back(normalized, stored) if stored else list(COMPARED_FIELDS)
    matches = not diffs
    record_ingestion(db_path, {
        **base_event, "outcome": "accepted" if matches else "error", "stage": "read-back",
        "observation_id": oid, "version_id": version, "patient_ref": patient_ref, "loinc": loinc,
        "issues": [] if matches else [{"severity": "error", "diagnostics": f"read-back differs in {diffs}"}],
        "hapi_validation": hv, "read_back_matches": matches,
    })
    body = {
        "resourceType": "Observation",
        "id": oid,
        "versionId": version,
        "location": f"{fhir.base_url}/Observation/{oid}/_history/{version}",
        "vital": v.spec.key,
        "loinc": loinc,
        "subject": patient_ref,
        "validation": {"local": "passed", "hapi": hv},
        "readBack": {"found": stored is not None, "matches": matches, "differingFields": diffs, "lastUpdated": (stored or {}).get("meta", {}).get("lastUpdated")},
    }
    return IngestResult(201 if matches else 502, body)
