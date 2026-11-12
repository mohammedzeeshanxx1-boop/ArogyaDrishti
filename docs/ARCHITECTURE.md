# Architecture

Status key: **built** exists and is tested; **planned** does not exist yet.

```
browser ──HTTP/WS──> web (nginx + React) ──/api, /ws──> api (FastAPI)
                                                         │        │
                                              FHIR REST  │        │ SQLite (app-only event metadata)
                                                         v
                                                  hapi-fhir (R4) ──JDBC──> database (PostgreSQL)
```

## Process model (localhost-first)

| Process | Started by | URL |
|---|---|---|
| Vite dev server (React) | `scripts/dev/start-web.sh` | http://localhost:5173 (proxies `/api`, `/health`, `/ws` to the API) |
| FastAPI (uvicorn) | `scripts/dev/start-api.sh` | http://localhost:8000 |
| HAPI FHIR 5.7.0 (Java 11, H2 in `.local/hapi/data`) | `scripts/dev/start-hapi.sh` | http://localhost:8090/baseR4 |
| Synthea pipeline (Python + Java) | `scripts/dev/seed.sh` | one-shot |
| Simulator, BIDMC replay, monitoring engine | planned as local Python processes (C2, C4, C5) | — |

All URLs come from environment variables (`.env.local.example`). In containers the same code runs with `FHIR_BASE_URL=http://hapi-fhir:8080/fhir` and nginx in front of the API.

## Data ownership

- **HAPI FHIR** is the only store for clinical data: Patient, Condition, MedicationRequest, Observation.
- **SQLite** holds app-only metadata: the schema version and the ingestion event log (accepted and rejected submissions; rejected payloads only as a SHA-256). It never holds FHIR resources.

## Components

| Component | Location | Status |
|---|---|---|
| Service shell: health, meta, status, heartbeat socket | `apps/api/app` | built |
| HAPI connectivity probe (`/fhir/metadata`, R4 check) | `apps/api/app/fhir.py` | built |
| Dashboard shell with live service status | `apps/web/src` | built |
| Vital Signs ingestion: strict validation, HAPI `$validate`, store, read-back | `apps/api/app/ingest.py`, `vitals.py` | built (C1) |
| Patients and discharge profiles | `apps/api/app/patients.py` | built (C1) |
| FHIR Inspector | `apps/api/app/main.py` (`/api/inspector/*`) | built (C1) |
| Virtual wearable simulator | `apps/api` | planned (C2) |
| BIDMC replay | `services/bidmc` | planned (C2) |
| Synthea generation and import pipeline | `services/synthea` | built (C1) |
| NEWS2-style baseline scorer | `apps/api` | planned (C4) |
| Patient-specific deterioration trend engine (personalization rules) | `apps/api` | planned (C4) |
| Sensor Trust Engine (artifact detection, alert suppression) | `apps/api` | planned (C5) |
| Alerts (Watch, Review, Urgent) with explanations | `apps/api`, `apps/web` | planned (C6) |
| Replay Lab (naive versus personalized) | `apps/api`, `apps/web` | planned (C7) |
| Judge Evidence Console (requirement-level verification) | `apps/web` | planned (C7) |

## Design constraints

- Monitoring logic is rule-based, deterministic and unit-tested. No external LLM calls in any clinical decision.
- Scenarios are seeded so every run is repeatable.
- The UI must never show a service or result as healthy without a live check. At C0 this is enforced by tests in both `apps/api/tests` and `apps/web/src/App.test.tsx`.
