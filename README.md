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

## Using the prototype

Start the services (below), create the local accounts once with `scripts/dev/accounts.sh`, then open http://localhost:5173 and sign in.

- **Doctor Portal** (`#/doctor`, account `doctor`): dashboard with patient counts derived from live data, patient directory (search, status filter, sort), patient monitoring page (four live vital cards, interactive trend charts with time ranges, plain-language risk assessment with an expandable technical section, alert history, SpO₂ Scale 2 configuration) and a clearly labelled Demo / Simulation section (Stable Recovery or Gradual Deterioration; Start, Stop, Reset).
- **Doctor notifications**: real-time pop-ups for every new risk event recorded by the server (WATCH amber, REVIEW orange, URGENT red; recovery to NORMAL in teal) on every Doctor Portal page, plus a bell with unread count, mark as read / mark all as read and acknowledgement. Read and acknowledgement state is stored per doctor account; acknowledging never changes the alert.
- **Data Management** (`#/doctor/data`): Add Patient (FHIR Patient, plus an inpatient Encounter for the discharge date), explicit Patient Portal login creation (random one-time password), CSV import of patient records or vital-sign observations (validated in full first; nothing is written if any row is invalid), CSV export of the directory, a patient's record and a patient's vital-sign history.
- **Video Consultation**: links to the external SparkMeet service (`VITE_SPARKMEET_URL`, default https://sparkmeet-web.onrender.com/) from both portals; no patient data is put in the URL. Arogya Drishti does not create rooms or invitations.
- **Patient Portal** (`#/me`, one account per synthetic patient): My Health, My Health Trends, My Medical Records, My Profile, Video Consultation. A patient account can read only its own record; the server enforces this.

Accounts have random passwords (printed by `accounts.sh` and kept in `.local/api/credentials.json`, mode 600, gitignored). Patients without recent readings are shown as **Not assessed**. Developer tools are described in [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md).

## Run on localhost (development)

Needs **Python ≥ 3.10** (macOS's built-in 3.9 is not enough: `brew install python@3.12`), **Node ≥ 22.12** (`brew install node@22`; 20.19+ runs the app but not the web tests), curl, unzip and zip. Java is optional: `setup.sh` uses an installed Java 11/17/21 (e.g. `brew install openjdk@17`) or installs a private Java 17 into `.local/tools/jdk`. Every setup step reports PASS/FAIL with the exact fix, and `up.sh` refuses to start a service whose prerequisites are missing.

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

[CHECKPOINTS.md](CHECKPOINTS.md) · [DATA_SOURCES.md](DATA_SOURCES.md) · [FINAL_PRODUCT_GAP_ANALYSIS.md](FINAL_PRODUCT_GAP_ANALYSIS.md) · [FINAL_PRODUCT_PLAN.md](FINAL_PRODUCT_PLAN.md) · [EVALUATION.md](EVALUATION.md) · [DEPLOYMENT.md](DEPLOYMENT.md) · [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) · [docs/REQUIREMENTS_TRACE.md](docs/REQUIREMENTS_TRACE.md)
