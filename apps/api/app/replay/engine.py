"""Replay sessions and their manager.

Lifecycle:  created --start--> running <--pause/resume--> paused
            running|paused --stop--> stopped      running --(all persisted)--> completed
            running --(HAPI failure)--> error --resume--> running (retries the failed batch)
            any --reset--> a NEW session with identical source parameters (state created)

Speeds: "1x", "5x", "10x" play events when the simulated clock reaches their
measurement time; "batch" persists everything without waiting.

Guarantees:
  * the cursor advances only after HAPI confirms a batch (no silent loss)
  * a failed batch is retried from the same cursor; conditional create makes retries idempotent
  * at most one session is active (running or paused) at a time, and none while the
    legacy demo simulator is running
"""

from __future__ import annotations

import asyncio
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Callable

from ..fhir import FhirClient, FhirUnavailable
from . import store
from .clock import SimClock
from .persistence import PersistError, persist_batch
from .scenarios import SCENARIOS, fingerprint
from .sources import EventSource, SimulatedSource

SPEEDS: dict[str, float | None] = {"1x": 1.0, "5x": 5.0, "10x": 10.0, "batch": None}
ACTIVE_STATES = {"running", "paused"}
DEFAULT_BATCH = 200


class ReplayConflict(Exception):
    pass


def _now() -> datetime:
    return datetime.now(timezone.utc)


