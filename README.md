# Arogya Drishti

**See the warning signs before they become emergencies.**

A personalized post-discharge deterioration monitor, built for MineArena 1.0 problem statement PS-03.

> Clinical decision support only. Not for medical diagnosis.

## Current state: checkpoint C1

- **Built and tested against a real HAPI FHIR R4 server:** strict ingestion of four vital signs (heart rate, SpO2, respiratory rate, body temperature) with HAPI `$validate`, storage, read-back and restart persistence; 8 Synthea-generated discharge profiles with conditions and medications; patient, profile and FHIR Inspector endpoints.
- **Not built yet:** simulator and BIDMC replay, scoring, artifact detection, alerts, dashboard views, replay and report.
- **Development is localhost-first, without Docker:** web on http://localhost:5173, API on http://localhost:8000, HAPI FHIR (native Java) on http://localhost:8090/baseR4. The Docker stack is kept for later deployment but has not been run.

See [CHECKPOINTS.md](CHECKPOINTS.md) for every command and its actual result.

| Service | Tech | Role | Port |
|---|---|---|---|
| `web` | React, Vite, TypeScript, Tailwind (Recharts installed, unused until the dashboard) | Clinician dashboard shell; shows live service status | 8080 |
| `api` | Python, FastAPI, WebSockets | Ingestion, patients, FHIR Inspector | 8000 |
| `hapi-fhir` | HAPI FHIR JPA server, R4 | Stores all FHIR resources | 8090 |
| `database` | PostgreSQL | Persistence for HAPI FHIR | internal |
| `synthea-import` (opt-in, profile `seed`) | Synthea + Python | Generates and loads the synthetic cohort | — |

App-only event metadata goes to SQLite on the `api` volume. FHIR resources are never stored there.

## Round 1 demo (MVP)

```bash
scripts/dev/up.sh            # then open http://localhost:5173
```
Pick a patient → **Demonstrate Gradual Deterioration** (risk escalates WATCH → REVIEW → URGENT in about 30 s) or **Demonstrate Stable Recovery** (stays NORMAL). The script is in [docs/DEMO_SCRIPT.md](docs/DEMO_SCRIPT.md). The risk engine is a labelled prototype (not NEWS2); see CHECKPOINTS.md "ROUND 1 MVP" for exactly what is and is not built.

## Run on localhost (development)

Needs Python 3.10+, Node 20+, Java 11+ on PATH (for Synthea) and curl.

```bash
scripts/dev/setup.sh      # once: .venv, npm packages, Java 11 runtime for HAPI
scripts/dev/up.sh         # HAPI :8090, API :8000, web :5173 in the background, then health check
scripts/dev/seed.sh       # once: generate the Synthea cohort and load it into HAPI
scripts/dev/health.sh     # PASS / FAIL / BLOCKED per service
scripts/dev/down.sh       # stop (data in .local/ is kept)
```

Or run each in its own terminal: `scripts/dev/start-hapi.sh`, `scripts/dev/start-api.sh` (`RELOAD=1` for auto-reload), `scripts/dev/start-web.sh`. Settings live in `.env.local.example`; copy it to `.env.local` to override. Logs go to `.local/logs/`.

HAPI runs from the official HAPI FHIR 5.7.0 CLI with a small, documented jar patch (`infra/hapi-local/README.md`). If it cannot start, `health.sh` reports HAPI as BLOCKED and the live FHIR tests are skipped as BLOCKED, never passed.

## Run with Docker (later deployment; untested)

```bash
cp .env.example .env                                    # then change POSTGRES_PASSWORD
docker compose up -d --build
docker compose --profile seed run --rm synthea-import
scripts/smoke.sh
```

## API

| Method and path | Purpose |
|---|---|
| `POST /api/fhir/Observation` | Ingest one R4 vital-sign Observation |
| `GET /api/fhir/Observation/{id}` | One stored Observation, read from HAPI |
| `GET /api/fhir/Observation?patient=&code=` | Ingested observations for a patient |
| `GET /api/patients` | Synthetic discharge cohort |
| `GET /api/patients/{id}/profile` | Discharge profile with completeness check |
| `GET /api/inspector/observations/{id}` | Stored Observation with live validation and ingestion history |
| `GET /api/inspector/ingestions` | Recent accepted and rejected submissions |
| `POST /api/demo/simulator/start` · `/stop` · `GET /api/demo/simulator` | Virtual wearable (scenarios `stable`, `deterioration`) |
| `POST /api/demo/reset` | Start a fresh monitoring window for a patient |
| `GET /api/demo/monitor/{id}` | Vitals, prototype risk with explanations, FHIR proof (all read from HAPI) |
| `GET /api/v1/status`, `/api/v1/meta`, `/health`, `WS /ws/heartbeat` | Service status |

Rejections are FHIR `OperationOutcome` resources. Interactive docs: http://localhost:8000/docs.

## Checks

```bash
scripts/check.sh          # uses .venv and the localhost URLs by default
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
scripts           dev/ (localhost start, stop, health, seed), check.sh, smoke.sh (containers), c1_persistence_check.py
docs              architecture and requirement traceability
```

## Documents

[CHECKPOINTS.md](CHECKPOINTS.md) · [EVALUATION.md](EVALUATION.md) · [DEPLOYMENT.md](DEPLOYMENT.md) · [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) · [docs/REQUIREMENTS_TRACE.md](docs/REQUIREMENTS_TRACE.md)
