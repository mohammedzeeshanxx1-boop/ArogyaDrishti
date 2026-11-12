"""Seeded scenario definitions.

A scenario turns (seed, anchor) into two SEPARATE outputs:
  * measurement events: what a wearable would report (vital, value, unit, measured_at)
  * ground truth: labelled annotations (e.g. deterioration onset) for evaluation only

Identical (scenario, seed, anchor, duration, interval) -> identical events, byte for byte.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import random
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta

from ..vitals import VITALS

LOINC_BY_KEY = {spec.key: loinc for loinc, spec in VITALS.items()}
UCUM_BY_KEY = {"heart_rate": "/min", "spo2": "%", "respiratory_rate": "/min", "body_temperature": "Cel"}
DECIMALS = {"heart_rate": 0, "spo2": 0, "respiratory_rate": 0, "body_temperature": 1}
VITAL_ORDER = ("heart_rate", "spo2", "respiratory_rate", "body_temperature")


@dataclass(frozen=True)
class MeasurementEvent:
    """Detector-visible input. Deliberately has no label, scenario or onset field."""
    seq: int
    vital: str
    loinc: str
    value: float
    ucum: str
    measured_at: datetime
    source: str  # "simulated" | "bidmc"

    def key(self) -> tuple:
        return (self.seq, self.vital, self.loinc, self.value, self.ucum, self.measured_at.isoformat(), self.source)


@dataclass(frozen=True)
class GroundTruth:
    """Evaluation-only annotation. Never written to FHIR or passed to the detector."""
    label: str                 # e.g. "deterioration_onset", "stable"
    start: datetime
    end: datetime | None
    detail: str = ""


@dataclass(frozen=True)
class VitalCurve:
    baseline: float
    target: float      # value reached at the end (equals baseline when flat)
    noise: float       # +/- uniform noise amplitude
    lo: float          # clamp to physical range
    hi: float


@dataclass(frozen=True)
class ScenarioSpec:
    id: str
    name: str
    description: str
    default_seed: int
    default_duration_minutes: int
    default_interval_seconds: int
    curves: dict[str, VitalCurve]
    onset_fraction: float | None = None   # fraction of duration where deterioration starts (ground truth)
    shape: float = 1.4                    # curvature of the deterioration ramp
    tags: tuple[str, ...] = field(default_factory=tuple)
    # Injected sensor artifacts: (fraction of duration, vital, kind, amount, steps). Kinds: "zero" (probe off)
    # or "spike" (amount added for `steps` readings). Each injection becomes an "artifact" ground-truth window.
    artifacts: tuple[tuple[float, str, str, float, int], ...] = ()

    def public(self) -> dict:
        # No ground-truth detail (onset) is exposed here.
        return {"id": self.id, "name": self.name, "description": self.description, "defaultSeed": self.default_seed,
                "defaultDurationMinutes": self.default_duration_minutes, "defaultIntervalSeconds": self.default_interval_seconds,
                "vitals": list(self.curves)}


SCENARIOS: dict[str, ScenarioSpec] = {
    s.id: s for s in (
        ScenarioSpec(
            id="stable", name="Stable Recovery",
            description="Vitals stay near a normal resting baseline with small seeded noise.",
            default_seed=1001, default_duration_minutes=120, default_interval_seconds=60,
            curves={
                "heart_rate": VitalCurve(74, 74, 3, 30, 220),
                "spo2": VitalCurve(97, 97, 1, 70, 100),
                "respiratory_rate": VitalCurve(15, 15, 1, 6, 60),
                "body_temperature": VitalCurve(36.8, 36.8, 0.15, 34, 42),
            },
        ),
        ScenarioSpec(
            id="deterioration", name="Gradual Deterioration",
            description="Normal vitals, then a progressive multi-parameter deterioration.",
            default_seed=2002, default_duration_minutes=120, default_interval_seconds=60,
            curves={
                "heart_rate": VitalCurve(78, 132, 2, 30, 220),
                "spo2": VitalCurve(97, 88, 0.7, 70, 100),
                "respiratory_rate": VitalCurve(16, 31, 0.8, 6, 60),
                "body_temperature": VitalCurve(37.0, 39.2, 0.08, 34, 42),
            },
            onset_fraction=0.35,
        ),
    )
}

_ARTIFACTS = (
    (0.15, "heart_rate", "spike", 60, 1), (0.30, "spo2", "zero", 0, 3), (0.30, "heart_rate", "zero", 0, 3),
    (0.45, "spo2", "spike", -16, 1), (0.60, "respiratory_rate", "spike", 20, 1), (0.75, "heart_rate", "spike", 55, 1),
    (0.90, "body_temperature", "spike", -4.5, 1),
)
SCENARIOS["artifact"] = dataclasses.replace(
    SCENARIOS["stable"], id="artifact", name="Stable with Sensor Artifacts", default_seed=3003,
    description="Stable vitals with injected probe-off episodes and motion spikes.", artifacts=_ARTIFACTS)
SCENARIOS["deterioration_artifact"] = dataclasses.replace(
    SCENARIOS["deterioration"], id="deterioration_artifact", name="Deterioration with Sensor Artifacts", default_seed=4004,
    description="Gradual deterioration with the same injected artifacts.", artifacts=_ARTIFACTS[:-1])


def _critical(vals: dict[str, float]) -> bool:
    """Scenario-defined severity, ground truth for lead time ONLY: the noise-free scripted curve has at least
    two of SpO2 <= 91 %, pulse >= 131 /min, RR >= 25 /min. A property of the script, computed without the detector."""
    return sum((vals["spo2"] <= 91, vals["heart_rate"] >= 131, vals["respiratory_rate"] >= 25)) >= 2


def generate(spec: ScenarioSpec, seed: int, anchor: datetime, duration_minutes: int, interval_seconds: int,
             source: str = "simulated") -> tuple[list[MeasurementEvent], list[GroundTruth]]:
    if interval_seconds <= 0 or duration_minutes <= 0:
        raise ValueError("duration and interval must be positive")
    steps = int(duration_minutes * 60 // interval_seconds) + 1
    rng = random.Random(seed)
    onset_step = int(round(spec.onset_fraction * (steps - 1))) if spec.onset_fraction is not None else None
    events: list[MeasurementEvent] = []
    seq = 0
    art_steps: dict[tuple[int, str], tuple[str, float]] = {}
    truth_art: list[GroundTruth] = []
    for frac, vital, kind, amount, n in spec.artifacts:
        s0 = int(round(frac * (steps - 1)))
        for k in range(n):
            art_steps[(s0 + k, vital)] = (kind, amount)
        truth_art.append(GroundTruth("artifact", anchor + timedelta(seconds=s0 * interval_seconds),
                                     anchor + timedelta(seconds=min(steps - 1, s0 + n) * interval_seconds), f"{kind} on {vital}"))
    critical_at: datetime | None = None
    for i in range(steps):
        at = anchor + timedelta(seconds=i * interval_seconds)
        if onset_step is None or i <= onset_step:
            progress = 0.0
        else:
            progress = ((i - onset_step) / max(1, steps - 1 - onset_step)) ** spec.shape
        clean = {v: spec.curves[v].baseline + (spec.curves[v].target - spec.curves[v].baseline) * progress for v in VITAL_ORDER}
        if critical_at is None and onset_step is not None and _critical(clean):
            critical_at = at
        for vital in VITAL_ORDER:
            c = spec.curves[vital]
            v = clean[vital] + rng.uniform(-c.noise, c.noise)
            v = min(c.hi, max(c.lo, v))
            art = art_steps.get((i, vital))
            if art:
                v = 0.0 if art[0] == "zero" else max(0.0, v + art[1])
            v = round(v, DECIMALS[vital]) if DECIMALS[vital] else float(int(round(v)))
            events.append(MeasurementEvent(seq, vital, LOINC_BY_KEY[vital], v, UCUM_BY_KEY[vital], at, source))
            seq += 1
    end = anchor + timedelta(seconds=(steps - 1) * interval_seconds)
    if onset_step is None:
        truth = [GroundTruth("stable", anchor, end, "no deterioration scripted")]
    else:
        onset = anchor + timedelta(seconds=onset_step * interval_seconds)
        truth = [GroundTruth("stable", anchor, onset, "pre-onset"),
                 GroundTruth("deterioration_onset", onset, end, f"progressive ramp, shape {spec.shape}")]
        if critical_at:
            truth.append(GroundTruth("critical", critical_at, end, "scripted curve reaches >=2 of SpO2<=91, pulse>=131, RR>=25"))
    return events, truth + truth_art


def fingerprint(events: list[MeasurementEvent]) -> str:
    """SHA-256 over all event fields, for reproducibility checks."""
    h = hashlib.sha256()
    for e in events:
        h.update(json.dumps(e.key(), sort_keys=True).encode())
    return h.hexdigest()


def event_dict(e: MeasurementEvent) -> dict:
    d = asdict(e)
    d["measured_at"] = e.measured_at.isoformat()
    return d
