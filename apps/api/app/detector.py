"""Detection engine: Sensor Trust Engine -> NEWS2-style score -> personalized baseline rules.

Inputs are ONLY readings derived from stored FHIR Observations:
  {vital, value, effective (ISO), observation}  plus a patient-level `scale2` decision
  that itself comes from a FHIR Flag (see scale2.py). No scenario or ground truth.

NEWS2 source and honesty
  Bands below are transcribed from the Royal College of Physicians NEWS2 chart (2017).
  The chart PDF is NOT yet in the repository (rcp.ac.uk blocks automated download), so the
  transcription is UNVERIFIED against a local copy. Only 4 of 7 NEWS2 parameters are
  measured (RR, SpO2, pulse, temperature). Systolic BP, air/oxygen and consciousness are
  not available, so the aggregate is PARTIAL and can only under-estimate a full NEWS2.
  Supplemental oxygen is unknown; Scale 2 readings >= 93 % are scored as on room air (0).
  This is a decision-support prototype, not a validated clinical score.

Modes
  "fixed":         NEWS2-style on every reading (no artifact suppression, no personalization)
  "personalized":  Sensor Trust Engine + NEWS2-style + baseline rules (with a safety floor)
"""

from __future__ import annotations

import statistics
from collections import defaultdict
from datetime import datetime

LEVELS = ["NORMAL", "WATCH", "REVIEW", "URGENT"]
RANK = {lvl: i for i, lvl in enumerate(LEVELS)}
VITAL_LABEL = {
    "heart_rate": ("Heart rate", "/min"),
    "spo2": ("SpO2", "%"),
    "respiratory_rate": ("Respiratory rate", "/min"),
    "body_temperature": ("Temperature", "°C"),
}
LABEL = ("NEWS2-style score (partial: 4 of 7 parameters; RCP 2017 bands transcribed, not yet verified against the chart PDF) "
         "+ Sensor Trust Engine + personalized baselines. Decision support prototype, not clinically validated.")


# ------------------------------------------------------------------ NEWS2-style parameter scores
def score_rr(v: float) -> int:
    if v <= 8: return 3
    if v <= 11: return 1
    if v <= 20: return 0
    if v <= 24: return 2
    return 3


def score_spo2_scale1(v: float) -> int:
    if v <= 91: return 3
    if v <= 93: return 2
    if v <= 95: return 1
    return 0


def score_spo2_scale2(v: float) -> int:
    # 88-92 is the target range; >= 93 on room air scores 0 (oxygen status not measured).
    if v <= 83: return 3
    if v <= 85: return 2
    if v <= 87: return 1
    return 0


def score_pulse(v: float) -> int:
    if v <= 40: return 3
    if v <= 50: return 1
    if v <= 90: return 0
    if v <= 110: return 1
    if v <= 130: return 2
    return 3


def score_temp(v: float) -> int:
    if v <= 35.0: return 3
    if v <= 36.0: return 1
    if v <= 38.0: return 0
    if v <= 39.0: return 1
    return 2


BANDS_TEXT = {
    "respiratory_rate": "RR ≤8:3 · 9–11:1 · 12–20:0 · 21–24:2 · ≥25:3",
    "spo2_scale1": "SpO2 Scale 1 ≤91:3 · 92–93:2 · 94–95:1 · ≥96:0",
    "spo2_scale2": "SpO2 Scale 2 ≤83:3 · 84–85:2 · 86–87:1 · ≥88:0 (room air assumed)",
    "heart_rate": "Pulse ≤40:3 · 41–50:1 · 51–90:0 · 91–110:1 · 111–130:2 · ≥131:3",
    "body_temperature": "Temp ≤35.0:3 · 35.1–36.0:1 · 36.1–38.0:0 · 38.1–39.0:1 · ≥39.1:2",
}


def parameter_score(vital: str, value: float, scale2: bool) -> tuple[int, str]:
    if vital == "respiratory_rate":
        return score_rr(value), BANDS_TEXT["respiratory_rate"]
    if vital == "spo2":
        return (score_spo2_scale2(value), BANDS_TEXT["spo2_scale2"]) if scale2 else (score_spo2_scale1(value), BANDS_TEXT["spo2_scale1"])
    if vital == "heart_rate":
        return score_pulse(value), BANDS_TEXT["heart_rate"]
    return score_temp(value), BANDS_TEXT["body_temperature"]


def level_from_news2(total: int, any_three: bool) -> str:
    """Mapping (documented): 0 NORMAL; 1-4 WATCH (low); single parameter 3 or 5-6 REVIEW (urgent ward review); >=7 URGENT."""
    if total >= 7:
        return "URGENT"
    if total >= 5 or any_three:
        return "REVIEW"
    if total >= 1:
        return "WATCH"
    return "NORMAL"


