# Checkpoints

Rule: a checkpoint is closed only with code, tests, the commands run and their actual results. Anything that could not be run is listed as BLOCKED, never assumed.

## Plan

C0 and C1 scope were set by the project owner. C2 onward is a proposed split, not yet confirmed.

| ID | Scope | Status |
|---|---|---|
| C0 | Scaffold and service startup | Done, with blockers |
| C1 | FHIR R4 Vital Signs ingestion and HAPI storage (requirement 1); Synthea discharge profiles (requirement 3) | Done on a local HAPI server; Docker path still blocked |
| C2 | Virtual wearable simulator and BIDMC replay (requirement 2) | Not started |
| C3 | (requirement 3 was delivered in C1) | — |
| C4 | NEWS2-style baseline and at least 2 personalization rules (requirement 4) | Not started |
| C5 | Sensor artifact detection and false-alert suppression (requirement 5) | Not started |
| C6 | Clinician dashboard, Watch/Review/Urgent alerts, explanations (requirement 6) | Not started |
| C7 | Scenario replay and comparative performance report (requirement 7) | Not started |

## Open blockers

| # | Blocked item | Status |
|---|---|---|
| B1 | PS-03 PDF not in the repository | Open |
| B2 | Docker Hub (and GHCR, Quay, ECR, Maven Central) denied from the build environment; no container built or started | Open. C1 worked around it for HAPI only (see C1) |
| B3 | `scripts/smoke.sh` never executed | Open (depends on B2) |

---

## C1: FHIR R4 ingestion, HAPI storage, Synthea discharge profiles

Run on 2026-11-12 in the same Linux cloud workspace as C0.

### How HAPI was run (read this first)

Docker images still cannot be pulled here (B2), so the official `hapiproject/hapi` image on PostgreSQL defined in `docker-compose.yml` was **not** used. The C1 evidence comes from a real HAPI JPA server started from the **official HAPI FHIR 5.7.0 CLI release** (`run-server -v r4`, on-disk Derby database), downloaded from GitHub releases and checked by SHA-256.

Two things were needed to start it, both scripted in `infra/hapi-local/run.sh` and explained in `infra/hapi-local/README.md`:
- It runs on a Java 11 runtime (OpenJDK 11.0.13 Temurin, installed from PyPI package `jdk4py==11.0.13.1`).
- Out of the box `run-server` crashes on both Java 11 and 21: Hibernate's Jandex cannot index 10 Guava classes. The script strips only the type-use annotation attributes from those 10 classes in a copy of the jar. Re-scan: 92,335 classes, 0 failures.

Result: `GET /baseR4/metadata` → `CapabilityStatement`, `fhirVersion 4.0.1`, software `HAPI FHIR Server 5.7.0`.

**Not verified:** HAPI on PostgreSQL in Docker, the `hapiproject/hapi:v7.4.0` tag, and persistence of the PostgreSQL volume. The API code is the same for both servers; only `FHIR_BASE_URL` differs (`/baseR4` here, `/fhir` in Docker).

### What was built

| Item | Where |
|---|---|
| Strict local validator for the four vitals (status, category, LOINC coding, subject, effectiveDateTime, valueQuantity/UCUM, unknown elements) | `apps/api/app/vitals.py` |
| Ingestion pipeline: local validation → subject exists → HAPI `$validate` against the R4 vital-sign profile → store → read back and compare | `apps/api/app/ingest.py` |
| HAPI client (read, create, `$validate`, paged search, count) | `apps/api/app/fhir.py` |
| Ingestion event log, accepted and rejected (rejected payloads kept only as SHA-256) | `apps/api/app/db.py` (schema v2) |
| Patients list and discharge profile | `apps/api/app/patients.py` |
| Synthea pipeline: fetch (pinned v3.4.0, SHA-256), generate (fixed seeds), select, import, verify | `services/synthea/pipeline.py`, `synthea.lock.json` |
| Opt-in Compose job for the Synthea import (untested, B2) | `services/synthea/Dockerfile`, `docker-compose.yml` profile `seed` |
| Restart persistence check | `scripts/c1_persistence_check.py` |
| Local HAPI fallback | `infra/hapi-local/` |

