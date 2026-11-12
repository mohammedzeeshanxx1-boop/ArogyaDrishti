"""Doctor-only patient management: register patients, CSV import, CSV export.

- Patients are stored as FHIR R4 Patient resources (plus an inpatient Encounter carrying the discharge date
  when one is given). Nothing else is created: no conditions, medications or observations are invented.
- CSV imports are validated completely before anything is written; an import with any invalid row writes
  nothing (no silent partial success). Observations go through the normal ingestion pipeline
  (strict validation, HAPI $validate, storage, read-back) and are labelled as CSV imports, not wearables.
- CSV exports escape spreadsheet formulas and contain only stored values.
"""

from __future__ import annotations

import csv
import io
import re
import uuid
from datetime import date, datetime, timezone

from .patients import PORTAL_ID_SYSTEM
from .vitals import LOINC, VITALS, example_observation

SOURCE_SYSTEM = "urn:arogya-drishti:source"
SOURCE_DISPLAY = {"portal-entry": "Registered in the Doctor Portal", "csv-import": "Imported from CSV in the Doctor Portal"}
GENDERS = {"male", "female", "other", "unknown"}
NAME_RX = re.compile(r"^[A-Za-zÀ-ÖØ-öø-ÿ][A-Za-zÀ-ÖØ-öø-ÿ .'\-]{0,98}[A-Za-zÀ-ÖØ-öø-ÿ.]$")
PHONE_RX = re.compile(r"^\+?[0-9][0-9 ()\-]{5,19}$")
EMAIL_RX = re.compile(r"^[^@\s]{1,64}@[^@\s]+\.[A-Za-z]{2,}$")
MAX_PATIENT_ROWS = 200
MAX_OBSERVATION_ROWS = 100

# CSV column -> LOINC code (existing mapping) and the UCUM unit the column is expressed in.
OBS_COLUMNS = {
    "heart_rate_bpm": ("8867-4", "/min"),
    "spo2_percent": ("2708-6", "%"),
    "respiratory_rate_per_min": ("9279-1", "/min"),
    "temperature_c": ("8310-5", "Cel"),
}
PATIENT_COLUMNS = ["name", "birth_date", "gender", "discharge_date"]
OBS_REQUIRED = ["patient_id", "timestamp"]


def _date(v: str, field: str, errors: list[dict], row: int | None) -> date | None:
    try:
        d = date.fromisoformat(v)
    except ValueError:
        errors.append({"row": row, "field": field, "message": f"'{v}' is not a date in YYYY-MM-DD format"})
        return None
    if d > date.today():
        errors.append({"row": row, "field": field, "message": f"{v} is in the future"})
        return None
    if d.year < 1900:
        errors.append({"row": row, "field": field, "message": f"{v} is before 1900"})
        return None
    return d


def validate_patient(d: dict, row: int | None = None) -> tuple[dict | None, list[dict]]:
    """Clean and validate one patient (form or CSV row). Returns (clean, errors)."""
    errors: list[dict] = []
    name = re.sub(r"\s+", " ", str(d.get("name") or "")).strip()
    if not name:
        errors.append({"row": row, "field": "name", "message": "Name is required"})
    elif not NAME_RX.match(name) or len(name.split(" ")) < 2:
        errors.append({"row": row, "field": "name", "message": "Enter a first and last name using letters, spaces, apostrophes or hyphens"})
    birth = str(d.get("birth_date") or d.get("birthDate") or "").strip()
    bd = _date(birth, "birth_date", errors, row) if birth else None
    if not birth:
        errors.append({"row": row, "field": "birth_date", "message": "Date of birth is required"})
    gender = str(d.get("gender") or "").strip().lower()
    if gender not in GENDERS:
        errors.append({"row": row, "field": "gender", "message": "Gender must be one of: male, female, other, unknown (FHIR administrative gender)"})
    dis = str(d.get("discharge_date") or d.get("dischargeDate") or "").strip()
    dd = _date(dis, "discharge_date", errors, row) if dis else None
    if bd and dd and dd < bd:
        errors.append({"row": row, "field": "discharge_date", "message": "Discharge date is before the date of birth"})
    phone = str(d.get("phone") or "").strip()
    if phone and not PHONE_RX.match(phone):
        errors.append({"row": row, "field": "phone", "message": "Phone must contain 6–20 digits (spaces, (), - and a leading + allowed)"})
    email = str(d.get("email") or "").strip()
    if email and not EMAIL_RX.match(email):
        errors.append({"row": row, "field": "email", "message": "Email address is not valid"})
    if errors:
        return None, errors
    return {"name": name, "birthDate": bd.isoformat(), "gender": gender, "dischargeDate": dd.isoformat() if dd else None,
            "phone": phone or None, "email": email or None}, []