# ------------------------------------------------------------------ Sensor Trust Engine
# Plausibility: values a wearable can report but a living, monitored patient almost never has.
PLAUSIBLE = {"heart_rate": (25, 250), "spo2": (50, 100), "respiratory_rate": (4, 60), "body_temperature": (33.0, 42.5)}
# Largest believable change between consecutive readings (per step); bigger isolated jumps are spikes.
MAX_STEP = {"heart_rate": 35, "spo2": 8, "respiratory_rate": 12, "body_temperature": 1.0}


def trust(series: dict[str, list[dict]]) -> dict[str, list[dict]]:
    """Annotate each reading with trusted (bool) and trust_reason. Deterministic, uses only the series."""
    out: dict[str, list[dict]] = {}
    hr_zero_times = {r["effective"] for r in series.get("heart_rate", []) if r["value"] == 0}
    spo2_zero_times = {r["effective"] for r in series.get("spo2", []) if r["value"] == 0}
    for vital, rows in series.items():
        lo, hi = PLAUSIBLE[vital]
        annotated: list[dict] = []
        last_trusted = None
        for i, r in enumerate(rows):
            reason = None
            if r["value"] == 0 and vital in ("heart_rate", "spo2"):
                other = spo2_zero_times if vital == "heart_rate" else hr_zero_times
                reason = "probe-off: zero reading" + (" (HR and SpO2 both zero)" if r["effective"] in other else "")
            elif not lo <= r["value"] <= hi:
                reason = f"physiologically implausible ({r['value']} outside {lo}–{hi})"
            elif last_trusted is not None and abs(r["value"] - last_trusted["value"]) > MAX_STEP[vital]:
                nxt = rows[i + 1] if i + 1 < len(rows) else None
                if nxt is None:
                    reason = f"unconfirmed jump of {abs(r['value'] - last_trusted['value']):g} (held until the next reading)"
                elif abs(nxt["value"] - last_trusted["value"]) <= MAX_STEP[vital]:
                    reason = f"isolated spike of {abs(r['value'] - last_trusted['value']):g} that reverted (motion artifact)"
            annotated.append({**r, "trusted": reason is None, "trust_reason": reason})
            if reason is None:
                last_trusted = r
        out[vital] = annotated
    return out


# ------------------------------------------------------------------ personalized baselines
BASELINE_WINDOW = 100     # most recent trusted readings considered for the baseline
BASELINE_EXCLUDE = 10     # excluded newest readings (the baseline describes the past, not now)
BASELINE_MIN = 20         # warm-up: personalization inactive below this many baseline readings
DEVIATION_K = 4.0         # robust z (in MAD units) for the deviation rule
MIN_DELTA = {"heart_rate": 12, "spo2": 3, "respiratory_rate": 4, "body_temperature": 0.6}
WORSE = {"heart_rate": 1, "spo2": -1, "respiratory_rate": 1, "body_temperature": 1}


def baseline(rows: list[dict]) -> dict | None:
    trusted = [r for r in rows if r.get("trusted", True)]
    pool = trusted[:-BASELINE_EXCLUDE][-BASELINE_WINDOW:] if len(trusted) > BASELINE_EXCLUDE else []
    if len(pool) < BASELINE_MIN:
        return None
    vals = [r["value"] for r in pool]
    med = statistics.median(vals)
    mad = statistics.median([abs(v - med) for v in vals])
    return {"median": round(med, 2), "mad": round(mad, 2), "n": len(vals), "from": pool[0]["effective"], "to": pool[-1]["effective"]}


# ------------------------------------------------------------------ evaluation
def _alert(level, rule_type, vital, value, unit, rule, obs, effective, reason, **extra) -> dict:
    label = VITAL_LABEL[vital][0] if vital else "NEWS2-style aggregate"
    return {"level": level, "ruleType": rule_type, "vital": vital, "vitalLabel": label, "value": value, "unit": unit,
            "rule": rule, "observation": obs, "effective": effective, "reason": reason, **extra}