Endpoints added:

| Method and path | Purpose |
|---|---|
| `POST /api/fhir/Observation` | Ingest one vital sign; 201 with ids, validation and read-back; 422 `OperationOutcome` on rejection; 503 if HAPI is down |
| `GET /api/fhir/Observation?patient=&code=` | Ingested observations for a patient, from HAPI |
| `GET /api/patients` | The synthetic discharge cohort |
| `GET /api/patients/{id}/profile` | Demographics, latest discharge, active conditions, active medications, allergies, care plans, vital counts, completeness |
| `GET /api/inspector/observations/{id}` | FHIR Inspector: stored resource, live local and HAPI validation, ingestion history |
| `GET /api/inspector/ingestions` | Recent ingestion events, including rejections |

### Supported vitals

| LOINC | Vital | R4 profile | UCUM |
|---|---|---|---|
| 8867-4 | Heart rate | `heartrate` | `/min` |
| 2708-6 | Oxygen saturation | `oxygensat` | `%` |
| 9279-1 | Respiratory rate | `resprate` | `/min` |
| 8310-5 | Body temperature | `bodytemp` | `Cel`, `[degF]` |

Value bounds reject only physically impossible numbers (e.g. SpO2 above 100 %). Possible but implausible readings such as 0 bpm are accepted on purpose so that the C5 artifact detector can see them.

### Synthea

| Step | Command | Actual result |
|---|---|---|
| fetch | `python3 services/synthea/pipeline.py fetch` | Synthea v3.4.0 jar verified, SHA-256 `38678aab…5702432` |
| generate | `… generate` | 18 patient bundles (12 alive, 6 deceased), 25.3 s; seed 20260301, reference date 2026-11-01, ages 55–85, Massachusetts |
| reproducibility | same arguments run twice | all 18 patient bundles and both info bundles byte-identical |
| select | `… select` | 8 of 18 eligible (alive, ≥1 inpatient stay, ≥1 active condition, ≥1 active medication) |
| import | `… import --fhir-base http://localhost:8090/baseR4` | hospital and practitioner bundles, then 8 transactions with 7,926 entries, 0 entry errors, 78.7 s |
| idempotency | re-imported one bundle | Patient count stayed 8; every entry `200 OK` |
| verify | `… verify` | 8/8 OK: Patient readable by Synthea UUID, active conditions and medications present, inpatient count matches, every subject is `Patient/<uuid>` |

The 10 non-selected patients: 6 deceased, 4 alive with no inpatient stay.

Cohort (synthetic, from `services/synthea/output/manifest.json`):

| Patient (Synthea UUID) | Sex | Born | Last discharge | Active conditions | Active meds |
|---|---|---|---|---|---|
| 1716c10f-ea14-a88c-3aee-f11e047be6b8 | F | 1969 | 2026-08-19 | 11 | 4 |
| 66127cbf-a739-2bef-6f6b-6951906ff738 | M | 1944 | 2026-06-04 | 22 | 12 |
| b651508d-0bbe-1c83-72f7-b4a36466beb6 | F | 1950 | 2026-02-25 | 22 | 9 |
| a679696c-4bf6-2ba4-8aa3-197a4d87d72f | F | 1948 | 2026-02-21 | 16 | 4 |
| 9e0102e7-fb9f-6374-1b3c-96362325269b | F | 1953 | 2026-01-29 | 15 | 11 |
| 88967114-c92a-2b59-06ff-a60a2c76e10a | F | 1966 | 2025-10-28 | 12 | 3 |
| b921174b-e2eb-2053-5419-f56a8c684602 | F | 1943 | 2025-01-26 | 13 | 11 |
| 4ac09a28-e37e-064d-2ba4-970f6627b019 | F | 1949 | 2023-07-24 | 29 | 17 |

