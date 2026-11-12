"""Event sources for replay.

Every source yields MeasurementEvents (detector-visible) and, separately, an optional
list of GroundTruth annotations (evaluation-only). A future BidmcSource will implement
the same interface from parsed PhysioNet numerics and return no ground truth
(BIDMC has no deterioration labels).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from .scenarios import SCENARIOS, GroundTruth, MeasurementEvent, generate


class EventSource(Protocol):
    source_kind: str   # "simulated" | "bidmc"
    description: str

    def events(self) -> list[MeasurementEvent]: ...
    def ground_truth(self) -> list[GroundTruth]: ...


@dataclass
class SimulatedSource:
    scenario_id: str
    seed: int
    anchor: datetime
    duration_minutes: int
    interval_seconds: int
    source_kind: str = "simulated"

    def __post_init__(self):
        if self.scenario_id not in SCENARIOS:
            raise ValueError(f"unknown scenario {self.scenario_id!r}; known: {sorted(SCENARIOS)}")
        self._events, self._truth = generate(SCENARIOS[self.scenario_id], self.seed, self.anchor,
                                             self.duration_minutes, self.interval_seconds, self.source_kind)
        self.description = f"{SCENARIOS[self.scenario_id].name} (seed {self.seed})"

    def events(self) -> list[MeasurementEvent]:
        return list(self._events)

    def ground_truth(self) -> list[GroundTruth]:
        return list(self._truth)
