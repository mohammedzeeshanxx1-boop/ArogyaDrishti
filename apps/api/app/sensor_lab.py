"""Sensor Reliability Lab: false-alert metrics for the fixed-threshold comparator vs the existing engine.

Input is the unchanged step-by-step comparison from `early_detection.analyse` (existing detector on the stored
replay readings + the labelled fixed-threshold comparator) and the scenario's ground truth, which the replay
engine stores separately and which is read here only AFTER detection has run (evaluation only; never shown to
or used by the detector).

Definitions (applied identically to both systems):
- clinical alert: an alert episode, i.e. a step where the system goes from not alerting to alerting;
- false clinical alert: an episode whose start is not supported by genuine deterioration, i.e. it starts outside
  the scripted deterioration window, or every reading that triggered it is a labelled sensor artifact;
- sensor artifacts detected: labelled artifact readings the system classified as unreliable;
- genuine deterioration detected: an alert episode that starts inside the scripted deterioration window and is
  not triggered solely by artifact readings.
"""

from __future__ import annotations

from datetime import datetime

import asyncio

from . import detector, early_detection
from .evaluation import session_readings
from .replay import store


def _t(s: str) -> datetime:
    return detector.parse_time(s)


def _windows(truth: list[dict], label: str) -> list[tuple[datetime, datetime | None, str]]:
    return [(_t(w["start_at"]), _t(w["end_at"]) if w.get("end_at") else None, w.get("detail") or "") for w in truth if w["label"] == label]


def is_artifact(truth: list[dict], vital: str, at: datetime) -> bool:
    return any(start <= at < (end or at) and detail.endswith(f"on {vital}") for start, end, detail in _windows(truth, "artifact"))


def in_deterioration(truth: list[dict], at: datetime) -> bool:
    return any(start <= at and (end is None or at <= end) for start, end, _ in _windows(truth, "deterioration_onset"))


def metrics(a: dict, truth: list[dict]) -> dict:
    steps = a["steps"]
    has_det = bool(_windows(truth, "deterioration_onset"))
    start = _t(a["start"]) if a.get("start") else None

    def mins(i: int) -> float:
        return round((_t(steps[i]["t"]) - start).total_seconds() / 60, 1)

    # Labelled artifact readings in the stream (ground truth).
    labelled = [(i, v) for i, s in enumerate(steps) for v in s["readings"] if is_artifact(truth, v, _t(s["t"]))]

    # --- fixed-threshold comparator episodes
    comp_eps = []
    for i, s in enumerate(steps):
        if s["comparator"]["alarm"] and not (i > 0 and steps[i - 1]["comparator"]["alarm"]):
            at = _t(s["t"])
            only_artifacts = all(is_artifact(truth, b["vital"], at) for b in s["comparator"]["breaches"])
            false = only_artifacts or not in_deterioration(truth, at)
            comp_eps.append({"index": i, "minutes": mins(i), "false": false, "artifactOnly": only_artifacts,
                             "trigger": [b["text"] for b in s["comparator"]["breaches"]]})

    # --- engine episodes (existing risk levels)
    eng_eps = []
    for i, s in enumerate(steps):
        lvl = s["engine"]["level"]
        if lvl != "NORMAL" and not (i > 0 and steps[i - 1]["engine"]["level"] != "NORMAL"):
            at = _t(s["t"])
            vitals = {x["vital"] for x in s["engine"]["alerts"] if x.get("vital")}
            only_artifacts = bool(vitals) and all(is_artifact(truth, v, at) for v in vitals)
            false = only_artifacts or not in_deterioration(truth, at)
            eng_eps.append({"index": i, "minutes": mins(i), "level": lvl, "false": false, "artifactOnly": only_artifacts,
                            "trigger": [x["reason"] for x in s["engine"]["alerts"]][:3]})
    peak = max((s["engine"]["level"] for s in steps), key=lambda l: detector.RANK[l], default="NORMAL")

    # --- engine artifact classification vs labels
    sup = a["artifacts"]["suppressed"]
    sup_true = [x for x in sup if is_artifact(truth, x["vital"], _t(x["effective"]))]
    sup_false = [x for x in sup if not is_artifact(truth, x["vital"], _t(x["effective"]))]

    def genuine(eps):
        if not has_det:
            return {"applicable": False, "detected": None, "minutes": None, "level": None}
        g = next((e for e in eps if not e["false"]), None)
        return {"applicable": True, "detected": g is not None, "minutes": g["minutes"] if g else None, "level": g.get("level") if g else None}

    comp_false = sum(e["false"] for e in comp_eps)
    eng_false = sum(e["false"] for e in eng_eps)
    return {
        "definitions": __doc__.split("Definitions (applied identically to both systems):")[1].strip(),
        "labelledArtifactReadings": len(labelled),
        "scenarioHasDeterioration": has_det,
        "fixed": {"clinicalAlerts": len(comp_eps), "alarmReadings": sum(len(s["comparator"]["breaches"]) for s in steps),
                  "falseClinicalAlerts": comp_false, "artifactsDetected": None, "genuineDeterioration": genuine(comp_eps), "episodes": comp_eps},
        "engine": {"clinicalAlerts": len(eng_eps), "falseClinicalAlerts": eng_false, "peakLevel": peak,
                   "artifactsDetected": len(sup_true), "readingsFlaggedNotLabelled": len(sup_false),
                   "genuineDeterioration": genuine(eng_eps), "episodes": eng_eps},
        "falseAlertsAvoided": comp_false - eng_false if comp_false > eng_false else 0,
    }


async def evaluate_run(fhir, db_path: str, session_id: str, scale2: bool) -> dict:
    """Detection on the stored readings first; the scenario labels are read only afterwards (evaluation only)."""
    readings, _ = await session_readings(fhir, session_id)
    analysis = await asyncio.to_thread(early_detection.analyse, readings, scale2)
    truth = store.ground_truth(db_path, session_id)
    return {"analysis": analysis, "metrics": metrics(analysis, truth)}
