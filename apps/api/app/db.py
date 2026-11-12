"""SQLite store for app-only event metadata.

FHIR resources (Patient, Observation, ...) are never stored here; they live in
HAPI FHIR. At C0 this module only creates the database and records a schema
version so that service startup can be verified.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

SCHEMA_VERSION = 1


def init_db(path: str) -> None:
    if path != ":memory:":
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE IF NOT EXISTS app_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        conn.execute(
            "INSERT INTO app_meta (key, value) VALUES ('schema_version', ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (str(SCHEMA_VERSION),),
        )


def check_db(path: str) -> dict:
    try:
        with sqlite3.connect(path) as conn:
            row = conn.execute("SELECT value FROM app_meta WHERE key = 'schema_version'").fetchone()
    except sqlite3.Error as exc:
        return {"status": "error", "detail": str(exc)}
    if row is None:
        return {"status": "error", "detail": "schema_version missing"}
    return {"status": "ok", "schemaVersion": int(row[0])}
