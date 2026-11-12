# Arogya Drishti

**See the warning signs before they become emergencies.**

A personalized post-discharge deterioration monitor, built for MineArena 1.0 problem statement PS-03.

> Clinical decision support only. Not for medical diagnosis.

## Current state: checkpoint C1

- **Built and tested against a real HAPI FHIR R4 server:** strict ingestion of four vital signs (heart rate, SpO2, respiratory rate, body temperature) with HAPI `$validate`, storage, read-back and restart persistence; 8 Synthea-generated discharge profiles with conditions and medications; patient, profile and FHIR Inspector endpoints.
- **Not built yet:** simulator and BIDMC replay, scoring, artifact detection, alerts, dashboard views, replay and report.
- **Caveat:** the C1 evidence used a local HAPI 5.7.0 server (`infra/hapi-local`), because container images could not be pulled in the build environment. The Docker stack is defined but has not been run.

See [CHECKPOINTS.md](CHECKPOINTS.md) for every command and its actual result.

| Service | Tech | Role | Port |
|---|---|---|---|
| `web` | React, Vite, TypeScript, Tailwind (Recharts installed, unused until the dashboard) | Clinician dashboard shell; shows live service status | 8080 |
| `api` | Python, FastAPI, WebSockets | Ingestion, patients, FHIR Inspector | 8000 |
| `hapi-fhir` | HAPI FHIR JPA server, R4 | Stores all FHIR resources | 8090 |
| `database` | PostgreSQL | Persistence for HAPI FHIR | internal |
| `synthea-import` (opt-in, profile `seed`) | Synthea + Python | Generates and loads the synthetic cohort | — |

App-only event metadata goes to SQLite on the `api` volume. FHIR resources are never stored there.

## Run with Docker

```bash
cp .env.example .env                                    # then change POSTGRES_PASSWORD
docker compose up -d --build
docker compose --profile seed run --rm synthea-import   # generate and load the cohort
scripts/smoke.sh
```

## Run without Docker

```bash
JAVA11=/path/to/java11 infra/hapi-local/run.sh          # HAPI R4 on http://localhost:8090/baseR4
python3 services/synthea/pipeline.py all --fhir-base http://localhost:8090/baseR4

python3 -m venv .venv && .venv/bin/pip install -r apps/api/requirements-dev.txt
(cd apps/api && FHIR_BASE_URL=http://localhost:8090/baseR4 ../../.venv/bin/uvicorn app.main:app --port 8000)
npm --prefix apps/web ci && npm --prefix apps/web run dev    # http://localhost:5173
```

## API

| Method and path | Purpose |
|---|---|
| `POST /api/fhir/Observation` | Ingest one R4 vital-sign Observation |
| `GET /api/fhir/Observation?patient=&code=` | Ingested observations for a patient |
| `GET /api/patients` | Synthetic discharge cohort |
| `GET /api/patients/{id}/profile` | Discharge profile with completeness check |
| `GET /api/inspector/observations/{id}` | Stored Observation with live validation and ingestion history |
| `GET /api/inspector/ingestions` | Recent accepted and rejected submissions |
| `GET /api/v1/status`, `/api/v1/meta`, `/health`, `WS /ws/heartbeat` | Service status |

Rejections are FHIR `OperationOutcome` resources. Interactive docs: http://localhost:8000/docs.

## Checks

```bash
PYTHON=.venv/bin/python HAPI_TEST_FHIR_BASE=http://localhost:8090/baseR4 scripts/check.sh
```

Live tests need a running HAPI. Without one they are skipped with a `BLOCKED:` reason, never passed.

## Layout

```
apps/api          FastAPI service; tests/ (unit) and tests/integration/ (live HAPI)
apps/web          React dashboard
services/synthea  Synthea pipeline (pinned version, seeds, selection, import, verify)
services/bidmc    BIDMC PhysioNet replay (not implemented yet)
infra             nginx config; hapi-local/ fallback HAPI server
tests             repository-level tests
scripts           check.sh, smoke.sh, c1_persistence_check.py
docs              architecture and requirement traceability
```

## Documents

[CHECKPOINTS.md](CHECKPOINTS.md) · [EVALUATION.md](EVALUATION.md) · [DEPLOYMENT.md](DEPLOYMENT.md) · [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) · [docs/REQUIREMENTS_TRACE.md](docs/REQUIREMENTS_TRACE.md)