class ReplaySession:
    def __init__(self, *, session_id: str, source: EventSource, patient_id: str, speed: str, fhir: FhirClient,
                 db_path: str, batch_size: int = DEFAULT_BATCH, reset_from: str | None = None,
                 params: dict | None = None, monotonic: Callable[[], float] = time.monotonic):
        if speed not in SPEEDS:
            raise ValueError(f"speed must be one of {list(SPEEDS)}")
        self.id = session_id
        self.source = source
        self.patient_id = patient_id
        self.speed = speed
        self.fhir = fhir
        self.db_path = db_path
        self.batch_size = batch_size
        self.reset_from = reset_from
        self.params = params or {}
        self.events = source.events()
        if any(b.measured_at < a.measured_at for a, b in zip(self.events, self.events[1:])):
            raise ValueError("source events must be in measurement-time order")
        self.anchor = self.events[0].measured_at if self.events else _now()
        self.fingerprint = fingerprint(self.events)
        self.clock = SimClock(self.anchor, SPEEDS[speed] or 1.0, monotonic)
        self.state = "created"
        self.cursor = 0
        self.created = 0
        self.existing = 0
        self.batch_no = 0
        self.failed_batches = 0
        self.last_error: str | None = None
        self.started_at: str | None = None
        self.finished_at: str | None = None
        self.validated_shapes: set[str] = set()
        self._task: asyncio.Task | None = None
        self._unpaused = asyncio.Event()
        self._unpaused.set()
        self._stop = False
        self._lock = asyncio.Lock()

        store.insert_session(db_path, {
            "session_id": self.id, "source_kind": source.source_kind, "scenario_id": self.params.get("scenario"),
            "seed": self.params.get("seed"), "patient_id": patient_id, "anchor": self.anchor.isoformat(),
            "duration_minutes": self.params.get("durationMinutes", 0), "interval_seconds": self.params.get("intervalSeconds", 0),
            "speed": speed, "state": self.state, "events_total": len(self.events), "events_fingerprint": self.fingerprint,
            "created_at": _now().isoformat(), "reset_from": reset_from,
        })
        store.save_ground_truth(db_path, self.id, source.ground_truth())

    # ------------------------------------------------------------ state
    @property
    def active(self) -> bool:
        return self.state in ACTIVE_STATES

    def _save(self, **extra) -> None:
        store.update_session(self.db_path, self.id, state=self.state, cursor=self.cursor, events_created=self.created,
                             events_existing=self.existing, last_error=self.last_error, started_at=self.started_at,
                             finished_at=self.finished_at, **extra)

    def public(self) -> dict:
        total = len(self.events)
        sim_now = self.clock.now() if self.started_at else self.anchor
        if self.speed == "batch" or self.state in ("completed",):
            sim_now = self.events[self.cursor - 1].measured_at if self.cursor else self.anchor
        last = self.events[-1].measured_at if self.events else self.anchor
        return {
            "sessionId": self.id, "patientId": self.patient_id, "source": self.source.source_kind,
            "description": self.source.description, "scenario": self.params.get("scenario"),
            "scenarioName": SCENARIOS[self.params["scenario"]].name if self.params.get("scenario") in SCENARIOS else None,
            "seed": self.params.get("seed"), "durationMinutes": self.params.get("durationMinutes"),
            "intervalSeconds": self.params.get("intervalSeconds"), "speed": self.speed, "state": self.state,
            "anchor": self.anchor.isoformat(), "endsAt": last.isoformat(), "simulatedNow": min(sim_now, last).isoformat(),
            "eventsTotal": total, "cursor": self.cursor, "persisted": self.created + self.existing,
            "created": self.created, "existing": self.existing, "progress": round(self.cursor / total, 4) if total else 1.0,
            "batches": self.batch_no, "failedBatches": self.failed_batches, "lastError": self.last_error,
            "fingerprint": self.fingerprint, "startedAt": self.started_at, "finishedAt": self.finished_at,
            "resetFrom": self.reset_from,
        }

    # ------------------------------------------------------------ controls
    async def start(self) -> None:
        async with self._lock:
            if self.state not in ("created", "error"):
                raise ReplayConflict(f"cannot start a session in state {self.state!r}")
            self.started_at = self.started_at or _now().isoformat()
            self._launch()

    async def pause(self) -> None:
        async with self._lock:
            if self.state != "running":
                raise ReplayConflict(f"cannot pause a session in state {self.state!r}")
            self._unpaused.clear()
            self.clock.pause()
            self.state = "paused"
            self._save()

    async def resume(self) -> None:
        async with self._lock:
            if self.state == "paused":
                self.state = "running"
                self.clock.resume()
                self._unpaused.set()
                self._save()
            elif self.state == "error":
                self._launch()   # retry from the same cursor
            else:
                raise ReplayConflict(f"cannot resume a session in state {self.state!r}")

    async def stop(self) -> None:
        async with self._lock:
            if self.state in ("stopped", "completed"):
                return
            self._stop = True
            self._unpaused.set()
            task = self._task
        if task:
            await asyncio.gather(task, return_exceptions=True)   # lets an in-flight batch finish and be recorded
        async with self._lock:
            if self.state not in ("completed",):
                self.state = "stopped"
                self.clock.pause()
                self.finished_at = _now().isoformat()
                self._save()

    async def wait(self, timeout: float | None = None) -> None:
        if self._task:
            await asyncio.wait_for(asyncio.shield(self._task), timeout)

    def _launch(self) -> None:
        self._stop = False
        self.last_error = None
        self.state = "running"
        self._unpaused.set()
        self.clock.resume()
        self._save()
        self._task = asyncio.create_task(self._run(), name=f"replay-{self.id}")

    # ------------------------------------------------------------ loop
    def _due_end(self) -> int:
        n = len(self.events)
        limit = min(n, self.cursor + self.batch_size)
        if SPEEDS[self.speed] is None:
            return limit
        now = self.clock.now()
        j = self.cursor
        while j < limit and self.events[j].measured_at <= now:
            j += 1
        return j

    async def _run(self) -> None:
        n = len(self.events)
        while self.cursor < n:
            await self._unpaused.wait()
            if self._stop:
                return
            end = self._due_end()
            if end == self.cursor:
                wait = self.clock.wall_seconds_until(self.events[self.cursor].measured_at)
                await asyncio.sleep(min(max(wait, 0.01), 0.25))
                continue
            batch = self.events[self.cursor:end]
            self.batch_no += 1
            started = _now().isoformat()
            try:
                res = await persist_batch(self.fhir, batch, self.patient_id, self.id, self.validated_shapes, _now())
            except (PersistError, FhirUnavailable) as exc:
                self.failed_batches += 1
                self.last_error = f"batch {self.batch_no} (seq {batch[0].seq}-{batch[-1].seq}) not persisted: {exc}"
                store.record_batch(self.db_path, self.id, self.batch_no, started, _now().isoformat(), batch, "failed", error=str(exc))
                self.state = "error"
                self.clock.pause()
                self._save()
                return
            finished = _now().isoformat()
            store.record_batch(self.db_path, self.id, self.batch_no, started, finished, batch, "confirmed",
                               created=res.created, existing=res.existing, observation_ids=res.observation_ids,
                               statuses=res.statuses, shape_validated=set(res.hapi_validated))
            self.validated_shapes.update(res.hapi_validated)
            self.created += res.created
            self.existing += res.existing
            self.cursor = end
            self._save()
            if getattr(self, "on_batch", None):
                self.on_batch(self.patient_id)
        self.state = "completed"
        self.finished_at = _now().isoformat()
        self.clock.pause()
        self._save()