def patient_bundle(clean: dict, source: str, author: str, request_id: str) -> dict:
    """Transaction creating the Patient (idempotent on request_id) and, if given, a discharge Encounter."""
    parts = clean["name"].split(" ")
    pat_url = f"urn:uuid:{uuid.uuid4()}"
    tag = {"system": SOURCE_SYSTEM, "code": source, "display": SOURCE_DISPLAY[source]}
    patient = {
        "resourceType": "Patient",
        "meta": {"tag": [tag]},
        "identifier": [{"system": PORTAL_ID_SYSTEM, "value": request_id}],
        "active": True,
        "name": [{"use": "official", "text": clean["name"], "family": parts[-1], "given": parts[:-1]}],
        "gender": clean["gender"],
        "birthDate": clean["birthDate"],
        "telecom": [t for t in ([{"system": "phone", "value": clean["phone"], "use": "mobile"}] if clean.get("phone") else [])
                    + ([{"system": "email", "value": clean["email"]}] if clean.get("email") else [])],
    }
    if not patient["telecom"]:
        del patient["telecom"]
    entries = [{"fullUrl": pat_url, "resource": patient,
                "request": {"method": "POST", "url": "Patient", "ifNoneExist": f"identifier={PORTAL_ID_SYSTEM}|{request_id}"}}]
    if clean.get("dischargeDate"):
        entries.append({"fullUrl": f"urn:uuid:{uuid.uuid4()}", "resource": {
            "resourceType": "Encounter",
            "meta": {"tag": [tag]},
            "status": "finished",
            "class": {"system": "http://terminology.hl7.org/CodeSystem/v3-ActCode", "code": "IMP", "display": "inpatient encounter"},
            "type": [{"text": f"Hospital stay (discharge date recorded by {author})"}],
            "subject": {"reference": pat_url},
            "period": {"end": clean["dischargeDate"]},
        }, "request": {"method": "POST", "url": "Encounter"}})
    return {"resourceType": "Bundle", "type": "transaction", "entry": entries}


def created_patient_id(body: dict) -> str | None:
    for e in body.get("entry", []):
        loc = e.get("response", {}).get("location", "")
        if loc.startswith("Patient/"):
            return loc.split("/")[1]
    return None


