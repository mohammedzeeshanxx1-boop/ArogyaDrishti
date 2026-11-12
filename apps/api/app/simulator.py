"""Virtual wearable simulator (Round 1 MVP).

Two deterministic scenarios generate heart rate, SpO2, respiratory rate and
temperature. Every reading is posted as a FHIR R4 Observation to the existing
ingestion endpoint (POST /api/fhir/Observation), which validates it and stores
it in HAPI FHIR. Nothing is stored by the simulator itself.

Readings carry a real "now" timestamp; demo mode compresses the scenario into
about 40 seconds of wall-clock time.

CLI (posts over HTTP to a running API):
  python -m app.simulator --patient <id> --scenario deterioration --api http://localhost:8000
"""

from __future__ import annotations

import argparse
import asyncio
import os
import random
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

import httpx

from .vitals import example_observation

SCENARIOS = {
    "stable": "Stable Recovery",
    "deterioration": "Gradual Deterioration",
}
DEFAULT_STEPS = 20
DEFAULT_INTERVAL = 2.0  # seconds between readings in demo mode
RUN_TAG_SYSTEM = "urn:arogya-drishti:simulator-run"

# (start, end, noise amplitude, decimals) per vital; noise is seeded and bounded.
_PROFILES = {
    "stable": {
        "8867-4": (74, 75, 2, 0),      # heart rate /min
        "2708-6": (97, 97, 1, 0),      # SpO2 %
        "9279-1": (15, 15, 1, 0),      # respiratory rate /min
        "8310-5": (36.8, 36.8, 0.15, 1),  # temperature Cel
    },
    "deterioration": {
        "8867-4": (78, 134, 1.5, 0),
        "2708-6": (97, 88, 0.5, 0),
        "9279-1": (16, 31, 0.5, 0),
        "8310-5": (37.0, 39.3, 0.05, 1),
    },
}
_SEEDS = {"stable": 1001, "deterioration": 2002}


def scenario_readings(scenario: str, steps: int = DEFAULT_STEPS) -> list[dict[str, float]]:
    """Deterministic list of {loinc: value} per step."""
    if scenario not in _PROFILES:
        raise ValueError(f"unknown scenario {scenario!r}")
    rng = random.Random(_SEEDS[scenario])
    out = []
    for i in range(steps):
        f = i / (steps - 1) if steps > 1 else 1.0
        step = {}
        for loinc, (a, b, noise, dec) in _PROFILES[scenario].items():
            curve = f ** 1.4 if scenario == "deterioration" else f
            v = a + (b - a) * curve + rng.uniform(-noise, noise)
            step[loinc] = round(v, dec) if dec else int(round(v))
        out.append(step)
    return out


def build_observation(loinc: str, value: float, patient_id: str, when: datetime, run_id: str) -> dict:
    obs = example_observation(loinc, patient_id, value, when)
    obs["meta"] = {"tag": [{"system": RUN_TAG_SYSTEM, "code": run_id, "display": "Simulated wearable reading"}]}
    obs["device"] = {"display": "Arogya Drishti virtual wearable (simulated)"}
    return obs


@dataclass
class SimulatorState:
    running: bool = False
    run_id: str | None = None
    patient_id: str | None = None
    scenario: str | None = None
    step: int = 0
    total_steps: int = 0
    interval: float = DEFAULT_INTERVAL
    started_at: str | None = None
    finished_at: str | None = None
    stopped: bool = False
    accepted: int = 0
    rejected: int = 0
    last_error: str | None = None
    observation_ids: list[str] = field(default_factory=list)

    def public(self) -> dict:
        return {
            "running": self.running, "runId": self.run_id, "patientId": self.patient_id,
            "scenario": self.scenario, "scenarioLabel": SCENARIOS.get(self.scenario or ""),
            "step": self.step, "totalSteps": self.total_steps, "intervalSeconds": self.interval,
            "startedAt": self.started_at, "finishedAt": self.finished_at, "stopped": self.stopped,
            "accepted": self.accepted, "rejected": self.rejected, "lastError": self.last_error,
            "lastObservationId": self.observation_ids[-1] if self.observation_ids else None,
        }


