"""FHIR persistence for replay: one transaction Bundle per batch, idempotent.

Per batch:
  1. every Observation passes the same strict local validator as the live endpoint;
     any failure aborts the whole batch before anything is sent
  2. the first Observation of each vital (LOINC) in a session is also checked with HAPI
     $validate against its R4 profile (a "shape" check; the live endpoint still
     validates every Observation)
  3. a FHIR transaction (all-or-nothing) with conditional create
     (ifNoneExist on a replay identifier) so retries never duplicate
  4. success only if HAPI returns a transaction-response with one 201/200 entry
     per Observation; otherwise PersistError (nothing is claimed as stored)
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime

from ..fhir import FhirClient, summarize_outcome
from ..vitals import VITALS, example_observation, normalize, validate_observation
from .scenarios import MeasurementEvent

REPLAY_ID_SYSTEM = "urn:arogya-drishti:replay-event"
SESSION_TAG_SYSTEM = "urn:arogya-drishti:replay-session"
DEVICE_LABEL = {
    "simulated": "Arogya Drishti virtual wearable (simulated)",
    "bidmc": "PhysioNet BIDMC recording (replayed)",
}


class PersistError(Exception):
    """HAPI did not confirm the batch. Nothing in it may be counted as stored."""


@dataclass
class BatchResult:
    created: int = 0
    existing: int = 0
    observation_ids: list[str] = field(default_factory=list)  # aligned with the batch's events
    statuses: list[str] = field(default_factory=list)          # 'created' (201) or 'existing' (200, retry)
    hapi_validated: list[str] = field(default_factory=list)   # LOINC codes shape-checked in this batch


def replay_identifier(session_id: str, seq: int) -> str:
    return f"{session_id}:{seq}"


def build_observation(event: MeasurementEvent, patient_id: str, session_id: str) -> dict:
    obs = example_observation(event.loinc, patient_id, event.value, event.measured_at, event.ucum)
    obs["identifier"] = [{"system": REPLAY_ID_SYSTEM, "value": replay_identifier(session_id, event.seq)}]
    obs["meta"] = {"tag": [{"system": SESSION_TAG_SYSTEM, "code": session_id, "display": "Replay session"}]}
    obs["device"] = {"display": DEVICE_LABEL.get(event.source, event.source)}
    return obs


def _id_from_location(loc: str | None) -> str | None:
    # "Observation/123/_history/1" -> "123"
    parts = (loc or "").split("/")
    return parts[1] if len(parts) >= 2 and parts[0] == "Observation" else None


async def persist_batch(fhir: FhirClient, events: list[MeasurementEvent], patient_id: str, session_id: str,
                        validated_shapes: set[str], now: datetime) -> BatchResult:
    if not events:
        return BatchResult()
    result = BatchResult()
    resources = []
    for e in events:
        raw = build_observation(e, patient_id, session_id)
        v = validate_observation(raw, now)
        if not v.ok:
            issues = "; ".join(f"{i.expression}: {i.diagnostics}" for i in v.issues)
            raise PersistError(f"event seq {e.seq} failed local validation ({issues}); batch not sent")
        resources.append(normalize(raw, v.spec))

    for e, res in zip(events, resources):
        if e.loinc not in validated_shapes and e.loinc not in result.hapi_validated:
            oo = summarize_outcome(await fhir.validate(res, VITALS[e.loinc].profile))
            if oo["errors"]:
                raise PersistError(f"HAPI $validate rejected {e.vital} (seq {e.seq}): {oo['issues'][0]['diagnostics']}")
            result.hapi_validated.append(e.loinc)

    bundle = {
        "resourceType": "Bundle",
        "type": "transaction",
        "entry": [
            {
                "fullUrl": f"urn:uuid:{uuid.uuid4()}",
                "resource": res,
                "request": {"method": "POST", "url": "Observation",
                            "ifNoneExist": f"identifier={REPLAY_ID_SYSTEM}|{replay_identifier(session_id, e.seq)}"},
            }
            for e, res in zip(events, resources)
        ],
    }
    r = await fhir.transaction(bundle)
    body = r.body
    if r.status != 200 or body.get("resourceType") != "Bundle" or body.get("type") != "transaction-response":
        diag = "; ".join(i.get("diagnostics", "") for i in body.get("issue", [])) or f"HTTP {r.status}"
        raise PersistError(f"transaction rejected by HAPI: {diag[:300]}")
    entries = body.get("entry", [])
    if len(entries) != len(events):
        raise PersistError(f"HAPI returned {len(entries)} entries for {len(events)} Observations")
    for e, entry in zip(events, entries):
        status = entry.get("response", {}).get("status", "")
        oid = _id_from_location(entry.get("response", {}).get("location"))
        if not oid or not status[:3] in ("200", "201"):
            raise PersistError(f"seq {e.seq}: unexpected transaction entry status {status!r}")
        result.observation_ids.append(oid)
        if status.startswith("201"):
            result.created += 1
            result.statuses.append("created")
        else:
            result.existing += 1
            result.statuses.append("existing")
    return result
