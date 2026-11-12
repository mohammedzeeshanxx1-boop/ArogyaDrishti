# Checkpoints

Rule: a checkpoint is closed only with code, tests, the commands run and their actual results. Anything that could not be run is listed as BLOCKED, never assumed.

## Plan

C1 onward is a proposed split and has not been confirmed by the project owner.

| ID | Scope | Status |
|---|---|---|
| C0 | Scaffold and service startup | Done, with blockers below |
| C1 | FHIR R4 Vital Signs ingestion and HAPI storage (requirement 1) | Not started |
| C2 | Virtual wearable simulator and BIDMC replay (requirement 2) | Not started |
| C3 | At least 5 Synthea patient profiles with conditions and medications (requirement 3) | Not started |
| C4 | NEWS2-style baseline and at least 2 personalization rules (requirement 4) | Not started |
| C5 | Sensor artifact detection and false-alert suppression (requirement 5) | Not started |
| C6 | Clinician dashboard, Watch/Review/Urgent alerts, explanations (requirement 6) | Not started |
| C7 | Scenario replay and comparative performance report (requirement 7) | Not started |

---

## C0: scaffold and service startup

Run on 2026-11-12 in a Linux cloud workspace: Python 3.13.18, Node 22.23.4, npm 10.9.9, Docker 29.9.3, Compose v5.7.0.

### Blockers

| # | Blocked item | Cause | What it prevents | How to clear |
|---|---|---|---|---|
| B1 | Reading the PS-03 PDF | The repository contained only a one-line `README.md`; no PDF was found | The seven requirements and five criteria are taken from the project brief, not verified against the PDF | Add the PDF to the repository |
| B2 | `docker compose up` (all four containers) | The workspace network policy denies Docker Hub (`registry-1.docker.io` returned 403), so no base image can be pulled | No container was built or started. `hapi-fhir` and `database` have **never been started**. The pinned tag `hapiproject/hapi:v7.4.0`, the HAPI PostgreSQL environment settings and the persistent volume are untested | Run `docker compose up -d --build && scripts/smoke.sh` on a machine with Docker Hub access |
| B3 | `scripts/smoke.sh` | Depends on B2 | Script is written but has never been executed | Same as B2 |

### Passing checks

`PYTHON=/tmp/venv/bin/python scripts/check.sh` reported `ALL CHECKS PASSED`:

| Check | Command | Result |
|---|---|---|
| API tests | `cd apps/api && python -m pytest -q` | 9 passed |
| Scaffold and compose contract | `python -m pytest -q tests` | 21 passed |
| Web type-check | `npm --prefix apps/web run typecheck` | no errors |
| Web tests | `npm --prefix apps/web run test` | 3 passed |
| Web build | `npm --prefix apps/web run build` | built (JS 224.55 kB, 70.51 kB gzip) |
| Compose file | `docker compose --env-file .env.example config --quiet` | valid |

One deprecation warning appears in the API tests (Starlette test client and `httpx`); it does not affect results.

### Native startup (api and web, without containers)

API started with `uvicorn app.main:app --port 8000`, web with `npx vite --port 5173`.

| Probe | Actual result |
|---|---|
| `GET :8000/health` | `{"status":"ok"}` |
| `GET :8000/api/v1/status` | `api` ok, `eventStore` ok (schema version 1), `fhir` **unreachable** (`ConnectError`), which is correct because HAPI was not running |
| `GET :5173/` | page served, title "Arogya Drishti" |
| `GET :5173/api/v1/meta` (through the web proxy) | brand, tagline, disclaimer, checkpoint `C0` |
| WebSocket `:5173/ws/heartbeat` (through the web proxy) | received `hello`, then `pong` after `ping` |

The page was not opened in a browser; it was verified by HTTP and by the component tests.

### Failures

- `docker compose build api` failed: `python:3.13-slim: ... registry-1.docker.io ... Forbidden` (blocker B2). No other check failed.

### Not in C0, by design

No FHIR ingestion, simulator, BIDMC data, Synthea profiles, scoring, artifact detection, alerts, replay or report. `services/synthea` and `services/bidmc` contain only a README.