class Simulator:
    """Runs one scenario at a time as a background asyncio task."""

    def __init__(self, client: httpx.AsyncClient, ingest_path: str = "/api/fhir/Observation"):
        self.client = client
        self.ingest_path = ingest_path
        self.state = SimulatorState()
        self._task: asyncio.Task | None = None

    async def start(self, patient_id: str, scenario: str, steps: int = DEFAULT_STEPS, interval: float = DEFAULT_INTERVAL) -> dict:
        if scenario not in SCENARIOS:
            raise ValueError(f"scenario must be one of {sorted(SCENARIOS)}")
        await self.stop()
        now = datetime.now(timezone.utc).replace(microsecond=0)
        self.state = SimulatorState(
            running=True, run_id=uuid.uuid4().hex[:12], patient_id=patient_id, scenario=scenario,
            total_steps=steps, interval=interval, started_at=now.isoformat(),
        )
        self._task = asyncio.create_task(self._run(scenario_readings(scenario, steps)))
        return self.state.public()

    async def stop(self) -> dict:
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self.state.stopped = True
            self.state.running = False
            self.state.finished_at = datetime.now(timezone.utc).isoformat()
        return self.state.public()

    async def wait(self) -> None:
        if self._task:
            await asyncio.gather(self._task, return_exceptions=True)

    async def _run(self, plan: list[dict[str, float]]) -> None:
        s = self.state
        loop = asyncio.get_running_loop()
        try:
            for i, step in enumerate(plan):
                t0 = loop.time()
                when = datetime.now(timezone.utc).replace(microsecond=0)
                for loinc, value in step.items():
                    obs = build_observation(loinc, value, s.patient_id, when, s.run_id)
                    try:
                        r = await self.client.post(self.ingest_path, json=obs)
                        body = r.json()
                    except (httpx.HTTPError, ValueError) as exc:
                        s.rejected += 1
                        s.last_error = f"{type(exc).__name__}: {exc}"
                        continue
                    if r.status_code == 201:
                        s.accepted += 1
                        s.observation_ids.append(body["id"])
                    else:
                        s.rejected += 1
                        s.last_error = "; ".join(i.get("diagnostics", "") for i in body.get("issue", [])) or f"HTTP {r.status_code}"
                s.step = i + 1
                if i < len(plan) - 1:
                    await asyncio.sleep(max(0.0, s.interval - (loop.time() - t0)))
        finally:
            if s.running:
                s.running = False
                s.finished_at = datetime.now(timezone.utc).isoformat()


async def _cli(args) -> None:
    async with httpx.AsyncClient(base_url=args.api, timeout=60) as client:
        if os.environ.get("AROGYA_USER"):   # the API requires a signed-in doctor to ingest observations
            r = await client.post("/api/auth/login", json={"username": os.environ["AROGYA_USER"], "password": os.environ.get("AROGYA_PASSWORD", "")})
            if r.status_code != 200:
                raise SystemExit(f"sign-in failed: HTTP {r.status_code} {r.text[:200]}")
        sim = Simulator(client)
        await sim.start(args.patient, args.scenario, args.steps, args.interval)
        while sim.state.running:
            await asyncio.sleep(1)
            st = sim.state
            print(f"step {st.step}/{st.total_steps} accepted={st.accepted} rejected={st.rejected} last={st.observation_ids[-1:]}")
        await sim.wait()
        print(sim.state.public())


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Arogya Drishti virtual wearable simulator")
    ap.add_argument("--patient", required=True)
    ap.add_argument("--scenario", choices=sorted(SCENARIOS), default="deterioration")
    ap.add_argument("--api", default="http://localhost:8000")
    ap.add_argument("--steps", type=int, default=DEFAULT_STEPS)
    ap.add_argument("--interval", type=float, default=DEFAULT_INTERVAL)
    asyncio.run(_cli(ap.parse_args()))
