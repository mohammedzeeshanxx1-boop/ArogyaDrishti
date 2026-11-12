"""Server-side monitoring: assessability, staleness, alert transitions."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app import detector, monitoring
from app.db import init_db

NOW = datetime(2026, 11, 12, 12, 0, tzinfo=timezone.utc)


def rd(vital, value, minutes_ago, i=0):
    return {"vital": vital, "value": value, "effective": (NOW - timedelta(minutes=minutes_ago)).isoformat(),
            "observation": f"Observation/{vital}-{minutes_ago}-{i}", "source": "Arogya Drishti virtual wearable (simulated)"}


def full(hr=72, spo2=97, rr=15, temp=36.8, ago=1):
    return [rd("heart_rate", hr, ago), rd("spo2", spo2, ago), rd("respiratory_rate", rr, ago), rd("body_temperature", temp, ago)]


def test_no_readings_is_not_reported_as_normal():
    s = monitoring.summarize([], detector.evaluate([]), NOW)
    assert s["assessable"] is False and s["level"] is None and s["monitoringStatus"] == "no_recent_data"


def test_too_few_trusted_vitals_is_not_assessable():
    r = [rd("heart_rate", 72, 1), rd("spo2", 97, 1)]
    s = monitoring.summarize(r, detector.evaluate(r), NOW)
    assert s["assessable"] is False and s["level"] is None and s["trustedVitals"] == 2


def test_probe_off_readings_do_not_count_as_trusted():
    r = [rd("heart_rate", 0, 1), rd("spo2", 0, 1), rd("respiratory_rate", 15, 1), rd("body_temperature", 36.8, 1)]
    s = monitoring.summarize(r, detector.evaluate(r), NOW)
    assert s["trustedVitals"] == 2 and s["assessable"] is False


def test_active_and_stale_status():
    r = full(ago=2)
    s = monitoring.summarize(r, detector.evaluate(r), NOW)
    assert s["assessable"] and s["level"] == "NORMAL" and s["monitoringStatus"] == "active"
    r = full(ago=40)
    s = monitoring.summarize(r, detector.evaluate(r), NOW)
    assert s["monitoringStatus"] == "stale" and s["assessable"]        # stale data is flagged, still assessed
    assert "simulated" in s["sources"][0]


def test_alert_transitions_raised_escalated_resolved(tmp_path):
    db = str(tmp_path / "app.db")
    init_db(db)
    monitoring.init(db)

    def step(readings, t):
        risk = detector.evaluate(readings)
        return monitoring.record_transition(db, "p1", risk, monitoring.summarize(readings, risk, NOW), "personalized", NOW + timedelta(minutes=t))

    assert step(full(), 0) is None                                     # NORMAL -> NORMAL: nothing recorded
    e1 = step(full(spo2=95), 1)                                        # SpO2 95 scores 1 -> WATCH
    assert e1["kind"] == "raised" and e1["level"] == "WATCH" and e1["observation"].startswith("Observation/")
    assert step(full(spo2=95), 2) is None                               # unchanged level: no duplicate
    e2 = step(full(hr=134, spo2=88, rr=31, temp=39.3), 3)
    assert e2["kind"] == "escalated" and e2["level"] == "URGENT" and e2["previous_level"] == "WATCH" and e2["reason"]
    e3 = step(full(), 4)
    assert e3["kind"] == "resolved" and e3["level"] == "NORMAL"
    assert step([rd("heart_rate", 72, 1)], 5) is None                  # not assessable: no state change, no event
    events = monitoring.alert_events(db, "p1")
    assert [e["kind"] for e in events] == ["resolved", "escalated", "raised"]


class _FakeFhir:
    def __init__(self):
        self.params = None

    async def search(self, rtype, params, limit=None):
        self.params = params
        return []


def test_new_run_window_narrows_but_never_widens_recent_window():
    import asyncio
    f = _FakeFhir()
    asyncio.run(monitoring.recent_readings(f, "p1", NOW, since=NOW - timedelta(minutes=2)))
    assert f.params["date"][0] == "ge2026-11-12T11:58:00Z"
    asyncio.run(monitoring.recent_readings(f, "p1", NOW, since=NOW - timedelta(hours=5)))
    assert f.params["date"][0] == "ge2026-11-12T11:00:00Z"


def test_reset_state_starts_new_run_unassessed_but_keeps_alert_history(tmp_path):
    db = str(tmp_path / "m.db"); init_db(db); monitoring.init(db)
    r = full(hr=135, spo2=88, rr=28, temp=39.2)
    risk = detector.evaluate(r)
    assert monitoring.record_transition(db, "p1", risk, monitoring.summarize(r, risk, NOW), "personalized", NOW)
    monitoring.reset_state(db, "p1")
    ev = monitoring.record_transition(db, "p1", risk, monitoring.summarize(r, risk, NOW), "personalized", NOW)
    assert ev and ev["kind"] == "raised"          # raised again in the new run, not a duplicate-suppressed no-op
    assert len(monitoring.alert_events(db, "p1")) == 2
