"""Scenario replay evaluation: fixed thresholds vs personalized detection.

For every replay session:
  1. read the session's Observations back FROM HAPI (the detector never sees anything else)
  2. replay them causally: at each measurement time, run the detector on readings up to that time
  3. turn the level timeline into alert episodes
  4. only then join with ground truth (evaluation-only) to compute metrics

Metrics (definitions are fixed here; nothing is hand-entered):
  * detection lead time: scripted "critical" time minus first REVIEW+ episode start after onset
    (positive = alerted before the scripted critical point); also onset-to-first-WATCH delay
  * alerts per patient-day: alert episodes (level >= WATCH) per 24 h of monitored time
  * false alert episodes: episodes starting inside a ground-truth "stable" or "artifact" window
  * FHIR compliance: Observations confirmed by HAPI / events, plus a live HAPI $validate of one
    stored Observation per vital
  * explainability: share of alerts (at episode starts) with level, rule, value, unit, reason and a
    triggering Observation id that exists among the session's stored Observations
"""

from __future__ import annotations

from datetime import datetime

from . import detector
from .fhir import FhirClient, summarize_outcome
from .replay import store
from .replay.persistence import SESSION_TAG_SYSTEM
from .risk import to_celsius as to_celsius_value
from .vitals import LOINC, VITALS

MODES = ("fixed", "personalized")
HISTORY = detector.BASELINE_WINDOW + detector.BASELINE_EXCLUDE + 5   # readings per vital the detector needs


async def session_readings(fhir: FhirClient, session_id: str) -> tuple[list[dict], dict[str, dict]]:
    obs = await fhir.search_by_date("Observation", {"_tag": f"{SESSION_TAG_SYSTEM}|{session_id}"})
    readings = []
    for o in obs:
        code = next((c["code"] for c in o.get("code", {}).get("coding", []) if c.get("system") == LOINC and c.get("code") in VITALS), None)
        if code is None:
            continue
        key = VITALS[code].key
        q = o["valueQuantity"]
        value = to_celsius_value(float(q["value"]), q.get("code", "")) if key == "body_temperature" else float(q["value"])
        readings.append({"vital": key, "value": value, "effective": o["effectiveDateTime"], "observation": f"Observation/{o['id']}"})
    return readings, {f"Observation/{o['id']}": o for o in obs}


def timeline(readings: list[dict], mode: str, scale2: bool) -> list[dict]:
    """Causal evaluation at each distinct measurement time."""
    by_time: dict[str, list[dict]] = {}
    for r in sorted(readings, key=lambda r: (detector.parse_time(r["effective"]), r["observation"])):
        by_time.setdefault(r["effective"], []).append(r)
    history: dict[str, list[dict]] = {}
    out = []
    for t, rows in by_time.items():
        for r in rows:
            history.setdefault(r["vital"], []).append(r)
            history[r["vital"]] = history[r["vital"]][-HISTORY:]
        res = detector.evaluate([r for v in history.values() for r in v], mode=mode, scale2=scale2)
        out.append({"t": detector.parse_time(t), "level": res["level"], "alerts": [a for a in res["alerts"] if a["level"] != "NORMAL"],
                    "suppressed": res["suppressedCount"]})
    return out


def episodes(tl: list[dict], min_level: str = "WATCH") -> list[dict]:
    eps, cur = [], None
    for step in tl:
        on = detector.RANK[step["level"]] >= detector.RANK[min_level]
        if on and cur is None:
            cur = {"start": step["t"], "end": step["t"], "peak": step["level"], "alerts": step["alerts"]}
        elif on:
            cur["end"] = step["t"]
            if detector.RANK[step["level"]] > detector.RANK[cur["peak"]]:
                cur["peak"] = step["level"]
        elif cur is not None:
            eps.append(cur); cur = None
    if cur is not None:
        eps.append(cur)
    return eps


def _in(t: datetime, w: dict) -> bool:
    return w["start"] <= t <= (w["end"] or w["start"])


