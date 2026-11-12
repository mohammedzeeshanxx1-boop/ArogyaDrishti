# Development utilities

The clinician dashboard contains no demo or test controls. These tools remain for development, verification and evaluation. They are API endpoints or scripts, not UI.

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

Patient ids: `curl -s http://localhost:8000/api/patients`.

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
