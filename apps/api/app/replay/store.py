"""SQLite access for replay metadata (tables defined in app.db SCHEMA v3)."""

from __future__ import annotations

from ..db import connect
from .scenarios import GroundTruth, MeasurementEvent


def insert_session(path: str, row: dict) -> None:
    cols = list(row)
    with connect(path) as c:
        c.execute(f"INSERT INTO replay_sessions ({', '.join(cols)}) VALUES ({', '.join('?' for _ in cols)})", [row[k] for k in cols])


def update_session(path: str, session_id: str, **fields) -> None:
    if not fields:
        return
    with connect(path) as c:
        c.execute(f"UPDATE replay_sessions SET {', '.join(f'{k} = ?' for k in fields)} WHERE session_id = ?",
                  [*fields.values(), session_id])


def record_batch(path: str, session_id: str, batch_no: int, started: str, finished: str, events: list[MeasurementEvent],
                 outcome: str, created: int = 0, existing: int = 0, error: str | None = None,
                 observation_ids: list[str] | None = None, statuses: list[str] | None = None,
                 shape_validated: set[str] | None = None) -> None:
    with connect(path) as c:
        c.execute("INSERT OR REPLACE INTO replay_batches VALUES (?,?,?,?,?,?,?,?,?)",
                  (session_id, batch_no, started, finished, len(events), outcome, created, existing, error))
        if outcome == "confirmed":
            seen: set[str] = set()
            rows = []
            for e, oid, st in zip(events, observation_ids or [], statuses or []):
                shape = 1 if shape_validated and e.loinc in shape_validated and e.loinc not in seen else 0
                if shape:
                    seen.add(e.loinc)
                rows.append((session_id, e.seq, e.vital, e.loinc, e.measured_at.isoformat(), finished, oid, st, batch_no, shape))
            c.executemany("INSERT OR REPLACE INTO replay_events VALUES (?,?,?,?,?,?,?,?,?,?)", rows)


def save_ground_truth(path: str, session_id: str, truth: list[GroundTruth]) -> None:
    with connect(path) as c:
        c.executemany(
            "INSERT INTO replay_ground_truth (session_id, label, start_at, end_at, detail) VALUES (?,?,?,?,?)",
            [(session_id, t.label, t.start.isoformat(), t.end.isoformat() if t.end else None, t.detail) for t in truth],
        )


def ground_truth(path: str, session_id: str) -> list[dict]:
    """EVALUATION ONLY. Must not be called from the detection path."""
    with connect(path) as c:
        rows = c.execute("SELECT label, start_at, end_at, detail FROM replay_ground_truth WHERE session_id = ? ORDER BY id",
                         (session_id,)).fetchall()
    return [dict(r) for r in rows]


def session_row(path: str, session_id: str) -> dict | None:
    with connect(path) as c:
        r = c.execute("SELECT * FROM replay_sessions WHERE session_id = ?", (session_id,)).fetchone()
    return dict(r) if r else None


def event_rows(path: str, session_id: str) -> list[dict]:
    with connect(path) as c:
        return [dict(r) for r in c.execute("SELECT * FROM replay_events WHERE session_id = ? ORDER BY seq", (session_id,))]


def batch_rows(path: str, session_id: str) -> list[dict]:
    with connect(path) as c:
        return [dict(r) for r in c.execute("SELECT * FROM replay_batches WHERE session_id = ? ORDER BY batch_no", (session_id,))]


def event_by_observation(path: str, observation_id: str) -> dict | None:
    with connect(path) as c:
        r = c.execute("SELECT * FROM replay_events WHERE observation_id = ? ORDER BY ingested_at DESC LIMIT 1", (observation_id,)).fetchone()
    return dict(r) if r else None
