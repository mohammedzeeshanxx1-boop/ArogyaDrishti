"""SQLite store for app-only event metadata.

FHIR resources are never stored here; they live in HAPI FHIR. This database
records ingestion events (accepted and rejected) so that the FHIR Inspector
can show what happened to each submission. Rejected payloads are stored only
as a SHA-256 hash, never in full.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

SCHEMA_VERSION = 3

SCHEMA = """
CREATE TABLE IF NOT EXISTS app_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS ingestion_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    received_at TEXT NOT NULL,
    outcome TEXT NOT NULL CHECK (outcome IN ('accepted', 'rejected', 'error')),
    stage TEXT NOT NULL,
    observation_id TEXT,
    version_id TEXT,
    patient_ref TEXT,
    loinc TEXT,
    payload_sha256 TEXT NOT NULL,
    issues_json TEXT NOT NULL,
    hapi_validation_json TEXT,
    read_back_matches INTEGER
);
CREATE INDEX IF NOT EXISTS ix_ingestion_obs ON ingestion_events(observation_id);

-- Replay metadata (schema v3). Measurement VALUES are never stored here; HAPI is the
-- only store of clinical data. These tables hold identifiers, timestamps and status
-- so that evaluation can join FHIR Observations to measurement and ingestion times.
CREATE TABLE IF NOT EXISTS replay_sessions (
    session_id TEXT PRIMARY KEY,
    source_kind TEXT NOT NULL,
    scenario_id TEXT,
    seed INTEGER,
    patient_id TEXT NOT NULL,
    anchor TEXT NOT NULL,
    duration_minutes INTEGER NOT NULL,
    interval_seconds INTEGER NOT NULL,
    speed TEXT NOT NULL,
    state TEXT NOT NULL,
    events_total INTEGER NOT NULL,
    events_fingerprint TEXT NOT NULL,
    events_created INTEGER NOT NULL DEFAULT 0,
    events_existing INTEGER NOT NULL DEFAULT 0,
    cursor INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    started_at TEXT,
    finished_at TEXT,
    last_error TEXT,
    reset_from TEXT
);
CREATE TABLE IF NOT EXISTS replay_events (
    session_id TEXT NOT NULL,
    seq INTEGER NOT NULL,
    vital TEXT NOT NULL,
    loinc TEXT NOT NULL,
    measured_at TEXT NOT NULL,      -- simulated / recorded measurement time (= effectiveDateTime)
    ingested_at TEXT NOT NULL,      -- wall-clock time HAPI confirmed the batch
    observation_id TEXT NOT NULL,
    persist_status TEXT NOT NULL CHECK (persist_status IN ('created', 'existing')),
    batch_no INTEGER NOT NULL,
    hapi_shape_validated INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (session_id, seq)
);
CREATE TABLE IF NOT EXISTS replay_batches (
    session_id TEXT NOT NULL,
    batch_no INTEGER NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT NOT NULL,
    size INTEGER NOT NULL,
    outcome TEXT NOT NULL CHECK (outcome IN ('confirmed', 'failed')),
    created INTEGER NOT NULL DEFAULT 0,
    existing INTEGER NOT NULL DEFAULT 0,
    error TEXT,
    PRIMARY KEY (session_id, batch_no)
);
-- EVALUATION ONLY. Read by app.replay.store.ground_truth(); never by the detector.
CREATE TABLE IF NOT EXISTS replay_ground_truth (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    label TEXT NOT NULL,
    start_at TEXT NOT NULL,
    end_at TEXT,
    detail TEXT
);
"""


def connect(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(path: str) -> None:
    if path != ":memory:":
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    with connect(path) as conn:
        conn.executescript(SCHEMA)
        conn.execute(
            "INSERT INTO app_meta (key, value) VALUES ('schema_version', ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (str(SCHEMA_VERSION),),
        )


def check_db(path: str) -> dict:
    try:
        with connect(path) as conn:
            row = conn.execute("SELECT value FROM app_meta WHERE key = 'schema_version'").fetchone()
    except sqlite3.Error as exc:
        return {"status": "error", "detail": str(exc)}
    if row is None:
        return {"status": "error", "detail": "schema_version missing"}
    return {"status": "ok", "schemaVersion": int(row[0])}


def record_ingestion(path: str, event: dict) -> int:
    cols = (
        "received_at", "outcome", "stage", "observation_id", "version_id", "patient_ref", "loinc",
        "payload_sha256", "issues_json", "hapi_validation_json", "read_back_matches",
    )
    row = {
        **{c: None for c in cols},
        **event,
        "issues_json": json.dumps(event.get("issues", [])),
        "hapi_validation_json": json.dumps(event["hapi_validation"]) if event.get("hapi_validation") is not None else None,
    }
    with connect(path) as conn:
        cur = conn.execute(
            f"INSERT INTO ingestion_events ({', '.join(cols)}) VALUES ({', '.join('?' for _ in cols)})",
            [row[c] for c in cols],
        )
        return int(cur.lastrowid)


def _event(row: sqlite3.Row) -> dict:
    d = dict(row)
    d["issues"] = json.loads(d.pop("issues_json"))
    hv = d.pop("hapi_validation_json")
    d["hapiValidation"] = json.loads(hv) if hv else None
    if d["read_back_matches"] is not None:
        d["read_back_matches"] = bool(d["read_back_matches"])
    return d


def ingestion_events(path: str, observation_id: str | None = None, limit: int = 50) -> list[dict]:
    with connect(path) as conn:
        if observation_id:
            rows = conn.execute("SELECT * FROM ingestion_events WHERE observation_id = ? ORDER BY id DESC", (observation_id,))
        else:
            rows = conn.execute("SELECT * FROM ingestion_events ORDER BY id DESC LIMIT ?", (limit,))
        return [_event(r) for r in rows.fetchall()]
