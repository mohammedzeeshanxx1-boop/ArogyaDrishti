"""Phase 1 replay engine: clock, determinism, lifecycle, persistence, recovery, isolation."""

from __future__ import annotations

import ast
import asyncio
import dataclasses
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.db import init_db
from app.fhir import FhirClient
from app.main import create_app
from app.replay import store
from app.replay.clock import SimClock
from app.replay.engine import ReplayConflict, ReplayManager
from app.replay.persistence import build_observation
from app.replay.scenarios import SCENARIOS, MeasurementEvent, fingerprint, generate
from app.vitals import validate_observation
from fake_hapi import FakeHapi

ANCHOR = datetime(2026, 11, 10, 6, 0, tzinfo=timezone.utc)
APP_DIR = Path(__file__).resolve().parents[1] / "app"


class FakeTime:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


# ------------------------------------------------------------------ clock
def test_clock_speed_pause_resume():
    ft = FakeTime()
    c = SimClock(ANCHOR, 10, ft)
    assert c.now() == ANCHOR and not c.running
    c.resume(); ft.t += 3
    assert c.elapsed() == 30 and c.now() == ANCHOR + timedelta(seconds=30)
    c.pause(); ft.t += 100
    assert c.elapsed() == 30                       # paused: simulated time frozen
    c.resume(); ft.t += 1
    assert c.elapsed() == 40
    assert c.wall_seconds_until(ANCHOR + timedelta(seconds=100)) == pytest.approx(6.0)
    assert c.wall_seconds_until(ANCHOR) == 0
    with pytest.raises(ValueError):
        SimClock(ANCHOR, 0)


# ------------------------------------------------------------------ determinism and ordering
@pytest.mark.parametrize("scenario", sorted(SCENARIOS))
def test_identical_inputs_give_identical_events(scenario):
    a, ta = generate(SCENARIOS[scenario], 7, ANCHOR, 60, 60)
    b, tb = generate(SCENARIOS[scenario], 7, ANCHOR, 60, 60)
    assert a == b and ta == tb and fingerprint(a) == fingerprint(b)
    c, _ = generate(SCENARIOS[scenario], 8, ANCHOR, 60, 60)
    assert fingerprint(c) != fingerprint(a)                         # seed matters
    d, _ = generate(SCENARIOS[scenario], 7, ANCHOR + timedelta(days=1), 60, 60)
    assert [e.value for e in d] == [e.value for e in a]             # anchor shifts time only
    assert all(y.measured_at - x.measured_at == timedelta(days=1) for x, y in zip(a, d))


def test_events_are_ordered_complete_and_correctly_coded():
    events, _ = generate(SCENARIOS["deterioration"], 1, ANCHOR, 30, 60)
    assert len(events) == 31 * 4
    assert [e.seq for e in events] == list(range(len(events)))
    assert all(b.measured_at >= a.measured_at for a, b in zip(events, events[1:]))
    steps = {e.measured_at for e in events}
    assert sorted(steps) == [ANCHOR + timedelta(minutes=i) for i in range(31)]
    codes = {(e.vital, e.loinc, e.ucum) for e in events}
    assert codes == {("heart_rate", "8867-4", "/min"), ("spo2", "2708-6", "%"),
                     ("respiratory_rate", "9279-1", "/min"), ("body_temperature", "8310-5", "Cel")}


@pytest.mark.parametrize("scenario", sorted(SCENARIOS))
def test_every_generated_observation_passes_strict_validation(scenario):
    spec = SCENARIOS[scenario]
    events, _ = generate(spec, spec.default_seed, ANCHOR, spec.default_duration_minutes, spec.default_interval_seconds)
    for e in events:
        r = validate_observation(build_observation(e, "p1", "s1"), ANCHOR + timedelta(days=1))
        assert r.ok, (e, r.issues)