# ------------------------------------------------------------------ observation import
def parse_timestamp(v: str) -> datetime | None:
    try:
        t = datetime.fromisoformat(v.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return t if t.tzinfo else None


def validate_observation_rows(rows: list[dict], known_patients: set[str], now: datetime) -> tuple[list[dict], list[dict]]:
    """Returns (planned observations, errors). Each planned item: row, patient_id, loinc, ucum, value, when."""
    planned, errors = [], []
    if not rows:
        errors.append({"row": None, "field": None, "message": "The file has no data rows"})
    if len(rows) > MAX_OBSERVATION_ROWS:
        errors.append({"row": None, "field": None, "message": f"At most {MAX_OBSERVATION_ROWS} rows per import ({len(rows)} given)"})
        return [], errors
    cols = set().union(*(r.keys() for r in rows)) if rows else set()
    missing = [c for c in OBS_REQUIRED if c not in cols]
    if missing:
        errors.append({"row": None, "field": None, "message": f"Missing required column(s): {', '.join(missing)}"})
    if not any(c in cols for c in OBS_COLUMNS):
        errors.append({"row": None, "field": None, "message": f"Include at least one vital-sign column: {', '.join(OBS_COLUMNS)}"})
    unknown = sorted(c for c in cols if c not in OBS_COLUMNS and c not in OBS_REQUIRED)
    if unknown:
        errors.append({"row": None, "field": None, "message": f"Unknown column(s): {', '.join(unknown)}"})
    if errors:
        return [], errors
    seen = set()
    for i, r in enumerate(rows, start=2):   # row 1 is the header
        pid = str(r.get("patient_id") or "").strip()
        if not pid:
            errors.append({"row": i, "field": "patient_id", "message": "patient_id is required"})
        elif pid not in known_patients:
            errors.append({"row": i, "field": "patient_id", "message": f"No patient with id '{pid}' in the FHIR server"})
        ts = str(r.get("timestamp") or "").strip()
        when = parse_timestamp(ts) if ts else None
        if not ts:
            errors.append({"row": i, "field": "timestamp", "message": "timestamp is required"})
        elif when is None:
            errors.append({"row": i, "field": "timestamp", "message": f"'{ts}' is not an ISO 8601 date-time with a timezone (e.g. 2026-11-12T08:30:00Z or 2026-11-12T14:00:00+05:30)"})
        elif when > now:
            errors.append({"row": i, "field": "timestamp", "message": f"{ts} is in the future"})
        values = 0
        for col, (loinc, ucum) in OBS_COLUMNS.items():
            raw = str(r.get(col) or "").strip()
            if not raw:
                continue
            try:
                v = float(raw)
            except ValueError:
                errors.append({"row": i, "field": col, "message": f"'{raw}' is not a number"})
                continue
            lo, hi = VITALS[loinc].units[ucum]
            if not (lo <= v <= hi):
                errors.append({"row": i, "field": col, "message": f"{v:g} is outside the accepted range {lo:g}–{hi:g}"})
                continue
            values += 1
            if pid and when:
                key = (pid, when.isoformat(), loinc)
                if key in seen:
                    errors.append({"row": i, "field": col, "message": "Duplicate measurement for this patient, time and vital in the file"})
                    continue
                seen.add(key)
                planned.append({"row": i, "patientId": pid, "loinc": loinc, "ucum": ucum, "value": v, "when": when})
        if values == 0 and not any(e["row"] == i for e in errors):
            errors.append({"row": i, "field": None, "message": "Row has no vital-sign value"})
    return planned, errors


def import_observation(item: dict, author: str, file_name: str, batch: str) -> dict:
    obs = example_observation(item["loinc"], item["patientId"], item["value"], item["when"], item["ucum"])
    obs["meta"] = {"tag": [{"system": SOURCE_SYSTEM, "code": "csv-import", "display": SOURCE_DISPLAY["csv-import"]},
                           {"system": "urn:arogya-drishti:import-batch", "code": batch, "display": f"{file_name} (uploaded by {author})"}]}
    obs["device"] = {"display": "CSV import (not a wearable reading)"}
    return obs


# ------------------------------------------------------------------ CSV export
_FORMULA = ("=", "+", "-", "@", "\t", "\r")


def cell(v) -> str | float | int:
    """Spreadsheet-safe cell: strings that could start a formula are prefixed with an apostrophe."""
    if v is None:
        return ""
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return v
    s = str(v)
    return "'" + s if s.startswith(_FORMULA) else s


def to_csv(header: list[str], rows: list[list]) -> str:
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\r\n", quoting=csv.QUOTE_MINIMAL)
    w.writerow(header)
    for r in rows:
        w.writerow([cell(v) for v in r])
    return buf.getvalue()


def safe_filename(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "-", s).strip("-")[:80] or "export"


def observation_rows(obs: list[dict], pid: str, name: str) -> list[list]:
    from .risk import to_celsius
    rows = []
    for o in obs:
        code = next((c["code"] for c in o.get("code", {}).get("coding", []) if c.get("system") == LOINC and c.get("code") in VITALS), None)
        q = o.get("valueQuantity") or {}
        if code is None or "value" not in q:
            continue
        spec = VITALS[code]
        value, unit = float(q["value"]), q.get("code") or q.get("unit") or ""
        if spec.key == "body_temperature" and unit == "[degF]":
            value, unit = round(to_celsius(value, unit), 2), "Cel"
        tags = {t.get("code") for t in o.get("meta", {}).get("tag", []) if t.get("system") == SOURCE_SYSTEM}
        source = (o.get("device") or {}).get("display") or ("CSV import" if "csv-import" in tags else "API ingestion" if "api-ingest" in tags else "FHIR server")
        rows.append([pid, name, o.get("effectiveDateTime"), spec.key, code, value, unit, source, o.get("status"), f"Observation/{o['id']}"])
    rows.sort(key=lambda r: (r[2] or "", r[3]))
    return rows


OBS_HEADER = ["patient_id", "patient_name", "timestamp", "vital", "loinc", "value", "unit", "source", "status", "observation_id"]
DIRECTORY_HEADER = ["patient_id", "name", "gender", "birth_date", "age", "last_discharge", "active_conditions", "active_medications",
                    "record_source", "risk_level", "monitoring_status", "last_observation_at"]
RECORD_HEADER = ["patient_id", "patient_name", "section", "item", "detail", "date"]


def now_utc() -> datetime:
    return datetime.now(timezone.utc)
