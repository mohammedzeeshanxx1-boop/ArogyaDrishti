# Development utilities

The patient page has one simulation control, the **Live Simulation** panel (scenario, Start, Stop, Reset, progress, status), which drives the simulator endpoints below. Everything else here is an API endpoint or script, not UI.

| Purpose | How |
|---|---|
| Stream **simulated** wearable readings for one patient (through the normal ingestion endpoint) | `scripts/dev/simulate.sh <patient-id> [stable\|deterioration] [steps] [interval-s]` |
| Same, started from the API | `POST /api/demo/simulator/start {"patientId", "scenario"}` · `POST /api/demo/simulator/stop` · `POST /api/demo/reset` |
| Deterministic replay at 1×/5×/10× or batch, with pause/resume/reset | `POST /api/replay/sessions` then `POST /api/replay/sessions/{id}/start\|pause\|resume\|stop\|reset` (see `docs/REPLAY_SCHEMA.md`) |
| Fixed-threshold vs personalized evaluation (5 metrics) | `POST /api/evaluation/run {"patientId", "durationMinutes"}` · `GET /api/evaluation/latest` |
| Requirement evidence computed from live data | `GET /api/evidence` |
| End-to-end acceptance test (writes `.local/api/reports/acceptance-latest.json`) | `.venv/bin/python scripts/acceptance.py [--with-tests]` |
| All automated tests and the production build | `scripts/check.sh` |
| FHIR inspection | `GET /api/inspector/observations/{id}` · `GET /api/inspector/ingestions` |

Patient ids: see `.local/api/credentials.json` (patientId) after `scripts/dev/accounts.sh`.

## Sign-in and authorization

The API requires sign-in (`AUTH_REQUIRED=true` by default; tests build `Settings` directly with it off). `scripts/dev/accounts.sh` creates one `doctor` account and one account per synthetic patient with random passwords (PBKDF2 hashes in SQLite; plain passwords only in `.local/api/credentials.json`, mode 600). `--reset` issues new passwords. Sessions are HttpOnly SameSite=Strict cookies (12 h). An ASGI middleware enforces, for HTTP and WebSocket: public status/meta/auth routes; doctor: all routes; patient: GET of their own `/api/patients/{id}/profile`, `/api/demo/monitor/{id}` and `/ws/monitor/{id}` only; everything else denied. The in-process simulator posts observations with a per-process internal token. `scripts/dev/simulate.sh` and `scripts/acceptance.py` sign in as the local doctor.

Not covered: HAPI FHIR itself (port 8090) has no authentication and must stay bound to localhost; no HTTPS on localhost (set `COOKIE_SECURE=true` behind TLS); no password change UI; failed sign-ins are throttled in memory only.

## Monitoring workflow (what the dashboard shows)

```
observation source (today: simulated, labelled in every Observation's device.display)
  → POST /api/fhir/Observation (strict validation + HAPI $validate) → HAPI FHIR (stored, read back)
  → server-side assessment (app/monitoring.py): Sensor Trust Engine → partial NEWS2-style score → personal baselines
  → alert event recorded in SQLite when the risk level changes (GET /api/alerts)
  → WebSocket /ws/monitor/{id} (polling fallback) and GET /api/clinical/overview → dashboard
```

- A patient is assessed only with a trusted reading for at least 3 of 4 vitals in the last `MONITOR_RECENT_MINUTES` (default 60). Otherwise the dashboard shows "Not assessed", never NORMAL.
- Data older than `MONITOR_STALE_MINUTES` (default 15) is marked stale.
- No physical device integration exists; `/api/monitoring/status` always reports `physicalDevicesConnected: 0`.
- No simulator starts automatically.
- Start and Reset set a current-run view for the patient: the dashboard, the overview and the server-side assessment then use only readings from that run (never older than the 60-minute window), and the patient's last assessed level is cleared so the new run's alerts are raised afresh. Stored FHIR Observations and alert history are never deleted.
- A 20-step run has too few readings to form a personal baseline (at least 20 older trusted readings per vital are needed), so the vital cards show "needs more readings"; baselines are exercised by the replay lab and unit tests.
