"""SpO2 Scale 2 eligibility, stored as a FHIR R4 Flag in HAPI.

NEWS2 Scale 2 is for patients with confirmed hypercapnic respiratory failure who have a
clinician-prescribed SpO2 target of 88-92 %. Eligibility therefore requires an explicit,
attributed clinical decision. A diagnosis (e.g. COPD) alone NEVER switches the scale; it is
only shown as supporting context.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone

from .fhir import FhirClient

FLAG_SYSTEM = "urn:arogya-drishti:flag"
FLAG_CODE = "news2-spo2-scale2"
SUPPORTING = re.compile(r"hypercap|respiratory failure|COPD|chronic obstructive|emphysema|obesity hypoventilation", re.I)


def _is_scale2(f: dict) -> bool:
    return any(c.get("system") == FLAG_SYSTEM and c.get("code") == FLAG_CODE for c in f.get("code", {}).get("coding", []))


async def active_flag(fhir: FhirClient, pid: str) -> dict | None:
    flags = await fhir.search("Flag", {"patient": f"Patient/{pid}", "_count": 50})
    active = [f for f in flags if _is_scale2(f) and f.get("status") == "active"]
    return max(active, key=lambda f: f.get("meta", {}).get("lastUpdated", "")) if active else None


async def status(fhir: FhirClient, pid: str) -> dict:
    flag = await active_flag(fhir, pid)
    conds = await fhir.search("Condition", {"subject": f"Patient/{pid}", "clinical-status": "active", "_count": 200})
    texts = {(c.get("code", {}).get("text") or (c.get("code", {}).get("coding") or [{}])[0].get("display") or "") for c in conds}
    supporting = sorted(t for t in texts if SUPPORTING.search(t))
    return {
        "patientId": pid,
        "scale": 2 if flag else 1,
        "eligible": flag is not None,
        "rule": "Scale 2 only with an active, attributed clinician decision (FHIR Flag); a diagnosis alone never switches the scale",
        "flag": None if not flag else {
            "id": flag["id"], "reference": f"Flag/{flag['id']}", "author": flag.get("author", {}).get("display"),
            "reason": flag.get("code", {}).get("text"), "since": flag.get("period", {}).get("start"),
        },
        "supportingConditions": supporting,
    }


async def set_flag(fhir: FhirClient, pid: str, prescribed_by: str, reason: str) -> dict:
    if await active_flag(fhir, pid):
        return await status(fhir, pid)
    flag = {
        "resourceType": "Flag",
        "status": "active",
        "category": [{"coding": [{"system": "http://terminology.hl7.org/CodeSystem/flag-category", "code": "clinical", "display": "Clinical"}]}],
        "code": {"coding": [{"system": FLAG_SYSTEM, "code": FLAG_CODE, "display": "NEWS2 SpO2 Scale 2 (prescribed target 88-92 %)"}],
                 "text": f"Use NEWS2 SpO2 Scale 2: {reason}"},
        "subject": {"reference": f"Patient/{pid}"},
        "period": {"start": datetime.now(timezone.utc).replace(microsecond=0).isoformat()},
        "author": {"display": prescribed_by},
    }
    r = await fhir.request("POST", "Flag", json=flag)
    if r.status != 201:
        raise ValueError(f"HAPI did not store the Flag (HTTP {r.status})")
    return await status(fhir, pid)


async def clear_flag(fhir: FhirClient, pid: str) -> dict:
    flag = await active_flag(fhir, pid)
    if flag:
        flag = {**flag, "status": "inactive"}
        flag.setdefault("period", {})["end"] = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        r = await fhir.request("PUT", f"Flag/{flag['id']}", json=flag)
        if r.status not in (200, 201):
            raise ValueError(f"HAPI did not update the Flag (HTTP {r.status})")
    return await status(fhir, pid)