def test_deterioration_has_onset_truth_and_actually_deteriorates():
    events, truth = generate(SCENARIOS["deterioration"], 2002, ANCHOR, 120, 60)
    onset = next(t for t in truth if t.label == "deterioration_onset").start
    pre = [e.value for e in events if e.vital == "spo2" and e.measured_at <= onset]
    post = [e.value for e in events if e.vital == "spo2"][-5:]
    assert min(pre) >= 95 and max(post) <= 91
    _, stable_truth = generate(SCENARIOS["stable"], 1001, ANCHOR, 120, 60)
    assert [t.label for t in stable_truth] == ["stable"]


# ------------------------------------------------------------------ ground truth isolation (C7)
def test_measurement_events_have_no_label_fields():
    names = {f.name for f in dataclasses.fields(MeasurementEvent)}
    assert names == {"seq", "vital", "loinc", "value", "ucum", "measured_at", "source"}


def test_fhir_payload_contains_no_scenario_or_ground_truth():
    for scenario in SCENARIOS:
        events, truth = generate(SCENARIOS[scenario], 3, ANCHOR, 120, 60)
        text = json.dumps([build_observation(e, "p1", "a1b2c3") for e in events]).lower()
        forbidden = {scenario, SCENARIOS[scenario].name.lower(), "onset", "deterioration", "stable", "ground"}
        forbidden |= {t.label for t in truth}
        assert not [w for w in forbidden if w in text], scenario


