"""Doctor notifications over the recorded risk events (monitoring.alert_events).

Nothing here assesses risk: the events are the ones the server-side risk engine recorded. This module adds,
per doctor account:
  * a baseline cursor, set the first time the account reads its notifications, so older history (e.g. earlier
    simulation runs) is never presented as new or unread;
  * read receipts (bell state) and acknowledgements (a clinical record: event id, account, time).
Acknowledging or reading never changes or deletes an alert event.
"""

from __future__ import annotations

import json

from datetime import datetime, timezone

from .db import connect

SCHEMA = """
CREATE TABLE IF NOT EXISTS notification_cursors (
    username   TEXT PRIMARY KEY,
    since_id   INTEGER NOT NULL,      -- events with id <= since_id predate this account's notifications
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS alert_receipts (
    event_id INTEGER NOT NULL,
    username TEXT NOT NULL,
    read_at  TEXT NOT NULL,
    PRIMARY KEY (event_id, username)
);
CREATE TABLE IF NOT EXISTS alert_acknowledgements (
    event_id        INTEGER NOT NULL,
    username        TEXT NOT NULL,
    acknowledged_at TEXT NOT NULL,
    PRIMARY KEY (event_id, username)
);
"""

KIND_TEXT = {"raised": "Raised", "escalated": "Escalated", "de-escalated": "De-escalated", "resolved": "Resolved"}
VITAL_TEXT = {"heart_rate": ("Heart rate", "bpm", 0), "spo2": ("SpO₂", "%", 0), "respiratory_rate": ("Respiratory rate", "breaths/min", 0),
              "body_temperature": ("Temperature", "°C", 1)}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def init(db_path: str) -> None:
    with connect(db_path) as c:
        c.executescript(SCHEMA)


def latest_id(db_path: str) -> int:
    with connect(db_path) as c:
        return c.execute("SELECT COALESCE(MAX(id), 0) FROM alert_events").fetchone()[0]


def baseline(db_path: str, username: str) -> int:
    """The account's notification baseline; created at the current latest event on first use."""
    with connect(db_path) as c:
        row = c.execute("SELECT since_id FROM notification_cursors WHERE username = ?", (username,)).fetchone()
        if row:
            return row[0]
        since = c.execute("SELECT COALESCE(MAX(id), 0) FROM alert_events").fetchone()[0]
        c.execute("INSERT OR IGNORE INTO notification_cursors(username, since_id, created_at) VALUES (?,?,?)", (username, since, _now()))
        return since


NEWS2_ORDER = ["spo2", "heart_rate", "respiratory_rate", "body_temperature"]
NEWS2_NAMES = {"spo2": "SpO₂", "heart_rate": "Heart Rate", "respiratory_rate": "Respiratory Rate", "body_temperature": "Body Temperature"}


def _breakdown(e: dict) -> dict | None:
    try:
        b = json.loads(e.get("news2_json") or "null")
    except (TypeError, ValueError):
        return None
    return b if isinstance(b, dict) and b.get("parameters") is not None and b.get("total") is not None else None


def _classification(level: str, total: float, scores: list[int]) -> str | None:
    """Which band of the existing classification the stored total falls in (None if the level came from another rule)."""
    if level == "URGENT" and total >= 7:
        return "7 or higher → URGENT"
    if level == "REVIEW" and 5 <= total <= 6:
        return "5–6 → REVIEW"
    if level == "REVIEW" and 3 in scores:
        return "a single parameter scoring 3 → REVIEW"
    if level == "WATCH" and 1 <= total <= 4:
        return "1–4 → WATCH"
    if level == "NORMAL" and total == 0:
        return "0 → NORMAL"
    return None


def summary(e: dict) -> str:
    """Plain-language explanation from the stored event fields (no re-assessment)."""
    if e["kind"] == "resolved" or e["level"] == "NORMAL":
        head = f"Back to NORMAL from {e['previous_level']}" if e.get("previous_level") else "NORMAL"
    elif e.get("previous_level"):
        head = f"{KIND_TEXT[e['kind']]} from {e['previous_level']} to {e['level']}"
    else:
        head = f"Risk raised to {e['level']}"
    b = _breakdown(e)
    if b is not None:
        params = b["parameters"]
        parts = []
        for k in sorted((k for k in NEWS2_ORDER if k in params), key=lambda k: (-(params[k].get("score") or 0), NEWS2_ORDER.index(k))):
            label, unit, dec = VITAL_TEXT[k]
            v = params[k].get("value")
            parts.append(f"{NEWS2_NAMES[k]} {v:.{dec}f} {unit} (score {params[k].get('score')})" if v is not None else f"{NEWS2_NAMES[k]} (score {params[k].get('score')})")
        missing = [NEWS2_NAMES[k] for k in NEWS2_ORDER if k not in params]
        text = f"{head}. Partial NEWS2-style score {b['total']:g}"
        text += f": {', '.join(parts)}" if parts else ""
        text += f"; not available: {', '.join(missing)}" if missing else ""
        text += "."
        cls = _classification(e["level"], b["total"], [int(p.get("score") or 0) for p in params.values()])
        if cls:
            text += f" Classification: {cls}."
        elif e["level"] != "NORMAL" and e.get("reason"):
            text += f" {e['level']} from a personalized rule: {e['reason']}"
        text += f" Partial assessment: {b.get('measured', len(params))} of {b.get('of', 7)} NEWS2 parameters."
        return text
    # Events recorded before breakdowns were stored: say so instead of guessing the parameters.
    if e.get("vital") in VITAL_TEXT and e.get("value") is not None:
        label, unit, dec = VITAL_TEXT[e["vital"]]
        detail = f"{label} {e['value']:.{dec}f} {unit}"
    elif e.get("value") is not None:
        detail = f"partial NEWS2-style score {e['value']:g} (individual parameter scores were not recorded for this earlier alert)"
    else:
        detail = ""
    return f"{head}: {detail}." if detail else f"{head}."


