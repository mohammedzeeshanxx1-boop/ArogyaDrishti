"""Early Detection Lab: the existing personalized engine vs a simple fixed-threshold comparator on the SAME readings.

This module does not score anything itself on the Arogya Drishti side. For every measurement time of a replayed
scenario (readings read back from HAPI by session tag) it calls the existing `detector.evaluate(..., "personalized")`
causally, exactly like `evaluation.timeline`, and records what the engine reported.

The comparator is deliberately simple and explicitly labelled: each raw reading is checked on its own against fixed
alarm limits (no personal baseline, no trend, no artifact filtering). It is a demonstration comparator, not a model
of all traditional clinical monitoring.
"""

from __future__ import annotations

from . import detector
from .evaluation import HISTORY

# Demonstration comparator: single-reading fixed alarm limits.
FIXED_LIMITS: dict[str, dict[str, float]] = {
    "spo2": {"low": 90},
    "heart_rate": {"low": 50, "high": 120},
    "respiratory_rate": {"low": 8, "high": 30},
    "body_temperature": {"high": 39.0},
}
LABELS = {"heart_rate": ("Heart rate", "bpm"), "spo2": ("SpO₂", "%"), "respiratory_rate": ("Respiratory rate", "breaths/min"),
          "body_temperature": ("Temperature", "°C")}
COMPARATOR = {
    "name": "Fixed-threshold comparator (demo)",
    "description": "Checks every raw reading on its own against fixed alarm limits: SpO₂ < 90 %, heart rate < 50 or > 120 bpm, "
                   "respiratory rate < 8 or > 30 breaths/min, temperature > 39.0 °C. No personal baseline, no trend analysis, "
                   "no sensor-artifact filtering. A simple comparator for this demonstration, not a model of all traditional monitoring.",
    "limits": FIXED_LIMITS,
}


def breach(vital: str, value: float) -> str | None:
    lim = FIXED_LIMITS.get(vital, {})
    label, unit = LABELS[vital]
    if "low" in lim and value < lim["low"]:
        return f"{label} {value:g} {unit} below {lim['low']:g}"
    if "high" in lim and value > lim["high"]:
        return f"{label} {value:g} {unit} above {lim['high']:g}"
    return None


def _alert(a: dict) -> dict:
    return {k: a.get(k) for k in ("level", "ruleType", "vital", "vitalLabel", "value", "unit", "rule", "reason", "score", "observation")} | {
        "baseline": ({"median": a["baseline"]["median"], "mad": a["baseline"]["mad"], "n": a["baseline"]["n"]} if a.get("baseline") else None)}


def analyse(readings: list[dict], scale2: bool = False) -> dict:
    """Causal step-by-step comparison over one replayed scenario."""
    by_time: dict[str, list[dict]] = {}
    for r in sorted(readings, key=lambda r: (detector.parse_time(r["effective"]), r["observation"])):
        by_time.setdefault(r["effective"], []).append(r)
    history: dict[str, list[dict]] = {}
    latest: dict[str, float] = {}
    suppressed_all: dict[str, dict] = {}
    steps = []
    for t, rows in by_time.items():
        for r in rows:
            history.setdefault(r["vital"], []).append(r)
            history[r["vital"]] = history[r["vital"]][-HISTORY:]
            latest[r["vital"]] = r["value"]
        res = detector.evaluate([r for v in history.values() for r in v], mode="personalized", scale2=scale2)
        # Readings the Sensor Trust Engine newly classifies as artifacts at this step. A spike is classified once the
        # following reading shows it reverted, so it can be reported one step after it arrived.
        sup_now = [x for x in res["suppressed"] if x["observation"] not in suppressed_all]
        for x in sup_now:
            suppressed_all[x["observation"]] = x
        breaches = [{"vital": r["vital"], "value": r["value"], "observation": r["observation"], "text": b}
                    for r in rows if (b := breach(r["vital"], r["value"]))]
        alerts = [_alert(a) for a in res["alerts"] if a["level"] != "NORMAL"]
        spo2_param = res["news2"]["parameters"].get("spo2") or {}
        steps.append({
            "t": detector.parse_time(t).isoformat(),
            "readings": {r["vital"]: r["value"] for r in rows},
            "latest": dict(latest),
            "comparator": {"alarm": bool(breaches), "breaches": breaches},
            "engine": {"level": res["level"], "news2": res["news2"]["total"], "measured": res["news2"]["measuredParameters"],
                       "alerts": alerts, "trend": any(a["ruleType"] == "personal-baseline" for a in alerts),
                       "suppressedNow": [{"vital": s["vital"], "value": s["value"], "reason": s["reason"], "observation": s["observation"]} for s in sup_now]},
            "spo2Baseline": (spo2_param.get("baseline") or {}).get("median"),
        })

    def first(pred):
        return next((i for i, s in enumerate(steps) if pred(s)), None)

    i_engine = first(lambda s: s["engine"]["level"] != "NORMAL")
    i_trend = first(lambda s: s["engine"]["trend"])
    i_comp = first(lambda s: s["comparator"]["alarm"])
    start = steps[0]["t"] if steps else None

    def marker(i, kind):
        if i is None:
            return None
        s = steps[i]
        mins = (detector.parse_time(s["t"]) - detector.parse_time(start)).total_seconds() / 60
        return {"index": i, "t": s["t"], "minutesFromStart": round(mins, 1), "latest": s["latest"],
                **({"level": s["engine"]["level"], "news2": s["engine"]["news2"], "alerts": s["engine"]["alerts"]} if kind == "engine"
                   else {"breaches": s["comparator"]["breaches"]})}

    fw, fc = marker(i_engine, "engine"), marker(i_comp, "comparator")
    advantage = round(fc["minutesFromStart"] - fw["minutesFromStart"], 1) if fw and fc else None
    # Comparator alarms raised by readings the engine classified as likely sensor artifacts.
    artifact_alarms = [b | {"t": s["t"], "reason": suppressed_all[b["observation"]]["reason"]}
                       for s in steps for b in s["comparator"]["breaches"] if b["observation"] in suppressed_all]
    clinical_alerts_during_artifacts = sum(1 for s in steps if any(x["observation"] in suppressed_all for x in s["comparator"]["breaches"])
                                           and s["engine"]["level"] != "NORMAL")
    return {
        "comparator": COMPARATOR,
        "engine": {"name": "Arogya Drishti personalized engine",
                   "description": "Existing engine: Sensor Trust Engine (artifact suppression), partial NEWS2-style score (4 of 7 parameters), "
                                  "personal baselines (median/MAD) and trend deviation rules. Decision support only; not clinically validated."},
        "start": start, "end": steps[-1]["t"] if steps else None, "steps": steps,
        "firstWarning": fw, "firstTrendWarning": marker(i_trend, "engine"), "firstComparatorAlert": fc,
        "advantageMinutes": advantage,
        "comparatorAlarmSteps": sum(1 for s in steps if s["comparator"]["alarm"]),
        "engineAlertSteps": sum(1 for s in steps if s["engine"]["level"] != "NORMAL"),
        "artifacts": {"suppressed": list(suppressed_all.values()), "comparatorAlarmsFromArtifacts": artifact_alarms,
                      "engineAlertsDuringArtifacts": clinical_alerts_during_artifacts},
    }
