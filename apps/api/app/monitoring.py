"""Server-side monitoring: assessment, alert events, monitoring-source status.

Workflow (no dashboard needed):
  observation source -> POST /api/fhir/Observation (or a replay batch) -> HAPI validation + storage
  -> Assessor.request(patient) -> assess on recent trusted readings from HAPI
  -> alert event recorded in SQLite when the risk level changes -> WebSocket / dashboard

Honesty rules:
  * a patient is "assessable" only with a trusted reading for >= MIN_TRUSTED_VITALS of the 4 vitals
    inside the recent window; otherwise no risk level is reported (never a fabricated NORMAL)
  * alert events are recorded only on level changes computed from stored data; there is no
    acknowledgement workflow (none existed before, none is simulated)
"""

from __future__ import annotations

import asyncio
import os
from datetime import datetime, timedelta, timezone

from . import detector, scale2
from .db import connect
from .fhir import FhirClient
from .risk import to_celsius
from .vitals import INGEST_TAG, LOINC, VITALS

RECENT_MINUTES = int(os.environ.get("MONITOR_RECENT_MINUTES", "60"))   # window used for current status
STALE_MINUTES = int(os.environ.get("MONITOR_STALE_MINUTES", "15"))     # newest reading older than this = stale
MIN_TRUSTED_VITALS = 3
RECENT_LIMIT = 240

SCHEMA = """
CREATE TABLE IF NOT EXISTS patient_risk_state (
    patient_id TEXT PRIMARY KEY,
    level TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS alert_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    patient_id TEXT NOT NULL,
    created_at TEXT NOT NULL,          -- when the assessment ran (wall clock)
    measured_at TEXT,                  -- measurement time of the triggering observation
    kind TEXT NOT NULL CHECK (kind IN ('raised', 'escalated', 'de-escalated', 'resolved')),
    level TEXT NOT NULL,
    previous_level TEXT,
    vital TEXT,
    value REAL,
    unit TEXT,
    rule TEXT,
    reason TEXT NOT NULL,
    observation TEXT,
    mode TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_alert_patient ON alert_events(patient_id, id);
"""


def init(db_path: str) -> None:
    with connect(db_path) as c:
        c.executescript(SCHEMA)