class ReplayManager:
    def __init__(self, fhir: FhirClient, db_path: str, legacy_busy: Callable[[], bool] = lambda: False,
                 monotonic: Callable[[], float] = time.monotonic, on_batch: Callable[[str], None] | None = None):
        self.on_batch = on_batch    # called with the patient id after every HAPI-confirmed batch
        self.fhir = fhir
        self.db_path = db_path
        self.legacy_busy = legacy_busy
        self.monotonic = monotonic
        self.sessions: dict[str, ReplaySession] = {}
        self._lock = asyncio.Lock()

    def active(self) -> ReplaySession | None:
        return next((s for s in self.sessions.values() if s.active), None)

    def latest_for(self, patient_id: str) -> ReplaySession | None:
        mine = [s for s in self.sessions.values() if s.patient_id == patient_id]
        return mine[-1] if mine else None

    def get(self, session_id: str) -> ReplaySession | None:
        return self.sessions.get(session_id)

    def _new(self, patient_id: str, scenario: str, seed: int, anchor: datetime, duration: int, interval: int,
             speed: str, batch_size: int, reset_from: str | None = None) -> ReplaySession:
        source = SimulatedSource(scenario, seed, anchor, duration, interval)
        s = ReplaySession(session_id=uuid.uuid4().hex[:16], source=source, patient_id=patient_id, speed=speed,
                          fhir=self.fhir, db_path=self.db_path, batch_size=batch_size, reset_from=reset_from,
                          params={"scenario": scenario, "seed": seed, "durationMinutes": duration, "intervalSeconds": interval,
                                  "batchSize": batch_size},
                          monotonic=self.monotonic)
        s.on_batch = self.on_batch
        self.sessions[s.id] = s
        return s

    async def create(self, patient_id: str, scenario: str, seed: int | None, anchor: datetime | None,
                     duration: int | None, interval: int | None, speed: str, batch_size: int = DEFAULT_BATCH) -> ReplaySession:
        spec = SCENARIOS.get(scenario)
        if spec is None:
            raise ValueError(f"unknown scenario {scenario!r}; known: {sorted(SCENARIOS)}")
        duration = duration or spec.default_duration_minutes
        interval = interval or spec.default_interval_seconds
        if anchor is None:
            # End the scenario at "now" so no measurement time is ever in the future,
            # even at 10x (the simulated clock starts at the anchor).
            anchor = (_now() - timedelta(minutes=duration)).replace(second=0, microsecond=0)
        async with self._lock:
            return self._new(patient_id, scenario, seed if seed is not None else spec.default_seed, anchor,
                             duration, interval, speed, batch_size)

    async def start(self, session_id: str) -> ReplaySession:
        async with self._lock:
            s = self._require(session_id)
            other = self.active()
            if other and other.id != s.id:
                raise ReplayConflict(f"replay session {other.id} is already {other.state}; stop it first")
            if self.legacy_busy():
                raise ReplayConflict("the demo simulator is running; stop it first")
            await s.start()
            return s

    async def reset(self, session_id: str) -> ReplaySession:
        s = self._require(session_id)
        await s.stop()
        async with self._lock:
            p = s.params
            return self._new(s.patient_id, p["scenario"], p["seed"], s.anchor, p["durationMinutes"], p["intervalSeconds"],
                             s.speed, p["batchSize"], reset_from=s.id)

    async def shutdown(self) -> None:
        for s in list(self.sessions.values()):
            if s.active:
                await s.stop()

    def _require(self, session_id: str) -> ReplaySession:
        s = self.sessions.get(session_id)
        if s is None:
            raise KeyError(session_id)
        return s
