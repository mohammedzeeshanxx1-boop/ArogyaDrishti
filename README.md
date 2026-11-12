# Arogya Drishti

**See the warning signs before they become emergencies.**

A personalized post-discharge deterioration monitor, built for MineArena 1.0 problem statement PS-03.

> Clinical decision support only. Not for medical diagnosis.

## Current state: checkpoint C0 (scaffold and service startup)

The repository contains a runnable skeleton only. **No monitoring, alerting, patient data or replay exists yet**, and nothing here makes a clinical claim. See [CHECKPOINTS.md](CHECKPOINTS.md) for exactly what was run and what is blocked.

| Service | Tech | Role | Port |
|---|---|---|---|
| `web` | React, Vite, TypeScript, Tailwind (Recharts installed, unused until the dashboard) | Clinician dashboard shell; shows live service status | 8080 |
| `api` | Python, FastAPI, WebSockets | Monitoring API; at C0 only health, meta, status and a heartbeat socket | 8000 |
| `hapi-fhir` | HAPI FHIR JPA server, R4 | Stores all FHIR resources | 8090 |
| `database` | PostgreSQL | Persistence for HAPI FHIR | internal |

App-only event metadata goes to SQLite on the `api` volume. FHIR observations are never stored there.

## Run with Docker

```bash
cp .env.example .env        # then change POSTGRES_PASSWORD
docker compose up -d --build
scripts/smoke.sh            # waits for HAPI, then verifies all four services
```

Open http://localhost:8080. HAPI FHIR can take a minute or more on first boot; the dashboard shows it as unreachable until then.

## Run without Docker (api and web only)

```bash
python3 -m venv .venv && .venv/bin/pip install -r apps/api/requirements-dev.txt
(cd apps/api && ../../.venv/bin/uvicorn app.main:app --port 8000)
# second terminal
npm --prefix apps/web ci && npm --prefix apps/web run dev    # http://localhost:5173
```

## Checks

```bash
PYTHON=.venv/bin/python scripts/check.sh
```

Runs API tests, repository and compose contract tests, web type-check, web tests, web build and `docker compose config`.

## Layout

```
apps/api          FastAPI service and its tests
apps/web          React dashboard
services/synthea  Synthea patient generation (not implemented yet)
services/bidmc    BIDMC PhysioNet replay (not implemented yet)
infra             nginx config for the web container
tests             repository-level tests
scripts           check.sh, smoke.sh
docs              architecture and requirement traceability
```

## Documents

- [CHECKPOINTS.md](CHECKPOINTS.md): per-checkpoint evidence, with real command output
- [EVALUATION.md](EVALUATION.md): the five official metrics and how each will be measured
- [DEPLOYMENT.md](DEPLOYMENT.md): running and operating the stack
- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md), [docs/REQUIREMENTS_TRACE.md](docs/REQUIREMENTS_TRACE.md)
