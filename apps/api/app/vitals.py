"""Strict validation of incoming FHIR R4 vital-sign Observations.

This is the first of two gates. The second is HAPI FHIR's own ``$validate``
against the official R4 vital-signs profile (see ingest.py).

Only four vital signs are accepted, each with the LOINC code and UCUM unit
required by the corresponding base R4 profile:

  8867-4  heart rate         http://hl7.org/fhir/StructureDefinition/heartrate   /min
  2708-6  oxygen saturation  http://hl7.org/fhir/StructureDefinition/oxygensat   %
  9279-1  respiratory rate   http://hl7.org/fhir/StructureDefinition/resprate    /min
  8310-5  body temperature   http://hl7.org/fhir/StructureDefinition/bodytemp    Cel, [degF]

Value bounds below reject only physically impossible numbers (e.g. negative
rates, SpO2 above 100 %). They are not clinical thresholds and say nothing
about whether a reading is plausible for a patient: implausible but possible
readings (sensor artifacts) are deliberately accepted so that the artifact
detector (checkpoint C5) can see them.
"""

from __future__ import annotations

import copy
import math
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

LOINC = "http://loinc.org"
UCUM = "http://unitsofmeasure.org"
OBS_CATEGORY = "http://terminology.hl7.org/CodeSystem/observation-category"
INGEST_TAG = {"system": "urn:arogya-drishti:source", "code": "api-ingest", "display": "Ingested via Arogya Drishti API"}

# FHIR R4 Observation.status value set (required binding).
R4_OBSERVATION_STATUS = {"registered", "preliminary", "final", "amended", "corrected", "cancelled", "entered-in-error", "unknown"}
# Statuses that carry a usable measurement for monitoring.
ACCEPTED_STATUS = {"preliminary", "final", "amended", "corrected"}

# Every element defined on R4 Observation (including inherited ones). Anything else is rejected.
R4_OBSERVATION_ELEMENTS = {
    "resourceType", "id", "meta", "implicitRules", "language", "text", "contained", "extension", "modifierExtension",
    "identifier", "basedOn", "partOf", "status", "category", "code", "subject", "focus", "encounter",
    "effectiveDateTime", "effectivePeriod", "effectiveTiming", "effectiveInstant", "issued", "performer",
    "valueQuantity", "valueCodeableConcept", "valueString", "valueBoolean", "valueInteger", "valueRange",
    "valueRatio", "valueSampledData", "valueTime", "valueDateTime", "valuePeriod",
    "dataAbsentReason", "interpretation", "note", "bodySite", "method", "specimen", "device",
    "referenceRange", "hasMember", "derivedFrom", "component",
}

FHIR_ID = r"[A-Za-z0-9\-.]{1,64}"
PATIENT_REF = re.compile(rf"^Patient/({FHIR_ID})$")
# FHIR dateTime with a time part; R4 requires a timezone whenever a time is given.
DATETIME_WITH_TZ = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{1,9})?(Z|[+-]\d{2}:\d{2})$")
FUTURE_TOLERANCE = timedelta(minutes=5)


@dataclass(frozen=True)
class VitalSpec:
    key: str
    loinc: str
    display: str
    profile: str
    units: dict[str, tuple[float, float]]  # UCUM code -> inclusive physical bounds
    unit_display: dict[str, str]


VITALS: dict[str, VitalSpec] = {
    s.loinc: s
    for s in (
        VitalSpec("heart_rate", "8867-4", "Heart rate", "http://hl7.org/fhir/StructureDefinition/heartrate",
                  {"/min": (0, 350)}, {"/min": "beats/minute"}),
        VitalSpec("spo2", "2708-6", "Oxygen saturation in Arterial blood", "http://hl7.org/fhir/StructureDefinition/oxygensat",
                  {"%": (0, 100)}, {"%": "%"}),
        VitalSpec("respiratory_rate", "9279-1", "Respiratory rate", "http://hl7.org/fhir/StructureDefinition/resprate",
                  {"/min": (0, 150)}, {"/min": "breaths/minute"}),
        VitalSpec("body_temperature", "8310-5", "Body temperature", "http://hl7.org/fhir/StructureDefinition/bodytemp",
                  {"Cel": (10, 50), "[degF]": (50, 122)}, {"Cel": "Cel", "[degF]": "degF"}),
    )
}