def test_detector_module_cannot_reach_ground_truth():
    for module in ("risk.py", "detector.py"):
        tree = ast.parse((APP_DIR / module).read_text())
        imported = {n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
        imported |= {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
        assert not [m for m in imported if "replay" in m or "store" in m or "db" in m], imported
    main = (APP_DIR / "main.py").read_text()
    assert "ground_truth(" not in main     # the API never reads ground truth
    assert "replay_ground_truth" not in main


# ------------------------------------------------------------------ engine with fake HAPI
def manager(tmp_path, hapi: FakeHapi, ft=None, legacy=lambda: False):
    db = str(tmp_path / "app.db")
    init_db(db)
    client = FhirClient("http://hapi.test/fhir", 5, hapi.transport())
    return ReplayManager(client, db, legacy_busy=legacy, **({"monotonic": ft} if ft else {})), db


async def settle(n=20):
    for _ in range(n):
        await asyncio.sleep(0.01)


def test_batch_mode_persists_everything_without_waiting(tmp_path):
    async def run():
        hapi = FakeHapi()
        mgr, db = manager(tmp_path, hapi)
        s = await mgr.create("p1", "deterioration", 5, ANCHOR, 120, 60, "batch", batch_size=100)
        t0 = asyncio.get_running_loop().time()
        await mgr.start(s.id)
        await s.wait(10)
        elapsed = asyncio.get_running_loop().time() - t0
        assert s.state == "completed" and s.cursor == len(s.events) == 121 * 4
        assert s.created == len(s.events) and s.existing == 0
        assert len(hapi.observations) == len(s.events) and hapi.transactions == 5
        assert elapsed < 5                                         # 2 simulated hours, no real-time wait
        rows = store.event_rows(db, s.id)
        assert len(rows) == len(s.events) and {r["persist_status"] for r in rows} == {"created"}
        assert all(r["measured_at"] < r["ingested_at"] for r in rows)   # measurement vs ingestion time kept apart
        assert sum(r["hapi_shape_validated"] for r in rows) == 4        # one $validate per vital
        assert [t["label"] for t in store.ground_truth(db, s.id)] == ["stable", "deterioration_onset", "critical"]
        stored = hapi.observations[rows[5]["observation_id"]]
        assert stored["effectiveDateTime"] == s.events[5].measured_at.isoformat()
        assert stored["subject"]["reference"] == "Patient/p1"
    asyncio.run(run())


def test_playback_lifecycle_start_pause_resume_stop_reset(tmp_path):
    async def run():
        ft = FakeTime()
        hapi = FakeHapi()
        mgr, db = manager(tmp_path, hapi, ft)
        s = await mgr.create("p1", "stable", 1, ANCHOR, 10, 60, "10x", batch_size=50)
        assert s.state == "created" and s.cursor == 0
        await mgr.start(s.id); await settle()
        assert s.state == "running" and s.cursor == 4            # only the step at the anchor is due
        ft.t += 6; await settle()                                  # 6 s wall x 10 = 60 s simulated
        assert s.cursor == 8
        await s.pause(); ft.t += 600; await settle()
        assert s.state == "paused" and s.cursor == 8              # paused: nothing new even though wall time passed
        with pytest.raises(ReplayConflict):
            await s.pause()
        await s.resume(); ft.t += 12; await settle()
        assert s.state == "running" and s.cursor == 16
        await s.stop()
        assert s.state == "stopped" and s.cursor == 16
        ft.t += 100; await settle()
        assert s.cursor == 16                                       # stays stopped
        with pytest.raises(ReplayConflict):
            await s.start()
        r = await mgr.reset(s.id)
        assert r.id != s.id and r.reset_from == s.id and r.state == "created" and r.cursor == 0
        assert r.fingerprint == s.fingerprint                       # reproducible state
        assert len(hapi.observations) == 16                         # reset deletes nothing
        await mgr.start(r.id); ft.t += 1000; await settle(40)
        assert r.state == "completed" and r.cursor == len(r.events) == 44
    asyncio.run(run())


def test_speeds_scale_simulated_time(tmp_path):
    async def run():
        for speed, wall, expected_steps in (("1x", 60, 2), ("5x", 12, 2), ("10x", 6, 2), ("10x", 60, 11)):
            ft = FakeTime()
            mgr, _ = manager(tmp_path / speed / str(wall), FakeHapi(), ft)
            s = await mgr.create("p1", "stable", 1, ANCHOR, 30, 60, speed)
            await mgr.start(s.id); await settle()
            ft.t += wall; await settle()
            assert s.cursor == expected_steps * 4, (speed, wall, s.cursor)
            await s.stop()
    for d in ("1x/60", "5x/12", "10x/6", "10x/60"):
        (tmp_path / d).mkdir(parents=True, exist_ok=True)
    asyncio.run(run())


def test_hapi_down_stops_safely_and_resume_retries_without_loss(tmp_path):
    async def run():
        hapi = FakeHapi(down=True)
        mgr, db = manager(tmp_path, hapi)
        s = await mgr.create("p1", "deterioration", 5, ANCHOR, 60, 60, "batch", batch_size=50)
        await mgr.start(s.id); await s.wait(5)
        assert s.state == "error" and s.cursor == 0 and s.created == 0
        assert "not persisted" in s.last_error
        assert store.batch_rows(db, s.id)[0]["outcome"] == "failed"
        assert store.event_rows(db, s.id) == []                    # nothing claimed as stored
        hapi.down = False
        await s.resume(); await s.wait(5)
        assert s.state == "completed" and s.created == len(s.events) == len(hapi.observations)
    asyncio.run(run())


def test_lost_response_after_commit_does_not_duplicate(tmp_path):
    async def run():
        hapi = FakeHapi()
        hapi.commit_then_fail = 1
        mgr, db = manager(tmp_path, hapi)
        s = await mgr.create("p1", "stable", 1, ANCHOR, 30, 60, "batch", batch_size=40)
        await mgr.start(s.id); await s.wait(5)
        assert s.state == "error" and s.cursor == 0               # HAPI committed, but we never got confirmation
        await s.resume(); await s.wait(5)
        assert s.state == "completed"
        assert len(hapi.observations) == len(s.events) == 124      # no duplicates
        assert s.existing == 40 and s.created == 84                # first batch recognised via ifNoneExist
        statuses = [r["persist_status"] for r in store.event_rows(db, s.id)]
        assert statuses.count("existing") == 40
    asyncio.run(run())


def test_local_validation_failure_sends_nothing(tmp_path):
    async def run():
        hapi = FakeHapi()
        mgr, _ = manager(tmp_path, hapi)
        future = datetime.now(timezone.utc) + timedelta(days=2)    # forced future anchor
        s = await mgr.create("p1", "stable", 1, future, 10, 60, "batch")
        await mgr.start(s.id); await s.wait(5)
        assert s.state == "error" and "failed local validation" in s.last_error
        assert hapi.transactions == 0 and hapi.observations == {}
    asyncio.run(run())


def test_only_one_active_session_and_no_overlap_with_legacy_simulator(tmp_path):
    async def run():
        ft = FakeTime()
        legacy = {"busy": False}
        mgr, _ = manager(tmp_path, FakeHapi(), ft, legacy=lambda: legacy["busy"])
        a = await mgr.create("p1", "stable", 1, ANCHOR, 60, 60, "1x")
        b = await mgr.create("p1", "deterioration", 2, ANCHOR, 60, 60, "1x")
        await mgr.start(a.id)
        with pytest.raises(ReplayConflict):
            await mgr.start(b.id)
        await a.pause()
        with pytest.raises(ReplayConflict):
            await mgr.start(b.id)                                   # paused still counts as active
        await a.stop()
        legacy["busy"] = True
        with pytest.raises(ReplayConflict):
            await mgr.start(b.id)
        legacy["busy"] = False
        await mgr.start(b.id)
        assert b.state == "running"
        await b.stop()
    asyncio.run(run())


# ------------------------------------------------------------------ API
def app_client(tmp_path, hapi):
    settings = Settings("http://hapi.test/fhir", 1, str(tmp_path / "app.db"), ("http://localhost:5173",))
    return TestClient(create_app(settings, fhir_transport=hapi.transport(), simulator_in_process=True))


def test_api_batch_session_and_monitor_view(tmp_path):
    hapi = FakeHapi()
    with app_client(tmp_path, hapi) as c:
        assert {s["id"] for s in c.get("/api/replay/scenarios").json()["scenarios"]} == {"stable", "deterioration", "artifact", "deterioration_artifact"}
        r = c.post("/api/replay/sessions", json={"patientId": "p1", "scenario": "deterioration", "speed": "batch",
                                                 "durationMinutes": 60, "intervalSeconds": 60})
        assert r.status_code == 201, r.json()
        sid = r.json()["sessionId"]
        assert "onset" not in json.dumps(r.json()).lower()
        done = c.post(f"/api/replay/sessions/{sid}/start", params={"wait": True}).json()
        assert done["state"] == "completed" and done["persisted"] == done["eventsTotal"] == 244
        assert c.post(f"/api/replay/sessions/{sid}/start").status_code == 409
        assert c.post(f"/api/replay/sessions/{sid}/jump").status_code == 404
        assert c.get("/api/replay/sessions/nope").status_code == 404
        new = c.post(f"/api/replay/sessions/{sid}/reset").json()
        assert new["resetFrom"] == sid and new["fingerprint"] == done["fingerprint"] and new["state"] == "created"


def test_api_rejects_future_unknown_and_bad_input(tmp_path):
    with app_client(tmp_path, FakeHapi()) as c:
        future = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
        assert c.post("/api/replay/sessions", json={"patientId": "p1", "scenario": "stable", "anchor": future}).status_code == 400
        assert c.post("/api/replay/sessions", json={"patientId": "ghost", "scenario": "stable"}).status_code == 404
        assert c.post("/api/replay/sessions", json={"patientId": "p1", "scenario": "x"}).status_code == 400
        assert c.post("/api/replay/sessions", json={"patientId": "p1", "scenario": "stable", "speed": "3x"}).status_code == 400


def test_legacy_simulator_blocked_while_replay_active(tmp_path):
    with app_client(tmp_path, FakeHapi()) as c:
        sid = c.post("/api/replay/sessions", json={"patientId": "p1", "scenario": "stable", "speed": "1x"}).json()["sessionId"]
        assert c.post(f"/api/replay/sessions/{sid}/start").status_code == 200
        r = c.post("/api/demo/simulator/start", json={"patientId": "p1", "scenario": "stable"})
        assert r.status_code == 409
        assert c.post(f"/api/replay/sessions/{sid}/stop").json()["state"] == "stopped"
        assert c.post("/api/demo/simulator/start", json={"patientId": "p1", "scenario": "stable", "steps": 2, "intervalSeconds": 0}).status_code == 200