def _acks(c, ids: list[int]) -> dict[int, list[dict]]:
    if not ids:
        return {}
    q = f"SELECT event_id, username, acknowledged_at FROM alert_acknowledgements WHERE event_id IN ({','.join('?' * len(ids))}) ORDER BY acknowledged_at"
    out: dict[int, list[dict]] = {}
    for r in c.execute(q, ids):
        out.setdefault(r["event_id"], []).append({"username": r["username"], "acknowledgedAt": r["acknowledged_at"]})
    return out


def decorate(c, rows: list[dict], username: str | None, since: int) -> list[dict]:
    ids = [r["id"] for r in rows]
    acks = _acks(c, ids)
    read = set()
    if username and ids:
        read = {r[0] for r in c.execute(f"SELECT event_id FROM alert_receipts WHERE username = ? AND event_id IN ({','.join('?' * len(ids))})", [username, *ids])}
    return [{**r, "summary": summary(r), "read": r["id"] <= since or r["id"] in read, "acknowledgements": acks.get(r["id"], []),
             "acknowledgedByMe": any(a["username"] == username for a in acks.get(r["id"], []))} for r in rows]


def unread_count(c, username: str, since: int) -> int:
    return c.execute("SELECT COUNT(*) FROM alert_events e WHERE e.id > ? AND NOT EXISTS "
                     "(SELECT 1 FROM alert_receipts r WHERE r.event_id = e.id AND r.username = ?)", (since, username)).fetchone()[0]


def feed(db_path: str, username: str, after: int | None = None, limit: int = 30) -> dict:
    """after=None: latest `limit` events (bell). after=N: events with id > N, oldest first (new-event delivery)."""
    since = baseline(db_path, username)
    with connect(db_path) as c:
        if after is None:
            rows = [dict(r) for r in c.execute("SELECT * FROM alert_events ORDER BY id DESC LIMIT ?", (limit,))]
        else:
            rows = [dict(r) for r in c.execute("SELECT * FROM alert_events WHERE id > ? ORDER BY id ASC LIMIT ?", (after, limit))]
        items = decorate(c, rows, username, since)
        return {"latestId": c.execute("SELECT COALESCE(MAX(id), 0) FROM alert_events").fetchone()[0],
                "baselineId": since, "unread": unread_count(c, username, since), "items": items}


def mark_read(db_path: str, username: str, ids: list[int]) -> int:
    now = _now()
    with connect(db_path) as c:
        existing = {r[0] for r in c.execute(f"SELECT id FROM alert_events WHERE id IN ({','.join('?' * len(ids))})", ids)} if ids else set()
        c.executemany("INSERT OR IGNORE INTO alert_receipts(event_id, username, read_at) VALUES (?,?,?)", [(i, username, now) for i in existing])
    return len(existing)


def mark_all_read(db_path: str, username: str) -> int:
    since = baseline(db_path, username)
    now = _now()
    with connect(db_path) as c:
        cur = c.execute("INSERT OR IGNORE INTO alert_receipts(event_id, username, read_at) SELECT id, ?, ? FROM alert_events WHERE id > ?",
                        (username, now, since))
        return cur.rowcount


def acknowledge(db_path: str, username: str, event_id: int) -> dict | None:
    """Record that this doctor acknowledged the event. The event itself is never modified."""
    now = _now()
    with connect(db_path) as c:
        if c.execute("SELECT 1 FROM alert_events WHERE id = ?", (event_id,)).fetchone() is None:
            return None
        c.execute("INSERT OR IGNORE INTO alert_acknowledgements(event_id, username, acknowledged_at) VALUES (?,?,?)", (event_id, username, now))
        c.execute("INSERT OR IGNORE INTO alert_receipts(event_id, username, read_at) VALUES (?,?,?)", (event_id, username, now))
        row = c.execute("SELECT acknowledged_at FROM alert_acknowledgements WHERE event_id = ? AND username = ?", (event_id, username)).fetchone()
        return {"eventId": event_id, "username": username, "acknowledgedAt": row[0]}


def with_acks(db_path: str, rows: list[dict], username: str | None) -> list[dict]:
    with connect(db_path) as c:
        since = c.execute("SELECT since_id FROM notification_cursors WHERE username = ?", (username,)).fetchone() if username else None
        return decorate(c, rows, username, since[0] if since else 0)