@dataclass(frozen=True)
class Issue:
    severity: str  # "error" | "warning"
    code: str      # FHIR IssueType code
    expression: str
    diagnostics: str

    def as_fhir(self) -> dict:
        return {"severity": self.severity, "code": self.code, "diagnostics": self.diagnostics, "expression": [self.expression]}


@dataclass
class ValidationResult:
    issues: list[Issue] = field(default_factory=list)
    spec: VitalSpec | None = None
    patient_id: str | None = None
    effective: datetime | None = None

    @property
    def ok(self) -> bool:
        return not any(i.severity == "error" for i in self.issues)

    def error(self, code: str, expression: str, diagnostics: str) -> None:
        self.issues.append(Issue("error", code, expression, diagnostics))


def _codings(cc) -> list[dict]:
    if not isinstance(cc, dict) or not isinstance(cc.get("coding"), list):
        return []
    return [c for c in cc["coding"] if isinstance(c, dict)]


def _is_number(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def validate_observation(resource, now: datetime | None = None) -> ValidationResult:
    now = now or datetime.now(timezone.utc)
    r = ValidationResult()

    if not isinstance(resource, dict):
        r.error("structure", "Observation", "Body must be a JSON object")
        return r
    if resource.get("resourceType") != "Observation":
        r.error("structure", "resourceType", f"resourceType must be 'Observation', got {resource.get('resourceType')!r}")
        return r

    unknown = sorted(k for k in resource if k not in R4_OBSERVATION_ELEMENTS and not k.startswith("_"))
    for k in unknown:
        r.error("structure", f"Observation.{k}", f"'{k}' is not an element of FHIR R4 Observation")
    if "id" in resource:
        r.error("invalid", "Observation.id", "id must not be supplied on create; the server assigns it")

    # status
    status = resource.get("status")
    if status is None:
        r.error("required", "Observation.status", "status is required")
    elif status not in R4_OBSERVATION_STATUS:
        r.error("code-invalid", "Observation.status", f"'{status}' is not a FHIR R4 ObservationStatus code")
    elif status not in ACCEPTED_STATUS:
        r.error("business-rule", "Observation.status", f"status '{status}' carries no usable measurement; accepted: {sorted(ACCEPTED_STATUS)}")

    # category: vital-signs
    cats = resource.get("category")
    if not isinstance(cats, list) or not any(
        c.get("system") == OBS_CATEGORY and c.get("code") == "vital-signs" for cat in cats for c in _codings(cat)
    ):
        r.error("required", "Observation.category", f"category must include {OBS_CATEGORY}#vital-signs")

    # code: exactly one supported LOINC coding
    loinc = [c for c in _codings(resource.get("code")) if c.get("system") == LOINC]
    supported = [c for c in loinc if c.get("code") in VITALS]
    if not _codings(resource.get("code")):
        r.error("required", "Observation.code", "code.coding is required")
    elif not supported:
        found = [f"{c.get('system')}#{c.get('code')}" for c in _codings(resource.get("code"))]
        r.error("not-supported", "Observation.code", f"code must contain one supported LOINC coding {sorted(VITALS)}; found {found}")
    elif len({c["code"] for c in supported}) > 1:
        r.error("invalid", "Observation.code", "code contains more than one supported LOINC vital-sign coding")
    else:
        r.spec = VITALS[supported[0]["code"]]

    # subject
    subject = resource.get("subject")
    ref = subject.get("reference") if isinstance(subject, dict) else None
    m = PATIENT_REF.match(ref) if isinstance(ref, str) else None
    if subject is None:
        r.error("required", "Observation.subject", "subject is required")
    elif not m:
        r.error("invalid", "Observation.subject.reference", f"subject.reference must be a relative 'Patient/<id>' reference, got {ref!r}")
    else:
        r.patient_id = m.group(1)

    # effective[x]
    other_effective = [k for k in ("effectivePeriod", "effectiveTiming", "effectiveInstant") if k in resource]
    eff = resource.get("effectiveDateTime")
    if other_effective:
        r.error("not-supported", f"Observation.{other_effective[0]}", "only effectiveDateTime is accepted for monitored vitals")
    if eff is None:
        r.error("required", "Observation.effectiveDateTime", "effectiveDateTime is required")
    elif not isinstance(eff, str) or not DATETIME_WITH_TZ.match(eff):
        r.error("invalid", "Observation.effectiveDateTime", f"effectiveDateTime must be a full date-time with seconds and timezone, got {eff!r}")
    else:
        try:
            when = datetime.fromisoformat(eff.replace("Z", "+00:00"))
        except ValueError:
            r.error("invalid", "Observation.effectiveDateTime", f"effectiveDateTime is not a real date-time: {eff!r}")
        else:
            if when > now + FUTURE_TOLERANCE:
                r.error("business-rule", "Observation.effectiveDateTime", f"effectiveDateTime {eff} is in the future")
            r.effective = when

    # value
    other_values = sorted(k for k in resource if k.startswith("value") and k != "valueQuantity")
    for k in other_values:
        r.error("not-supported", f"Observation.{k}", f"{k} is not accepted; vitals must use valueQuantity")
    if "dataAbsentReason" in resource:
        r.error("not-supported", "Observation.dataAbsentReason", "observations without a value are not accepted")
    if "component" in resource:
        r.error("not-supported", "Observation.component", "component is not used by the supported vital signs")
    q = resource.get("valueQuantity")
    if q is None:
        r.error("required", "Observation.valueQuantity", "valueQuantity is required")
    elif not isinstance(q, dict):
        r.error("structure", "Observation.valueQuantity", "valueQuantity must be an object")
    else:
        value, system, ucum, unit = q.get("value"), q.get("system"), q.get("code"), q.get("unit")
        if not _is_number(value):
            r.error("invalid", "Observation.valueQuantity.value", f"value must be a finite number, got {value!r}")
        if system != UCUM:
            r.error("invalid", "Observation.valueQuantity.system", f"system must be {UCUM}, got {system!r}")
        if not isinstance(unit, str) or not unit.strip():
            r.error("required", "Observation.valueQuantity.unit", "unit (human-readable) is required")
        if "comparator" in q:
            r.error("not-supported", "Observation.valueQuantity.comparator", "comparator values are not accepted")
        if r.spec:
            if ucum not in r.spec.units:
                r.error("code-invalid", "Observation.valueQuantity.code",
                        f"UCUM code for {r.spec.display} must be one of {sorted(r.spec.units)}, got {ucum!r}")
            elif _is_number(value):
                lo, hi = r.spec.units[ucum]
                if not lo <= value <= hi:
                    r.error("value", "Observation.valueQuantity.value",
                            f"{value} {ucum} is physically impossible for {r.spec.display} (allowed {lo}..{hi})")
    return r


def normalize(resource: dict, spec: VitalSpec) -> dict:
    """Copy of the resource with the R4 vital-sign profile and ingest tag declared in meta."""
    out = copy.deepcopy(resource)
    meta = out.setdefault("meta", {})
    profiles = meta.setdefault("profile", [])
    if spec.profile not in profiles:
        profiles.append(spec.profile)
    tags = meta.setdefault("tag", [])
    if not any(t.get("system") == INGEST_TAG["system"] and t.get("code") == INGEST_TAG["code"] for t in tags):
        tags.append(dict(INGEST_TAG))
    return out


def example_observation(loinc: str, patient_id: str, value: float, when: datetime, ucum: str | None = None) -> dict:
    """A valid R4 vital-sign Observation for the given LOINC code (used by tests and the simulator)."""
    spec = VITALS[loinc]
    ucum = ucum or next(iter(spec.units))
    return {
        "resourceType": "Observation",
        "status": "final",
        "category": [{"coding": [{"system": OBS_CATEGORY, "code": "vital-signs", "display": "Vital Signs"}], "text": "Vital Signs"}],
        "code": {"coding": [{"system": LOINC, "code": loinc, "display": spec.display}], "text": spec.display},
        "subject": {"reference": f"Patient/{patient_id}"},
        "effectiveDateTime": when.isoformat(timespec="seconds"),
        "valueQuantity": {"value": value, "unit": spec.unit_display[ucum], "system": UCUM, "code": ucum},
    }