def _z(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


async def recent_readings(fhir: FhirClient, pid: str, now: datetime, minutes: int = RECENT_MINUTES,
                          since: datetime | None = None) -> list[dict]:
    # `since` (start of the current simulation / reset) narrows the window; it never widens it.
    start = max(now - timedelta(minutes=minutes), since) if since else now - timedelta(minutes=minutes)
    # Only subject + date go to HAPI: on HAPI 5.7/H2 adding code or _tag filters made this query
    # 4-17x slower (measured 0.16-0.32 s vs 0.7-2.9 s). LOINC code and ingestion tag are checked here.
    params = {
        "subject": f"Patient/{pid}",
        "date": [f"ge{_z(start)}", f"le{_z(now + timedelta(minutes=5))}"],
        "_sort": "-date",
        "_count": 200,
    }
    stored = [o for o in await fhir.search("Observation", params, limit=RECENT_LIMIT * 2) if is_ingested(o)][:RECENT_LIMIT]
    out = []
    for o in stored:
        code = next((c["code"] for c in o.get("code", {}).get("coding", []) if c.get("system") == LOINC and c.get("code") in VITALS), None)
        q = o.get("valueQuantity") or {}
        if code is None or "value" not in q:
            continue
        key = VITALS[code].key
        v = to_celsius(float(q["value"]), q.get("code", "")) if key == "body_temperature" else float(q["value"])
        out.append({"vital": key, "value": v, "effective": o["effectiveDateTime"], "observation": f"Observation/{o['id']}",
                    "source": (o.get("device") or {}).get("display")})
    return out


def is_ingested(o: dict) -> bool:
    return any(t.get("system") == INGEST_TAG["system"] and t.get("code") == INGEST_TAG["code"] for t in o.get("meta", {}).get("tag", []))


def summarize(readings: list[dict], risk: dict, now: datetime) -> dict:
    """Assessment status for one patient from recent readings and a detector result."""
    params = risk["news2"]["parameters"]
    latest_time = max((_parse(r["effective"]) for r in readings), default=None)
    if latest_time is None:
        status = "no_recent_data"
    elif now - latest_time > timedelta(minutes=STALE_MINUTES):
        status = "stale"
    else:
        status = "active"
    assessable = len(params) >= MIN_TRUSTED_VITALS and status != "no_recent_data"
    sources = sorted({r["source"] for r in readings if r.get("source")})
    return {
        "assessable": assessable,
        "level": risk["level"] if assessable else None,
        "monitoringStatus": status,
        "lastObservationAt": latest_time.isoformat() if latest_time else None,
        "trustedVitals": len(params),
        "requiredTrustedVitals": MIN_TRUSTED_VITALS,
        "recentWindowMinutes": RECENT_MINUTES,
        "staleAfterMinutes": STALE_MINUTES,
        "sources": sources,
        "latest": {k: {"value": p["value"], "effective": p["effective"], "observation": p["observation"],
                       "score": p["score"], "baseline": p["baseline"]} for k, p in params.items()},
    }


def record_transition(db_path: str, pid: str, risk: dict, summary: dict, mode: str, now: datetime) -> dict | None:
    """Store an alert event if the assessed level changed. Returns the event or None."""
    if not summary["assessable"]:
        return None
    level = risk["level"]
    with connect(db_path) as c:
        row = c.execute("SELECT level FROM patient_risk_state WHERE patient_id = ?", (pid,)).fetchone()
        prev = row["level"] if row else "NORMAL"
        c.execute("INSERT INTO patient_risk_state (patient_id, level, updated_at) VALUES (?,?,?) "
                  "ON CONFLICT(patient_id) DO UPDATE SET level = excluded.level, updated_at = excluded.updated_at",
                  (pid, level, now.isoformat()))
        if level == prev:
            return None
        rank = detector.RANK
        if level == "NORMAL":
            kind = "resolved"
        elif prev == "NORMAL":
            kind = "raised"
        else:
            kind = "escalated" if rank[level] > rank[prev] else "de-escalated"
        top = next((a for a in risk["alerts"] if a["level"] == level), None) if level != "NORMAL" else None
        ev = {
            "patient_id": pid, "created_at": now.isoformat(), "kind": kind, "level": level, "previous_level": prev,
            "measured_at": (top or {}).get("effective") or summary["lastObservationAt"],
            "vital": (top or {}).get("vital"), "value": (top or {}).get("value"), "unit": (top or {}).get("unit"),
            "rule": (top or {}).get("rule"),
            "reason": top["reason"] if top else f"All trusted vitals back within the {('personalized ' if mode == 'personalized' else '')}thresholds.",
            "observation": (top or {}).get("observation"), "mode": mode,
        }
        cols = list(ev)
        cur = c.execute(f"INSERT INTO alert_events ({', '.join(cols)}) VALUES ({', '.join('?' for _ in cols)})", [ev[k] for k in cols])
        ev["id"] = cur.lastrowid
        return ev


def alert_events(db_path: str, pid: str | None = None, limit: int = 50) -> list[dict]:
    with connect(db_path) as c:
        if pid:
            rows = c.execute("SELECT * FROM alert_events WHERE patient_id = ? ORDER BY id DESC LIMIT ?", (pid, limit))
        else:
            rows = c.execute("SELECT * FROM alert_events ORDER BY id DESC LIMIT ?", (limit,))
        return [dict(r) for r in rows.fetchall()]


def reset_state(db_path: str, pid: str) -> None:
    """Forget the last assessed level (a new run starts unassessed). Alert history is kept."""
    with connect(db_path) as c:
        c.execute("DELETE FROM patient_risk_state WHERE patient_id = ?", (pid,))


async def assess(fhir: FhirClient, db_path: str, pid: str, mode: str = "personalized", record: bool = True,
                 now: datetime | None = None, since: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    readings = await recent_readings(fhir, pid, now, since=since)
    eligible = await scale2.cached_eligible(fhir, pid)
    risk = detector.evaluate(readings, mode=mode, scale2=eligible)
    summary = summarize(readings, risk, now)
    event = record_transition(db_path, pid, risk, summary, mode, now) if record else None
    return {"patientId": pid, "assessedAt": now.isoformat(), "spo2Scale": 2 if eligible else 1,
            **summary, "topReason": risk["alerts"][0]["reason"] if summary["assessable"] and risk["alerts"] and risk["level"] != "NORMAL" else None,
            "newAlert": event}


class Assessor:
    """Debounced per-patient re-assessment triggered by ingestion. Errors are kept, never raised."""

    def __init__(self, fhir: FhirClient, db_path: str, since_for=None):
        self.fhir, self.db_path = fhir, db_path
        self.since_for = since_for or (lambda pid: None)   # current-run window start per patient
        self._running: dict[str, asyncio.Task] = {}
        self._dirty: set[str] = set()
        self.last_error: str | None = None
        self.assessments = 0

    def request(self, pid: str) -> None:
        if pid in self._running and not self._running[pid].done():
            self._dirty.add(pid)
            return
        self._running[pid] = asyncio.create_task(self._loop(pid))

    async def _loop(self, pid: str) -> None:
        while True:
            self._dirty.discard(pid)
            try:
                await assess(self.fhir, self.db_path, pid, since=self.since_for(pid))
                self.assessments += 1
            except Exception as exc:  # recorded for /api/monitoring/status
                self.last_error = f"{type(exc).__name__}: {exc}"
            if pid not in self._dirty:
                return

    async def idle(self) -> None:
        tasks = [t for t in self._running.values() if not t.done()]
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