def metrics(tl: list[dict], truth: list[dict], obs_ids: set[str]) -> dict:
    gt = [{"label": g["label"], "start": detector.parse_time(g["start_at"]), "end": detector.parse_time(g["end_at"]) if g["end_at"] else None} for g in truth]
    span_days = (tl[-1]["t"] - tl[0]["t"]).total_seconds() / 86400 if len(tl) > 1 else 0
    eps = episodes(tl, "WATCH")
    onset = next((g["start"] for g in gt if g["label"] == "deterioration_onset"), None)
    critical = next((g["start"] for g in gt if g["label"] == "critical"), None)
    quiet = [g for g in gt if g["label"] in ("stable", "artifact")]
    false_eps = [e for e in eps if any(_in(e["start"], w) for w in quiet) and not (onset and e["start"] >= onset)]
    artifact_eps = [e for e in false_eps if any(_in(e["start"], w) for w in gt if w["label"] == "artifact")]
    first_watch = next((e["start"] for e in eps if onset and e["start"] >= onset), None)
    first_review = next((s["t"] for s in tl if onset and s["t"] >= onset and detector.RANK[s["level"]] >= detector.RANK["REVIEW"]), None)
    alerts = [a for e in eps for a in e["alerts"]]
    complete = [a for a in alerts if a.get("level") and a.get("rule") and a.get("reason") and a.get("unit") is not None
                and a.get("value") is not None and all(o.strip() in obs_ids for o in str(a.get("observation", "")).split(","))]
    m = lambda d: None if d is None else round(d.total_seconds() / 60, 1)
    return {
        "monitoredDays": round(span_days, 4),
        "alertEpisodes": len(eps),
        "alertsPerPatientDay": round(len(eps) / span_days, 2) if span_days else None,
        "falseAlertEpisodes": len(false_eps),
        "artifactAlertEpisodes": len(artifact_eps),
        "onsetToFirstWatchMin": m(first_watch - onset) if onset and first_watch else None,
        "leadTimeBeforeCriticalMin": m(critical - first_review) if critical and first_review else None,
        "detectedBeforeCritical": (first_review <= critical) if critical and first_review else (False if critical else None),
        "explainedAlerts": len(complete), "alertsAtEpisodeStarts": len(alerts),
        "explainabilityPct": round(100 * len(complete) / len(alerts), 1) if alerts else None,
        "peakLevel": max((s["level"] for s in tl), key=detector.RANK.get) if tl else "NORMAL",
        "suppressedReadings": tl[-1]["suppressed"] if tl else 0,
    }


async def fhir_compliance(fhir: FhirClient, db_path: str, session_id: str, stored: dict[str, dict]) -> dict:
    rows = store.event_rows(db_path, session_id)
    row = store.session_row(db_path, session_id)
    sample, errors = [], 0
    for loinc, spec in VITALS.items():
        o = next((o for o in stored.values() if o["code"]["coding"][0]["code"] == loinc), None)
        if o:
            oo = summarize_outcome(await fhir.validate(o, spec.profile))
            errors += oo["errors"]
            sample.append({"observation": f"Observation/{o['id']}", "profile": spec.profile, "errors": oo["errors"], "warnings": oo["warnings"]})
    return {
        "events": row["events_total"] if row else None,
        "confirmedByHapi": len(rows),
        "storedInHapi": len(stored),
        "confirmedPct": round(100 * len(rows) / row["events_total"], 2) if row and row["events_total"] else None,
        "hapiValidateSample": sample,
        "sampleErrors": errors,
        "validationCoverage": "every Observation: strict local validator; HAPI $validate: one per vital at ingest + one per vital re-checked here",
    }


async def evaluate_session(fhir: FhirClient, db_path: str, session_id: str, scale2: bool) -> dict:
    """Detect first (from HAPI data only), then join ground truth for scoring."""
    readings, stored = await session_readings(fhir, session_id)
    row = store.session_row(db_path, session_id)
    if row and len(stored) != row["events_total"]:
        raise RuntimeError(f"session {session_id}: HAPI returned {len(stored)} Observations but {row['events_total']} were replayed; "
                           "refusing to compute metrics on incomplete data")
    timelines = {mode: timeline(readings, mode, scale2) for mode in MODES}
    truth = store.ground_truth(db_path, session_id)          # read only after detection has finished
    return {
        "sessionId": session_id,
        "observations": len(readings),
        "groundTruth": truth,
        "modes": {mode: metrics(tl, truth, set(stored)) for mode, tl in timelines.items()},
        "fhirCompliance": await fhir_compliance(fhir, db_path, session_id, stored),
    }
