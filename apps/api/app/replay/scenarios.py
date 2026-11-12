"""Seeded scenario definitions.

A scenario turns (seed, anchor) into two SEPARATE outputs:
  * measurement events: what a wearable would report (vital, value, unit, measured_at)
  * ground truth: labelled annotations (e.g. deterioration onset) for evaluation only

Identical (scenario, seed, anchor, duration, interval) -> identical events, byte for byte.
"""

from __future__ import annotations

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


def generate(spec: ScenarioSpec, seed: int, anchor: datetime, duration_minutes: int, interval_seconds: int,
             source: str = "simulated") -> tuple[list[MeasurementEvent], list[GroundTruth]]:
    if interval_seconds <= 0 or duration_minutes <= 0:
        raise ValueError("duration and interval must be positive")
    steps = int(duration_minutes * 60 // interval_seconds) + 1
    rng = random.Random(seed)
    onset_step = int(round(spec.onset_fraction * (steps - 1))) if spec.onset_fraction is not None else None
    events: list[MeasurementEvent] = []
    seq = 0
    for i in range(steps):
        at = anchor + timedelta(seconds=i * interval_seconds)
        if onset_step is None or i <= onset_step:
            progress = 0.0
        else:
            progress = ((i - onset_step) / max(1, steps - 1 - onset_step)) ** spec.shape
        for vital in VITAL_ORDER:
            c = spec.curves[vital]
            v = c.baseline + (c.target - c.baseline) * progress + rng.uniform(-c.noise, c.noise)
            v = min(c.hi, max(c.lo, v))
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
    return events, truth


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