Imported per patient: Patient, Encounter, Condition, MedicationRequest, Medication, AllergyIntolerance, CarePlan, CareTeam and vital-sign Observations. Claims, EOBs, labs, procedures, imaging, documents and provenance were left out. The subset has 0 dangling references; all external references resolve to Synthea's hospital/practitioner bundles. Entries are imported with PUT and the Synthea UUID as id, so Patient ids are stable and re-imports are idempotent. Synthea output is not committed (`services/synthea/output/` is git-ignored); it is regenerated from the lock file.

### Tests and checks

`PYTHON=/tmp/venv/bin/python HAPI_TEST_FHIR_BASE=http://localhost:8090/baseR4 scripts/check.sh` reported `ALL CHECKS PASSED`:

| Check | Result |
|---|---|
| API unit and flow tests (`-m "not live"`) | 66 passed |
| API live tests against real HAPI (`-m live`) | 21 passed |
| Scaffold and Compose contract tests | 24 passed |
| Web type-check, tests (3), build | passed |
| `docker compose --profile seed config` | valid |

Live tests, against HAPI 5.7.0 at `/baseR4`:
- HAPI declares FHIR 4.0.x; the API status endpoint sees it as R4.
- Heart rate, SpO2, respiratory rate, body temperature in °C and in °F are each ingested (201, HAPI `$validate` 0 errors), read **directly from HAPI** with matching status, subject, LOINC, value, UCUM and declared profile, and found again by patient+code search.
- HAPI's official validator accepts examples of all four vitals and rejects a heart rate with no category and one with `%` as its unit.
- Wrong unit, missing subject, future time, unsupported LOINC, missing timezone, unknown patient and non-object bodies all return 422 `OperationOutcome`, and the count of ingested Observations in HAPI does not change.
- The Inspector returns the stored Observation, local validation passed, HAPI validation (0 errors, profile `oxygensat`) and the accepted ingestion event with a matching read-back.
- ≥5 patients listed; every profile is complete (demographics, discharge encounter, active conditions with SNOMED codes, active medications, all references pointing at the patient); cohort ids match the Synthea manifest; an unknown patient returns 404.

Unit tests (no HAPI): 36 invalid-payload cases each rejected at the expected FHIR path; all four vitals accepted; profile and tag added without mutating input; API flow with a stand-in HAPI covering rejection before HAPI, unknown patient, HAPI validation errors, read-back mismatch reported as 502, HAPI down as 503, and bad ids as 400.

BLOCKED behaviour: with `HAPI_TEST_FHIR_BASE=http://localhost:9999/fhir` the live suite reports `SKIPPED … BLOCKED: HAPI FHIR not reachable at http://localhost:9999/fhir/metadata` and does not pass.

### Persistence across restart

`scripts/c1_persistence_check.py record` ingested one Observation per vital (ids 8229–8232). HAPI was stopped (metadata then returned no response) and started again on the same data directory (back after about 25 s). `check` then gave PASS for all 4 Observations (content SHA-256 unchanged) and all 8 cohort patients: `PERSISTENCE CHECK PASSED`.

### Findings during C1

- This HAPI 5.7.0 server **ignores the `?profile=` parameter of `$validate`** and enforces only profiles declared in `meta.profile`. Observed: a heart rate without category gave no errors with `?profile=…heartrate` but two category errors when the profile was in `meta.profile`. The client now always adds the profile to `meta.profile`, and a test asserts this.
- A paging bug in `pipeline.py verify` (HAPI's next-page links are absolute) was found by the first verify run and fixed.

### Failures and blockers

- No C1 check failed in its final run.
- Blocker B2 still stands for the Docker stack, the PostgreSQL volume and the `synthea-import` Compose job, none of which have been run.

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
