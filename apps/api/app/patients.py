"""Synthetic discharge profiles read from HAPI FHIR.

Patients are the Synthea cohort imported by services/synthea/pipeline.py and
are identified by Synthea's identifier system. All data is synthetic.
"""

from __future__ import annotations

import asyncio

from .fhir import FhirClient
from .vitals import LOINC, VITALS

SYNTHEA_ID_SYSTEM = "https://github.com/synthetichealth/synthea"


def _display(cc: dict | None) -> str | None:
    if not cc:
        return None
    return cc.get("text") or next((c.get("display") for c in cc.get("coding", []) if c.get("display")), None)


def _coding(cc: dict | None) -> dict | None:
    c = next(iter((cc or {}).get("coding", [])), None)
    return {"system": c.get("system"), "code": c.get("code"), "display": c.get("display")} if c else None


def _name(p: dict) -> str:
    n = next(iter(p.get("name", [])), {})
    return " ".join([*n.get("given", []), n.get("family", "")]).strip() or p["id"]


def _status(cc: dict | None) -> str | None:
    return next((c.get("code") for c in (cc or {}).get("coding", [])), None)


def _is_synthea(p: dict) -> bool:
    return any(i.get("system") == SYNTHEA_ID_SYSTEM for i in p.get("identifier", []))


async def list_patients(fhir: FhirClient) -> list[dict]:
    patients = await fhir.search("Patient", {"identifier": f"{SYNTHEA_ID_SYSTEM}|", "_count": 100, "_sort": "_id"})

    async def summary(p: dict) -> dict:
        ref = f"Patient/{p['id']}"
        last_imp, conds, meds = await asyncio.gather(
            fhir.search("Encounter", {"subject": ref, "class": "IMP", "_sort": "-date", "_count": 1}, limit=1),
            fhir.count("Condition", {"subject": ref, "clinical-status": "active"}),
            fhir.count("MedicationRequest", {"subject": ref, "status": "active"}),
        )
        enc = last_imp[0] if last_imp else None
        return {
            "id": p["id"],
            "name": _name(p),
            "gender": p.get("gender"),
            "birthDate": p.get("birthDate"),
            "synthetic": True,
            "lastDischarge": (enc or {}).get("period", {}).get("end"),
            "activeConditions": conds,
            "activeMedications": meds,
        }

    return list(await asyncio.gather(*(summary(p) for p in patients if _is_synthea(p))))


async def patient_profile(fhir: FhirClient, pid: str) -> dict | None:
    patient = await fhir.read("Patient", pid)
    if patient is None:
        return None
    ref = f"Patient/{pid}"
    encounters, conditions, med_bundle, allergies, careplans = await asyncio.gather(
        fhir.search("Encounter", {"subject": ref, "class": "IMP", "_sort": "-date", "_count": 50}),
        fhir.search("Condition", {"subject": ref, "clinical-status": "active", "_count": 200}),
        fhir.search("MedicationRequest", {"subject": ref, "status": "active", "_include": "MedicationRequest:medication", "_count": 200}),
        fhir.search("AllergyIntolerance", {"patient": ref, "_count": 100}),
        fhir.search("CarePlan", {"subject": ref, "status": "active", "_count": 50}),
    )
    vital_counts = await asyncio.gather(*(fhir.count("Observation", {"subject": ref, "code": f"{LOINC}|{c}"}) for c in VITALS))

    meds = [m for m in med_bundle if m["resourceType"] == "MedicationRequest"]
    med_resources = {f"Medication/{m['id']}": m for m in med_bundle if m["resourceType"] == "Medication"}

    def medication(mr: dict) -> dict:
        cc = mr.get("medicationCodeableConcept")
        if cc is None and "medicationReference" in mr:
            cc = med_resources.get(mr["medicationReference"].get("reference"), {}).get("code")
        return {
            "id": mr["id"],
            "medication": _display(cc),
            "coding": _coding(cc),
            "authoredOn": mr.get("authoredOn"),
            "dosage": next((d.get("text") for d in mr.get("dosageInstruction", []) if d.get("text")), None),
            "reason": [_display(r) or r.get("reference") for r in mr.get("reasonCode", []) + mr.get("reasonReference", [])],
        }

    discharge = encounters[0] if encounters else None
    subject_resources = encounters + conditions + meds + careplans
    refs_ok = all(r.get("subject", {}).get("reference") == ref for r in subject_resources) and all(
        a.get("patient", {}).get("reference") == ref for a in allergies
    )
    completeness = {
        "demographics": bool(patient.get("name") and patient.get("gender") and patient.get("birthDate")),
        "dischargeEncounter": bool(discharge and discharge.get("period", {}).get("end")),
        "activeConditions": bool(conditions),
        "activeMedications": bool(meds),
        "referencesResolveToPatient": refs_ok,
    }
    return {
        "patient": {
            "id": pid,
            "reference": ref,
            "name": _name(patient),
            "gender": patient.get("gender"),
            "birthDate": patient.get("birthDate"),
            "syntheaId": next((i.get("value") for i in patient.get("identifier", []) if i.get("system") == SYNTHEA_ID_SYSTEM), None),
            "synthetic": _is_synthea(patient),
        },
        "discharge": discharge and {
            "encounter": f"Encounter/{discharge['id']}",
            "type": _display(next(iter(discharge.get("type", [])), None)),
            "admitted": discharge.get("period", {}).get("start"),
            "discharged": discharge.get("period", {}).get("end"),
            "reason": [_display(r) for r in discharge.get("reasonCode", [])],
            "facility": (discharge.get("serviceProvider") or {}).get("display"),
            "inpatientStays": len(encounters),
        },
        "activeConditions": sorted(
            ({"id": c["id"], "condition": _display(c.get("code")), "coding": _coding(c.get("code")), "onset": c.get("onsetDateTime")} for c in conditions),
            key=lambda c: (c["onset"] or "", c["id"]),
        ),
        "activeMedications": sorted((medication(m) for m in meds), key=lambda m: (m["authoredOn"] or "", m["id"])),
        "allergies": [{"id": a["id"], "substance": _display(a.get("code")), "criticality": a.get("criticality"),
                       "clinicalStatus": _status(a.get("clinicalStatus"))} for a in allergies],
        "activeCarePlans": [{"id": c["id"], "plan": _display(next(iter(c.get("category", [])), None))} for c in careplans],
        "vitalObservationCounts": {VITALS[c].key: n for c, n in zip(VITALS, vital_counts)},
        "completeness": {**completeness, "complete": all(completeness.values())},
    }
