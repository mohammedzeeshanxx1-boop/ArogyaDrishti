"""Prototype risk rules engine (Round 1 MVP).

Deterministic, explainable rules over a patient's own stored observations.
This is NOT NEWS2 and is NOT clinically validated: thresholds are simplified
bands chosen for a demonstration. Inputs are only current and past
observations (value, time, Observation id); the engine never sees which
simulator scenario produced them.
"""

from __future__ import annotations

from collections import defaultdict

LEVELS = ["NORMAL", "WATCH", "REVIEW", "URGENT"]
RANK = {lvl: i for i, lvl in enumerate(LEVELS)}
RULES_LABEL = "Prototype rules engine (Round 1 MVP): simplified thresholds and trends. Not NEWS2. Not clinically validated."

VITAL_LABEL = {
    "heart_rate": ("Heart rate", "/min"),
    "spo2": ("SpO2", "%"),
    "respiratory_rate": ("Respiratory rate", "/min"),
    "body_temperature": ("Temperature", "°C"),
}

# Ordered most severe first; the first matching band wins.
THRESHOLDS: dict[str, list[tuple[str, str, float]]] = {
    "heart_rate": [("URGENT", ">=", 131), ("URGENT", "<=", 40), ("REVIEW", ">=", 111), ("REVIEW", "<=", 45), ("WATCH", ">=", 100), ("WATCH", "<=", 50)],
    "spo2": [("URGENT", "<=", 91), ("REVIEW", "<=", 93), ("WATCH", "<=", 95)],
    "respiratory_rate": [("URGENT", ">=", 30), ("URGENT", "<=", 8), ("REVIEW", ">=", 25), ("WATCH", ">=", 21), ("WATCH", "<=", 11)],
    "body_temperature": [("REVIEW", ">=", 39.1), ("REVIEW", "<=", 35.0), ("WATCH", ">=", 38.0), ("WATCH", "<=", 36.0)],
}

# Trend rule: latest reading vs the first of the last TREND_WINDOW readings.
TREND_WINDOW = 6
TRENDS: dict[str, tuple[str, float]] = {
    "heart_rate": ("rise", 15),
    "spo2": ("fall", 3),
    "respiratory_rate": ("rise", 5),
    "body_temperature": ("rise", 1.0),
}
MULTI_PARAMETER_COUNT = 3  # this many vitals at WATCH or worse -> at least REVIEW


def to_celsius(value: float, ucum: str) -> float:
    return round((value - 32) * 5 / 9, 2) if ucum == "[degF]" else value


def _fmt(v: float) -> str:
    return f"{v:g}"


def _match(value: float, op: str, limit: float) -> bool:
    return value >= limit if op == ">=" else value <= limit


def evaluate(readings: list[dict]) -> dict:
    """readings: [{vital, value, effective, observation}] in any order; value in the units of VITAL_LABEL."""
    series: dict[str, list[dict]] = defaultdict(list)
    for r in sorted(readings, key=lambda r: (r["effective"], r["observation"])):
        series[r["vital"]].append(r)

    alerts: list[dict] = []
    abnormal: list[dict] = []
    for vital, rows in series.items():
        label, unit = VITAL_LABEL[vital]
        latest = rows[-1]
        for level, op, limit in THRESHOLDS[vital]:
            if _match(latest["value"], op, limit):
                rule = f"{label} {'≥' if op == '>=' else '≤'} {_fmt(limit)} {unit}"
                alert = {
                    "level": level, "ruleType": "threshold", "vital": vital, "vitalLabel": label,
                    "value": latest["value"], "unit": unit, "rule": rule,
                    "observation": latest["observation"], "effective": latest["effective"],
                    "reason": f"Latest {label if label == 'SpO2' else label.lower()} {_fmt(latest['value'])} {unit} meets the {level} band ({rule}).",
                }
                alerts.append(alert)
                abnormal.append(alert)
                break
        window = rows[-TREND_WINDOW:]
        if len(window) >= 3:
            direction, delta = TRENDS[vital]
            first = window[0]
            change = latest["value"] - first["value"]
            if (direction == "rise" and change >= delta) or (direction == "fall" and -change >= delta):
                verb = "rose" if direction == "rise" else "fell"
                alerts.append({
                    "level": "WATCH", "ruleType": "trend", "vital": vital, "vitalLabel": label,
                    "value": latest["value"], "unit": unit,
                    "rule": f"{label} {direction} ≥ {_fmt(delta)} {unit} within the last {TREND_WINDOW} readings",
                    "observation": latest["observation"], "effective": latest["effective"],
                    "fromObservation": first["observation"], "fromValue": first["value"],
                    "reason": f"{label} {verb} from {_fmt(first['value'])} to {_fmt(latest['value'])} {unit} "
                              f"over {len(window)} readings ({first['observation']} → {latest['observation']}).",
                })

    if len(abnormal) >= MULTI_PARAMETER_COUNT:
        names = ", ".join(a["vitalLabel"] for a in abnormal)
        alerts.append({
            "level": "REVIEW", "ruleType": "multi-parameter", "vital": None, "vitalLabel": "Multiple vitals",
            "value": len(abnormal), "unit": "vitals",
            "rule": f"≥ {MULTI_PARAMETER_COUNT} vitals at WATCH or worse at the same time",
            "observation": ", ".join(a["observation"] for a in abnormal),
            "effective": max(a["effective"] for a in abnormal),
            "reason": f"{len(abnormal)} vitals are abnormal together ({names}).",
        })

    alerts.sort(key=lambda a: (-RANK[a["level"]], a["ruleType"] != "threshold", a["vitalLabel"]))
    level = alerts[0]["level"] if alerts else "NORMAL"
    return {
        "level": level,
        "alerts": alerts,
        "readingsConsidered": len(readings),
        "label": RULES_LABEL,
        "summary": alerts[0]["reason"] if alerts else (
            "All latest vitals are inside the prototype normal bands." if readings else "No observations in this monitoring window yet."
        ),
    }