def evaluate(readings: list[dict], mode: str = "personalized", scale2: bool = False) -> dict:
    if mode not in ("fixed", "personalized"):
        raise ValueError("mode must be 'fixed' or 'personalized'")
    series: dict[str, list[dict]] = defaultdict(list)
    for r in sorted(readings, key=lambda r: (r["effective"], r["observation"])):
        series[r["vital"]].append(r)
    if mode == "personalized":
        series = trust(series)
    else:
        series = {k: [{**r, "trusted": True, "trust_reason": None} for r in v] for k, v in series.items()}

    alerts: list[dict] = []
    suppressed: list[dict] = []
    params: dict[str, dict] = {}
    for vital, rows in series.items():
        for r in rows:
            if not r["trusted"]:
                suppressed.append({"vital": vital, "value": r["value"], "observation": r["observation"],
                                   "effective": r["effective"], "reason": r["trust_reason"]})
        trusted = [r for r in rows if r["trusted"]]
        if not trusted:
            continue
        latest = trusted[-1]
        s, bands = parameter_score(vital, latest["value"], scale2)
        params[vital] = {"score": s, "value": latest["value"], "observation": latest["observation"],
                         "effective": latest["effective"], "bands": bands,
                         "scale": (2 if scale2 else 1) if vital == "spo2" else None,
                         "baseline": baseline(rows) if mode == "personalized" else None}

    total = sum(p["score"] for p in params.values())
    any_three = any(p["score"] == 3 for p in params.values())
    news2_level = level_from_news2(total, any_three) if params else "NORMAL"

    # Personalization rule 2 (chronic-baseline tolerance): a parameter scoring exactly 1 whose own
    # baseline already scores 1 and that has not moved from it does not, on its own, raise WATCH.
    tolerated: set[str] = set()
    if mode == "personalized":
        for vital, p in params.items():
            b = p["baseline"]
            if p["score"] == 1 and b and parameter_score(vital, b["median"], scale2)[0] == 1 \
                    and abs(p["value"] - b["median"]) < max(DEVIATION_K * b["mad"], MIN_DELTA[vital]):
                tolerated.add(vital)
    effective_total = total - len(tolerated)
    if tolerated and not any_three and effective_total == 0:
        news2_level = "NORMAL"   # safety floor: never applies when any parameter scores 3 or aggregate >= 5

    unit = lambda v: VITAL_LABEL[v][1]
    for vital, p in params.items():
        if p["score"] > 0:
            tol = vital in tolerated and news2_level == "NORMAL"
            lvl = "REVIEW" if p["score"] == 3 else "WATCH"
            alerts.append(_alert(
                "NORMAL" if tol else lvl, "news2-parameter", vital, p["value"], unit(vital),
                f"{p['bands']}" + (f" (SpO2 Scale {p['scale']})" if p["scale"] else ""), p["observation"], p["effective"],
                f"{VITAL_LABEL[vital][0]} {p['value']:g} {unit(vital)} scores {p['score']}"
                + (" — at this patient's own baseline, tolerated (personalization rule 2)" if tol else "") + ".",
                score=p["score"]))
    if params:
        alerts.append(_alert(
            news2_level, "news2-aggregate", None, total, "points",
            "Aggregate 0 NORMAL · 1–4 WATCH · single 3 or 5–6 REVIEW · ≥7 URGENT",
            ", ".join(p["observation"] for p in params.values()), max(p["effective"] for p in params.values()),
            f"NEWS2-style partial aggregate {total} (from {len(params)} of 7 parameters"
            + (f"; {', '.join(VITAL_LABEL[v][0] for v in tolerated)} tolerated at personal baseline" if tolerated else "")
            + (f"; a single parameter scores 3" if any_three else "") + ").",
            score=total))

    # Personalization rule 1 (deviation from own baseline): sustained worsening of >= k·MAD (and a minimum
    # absolute change) over the median of the last 3 trusted readings raises at least WATCH, even when
    # the NEWS2-style score has not changed.
    personal_level = "NORMAL"
    if mode == "personalized":
        for vital, p in params.items():
            b = p["baseline"]
            if not b:
                continue
            recent = [r["value"] for r in series[vital] if r["trusted"]][-3:]
            if len(recent) < 3:
                continue
            cur = statistics.median(recent)
            delta = (cur - b["median"]) * WORSE[vital]
            threshold = max(DEVIATION_K * b["mad"], MIN_DELTA[vital])
            if delta >= threshold:
                personal_level = "WATCH"
                alerts.append(_alert(
                    "WATCH", "personal-baseline", vital, cur, unit(vital),
                    f"median of last 3 deviates ≥ max({DEVIATION_K:g}×MAD, {MIN_DELTA[vital]:g}) from personal baseline",
                    p["observation"], p["effective"],
                    f"{VITAL_LABEL[vital][0]} {cur:g} vs personal baseline {b['median']:g} (MAD {b['mad']:g}, "
                    f"{b['n']} readings {b['from'][11:16]}–{b['to'][11:16]}): worse by {delta:g} ≥ {threshold:g}.",
                    baseline=b))

    level = max([news2_level, personal_level], key=RANK.get)
    shown = [a for a in alerts if a["level"] != "NORMAL"] + [a for a in alerts if a["level"] == "NORMAL" and a["ruleType"] == "news2-parameter"]
    shown.sort(key=lambda a: (-RANK[a["level"]], a["ruleType"] != "news2-aggregate", a["vitalLabel"]))
    top = next((a for a in shown if a["level"] == level and level != "NORMAL"), None)
    return {
        "level": level,
        "mode": mode,
        "alerts": shown,
        "suppressed": suppressed[-20:],
        "suppressedCount": len(suppressed),
        "news2": {"total": total, "level": news2_level, "parameters": params, "measuredParameters": len(params),
                  "of": 7, "partial": True, "spo2Scale": 2 if scale2 else 1,
                  "notAvailable": ["systolic blood pressure", "air or oxygen", "consciousness (ACVPU)"]},
        "readingsConsidered": len(readings),
        "label": LABEL,
        "summary": top["reason"] if top else (
            ("All latest trusted vitals score 0." if params else "No observations in this monitoring window yet.")
            + (f" {len(suppressed)} reading(s) suppressed as sensor artifacts." if suppressed else "")),
    }


def parse_time(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))
