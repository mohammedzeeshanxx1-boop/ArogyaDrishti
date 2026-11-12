# Checkpoints

Rule: a checkpoint is closed only with code, tests, the commands run and their actual results. Anything that could not be run is listed as BLOCKED, never assumed.

## Plan

C0 and C1 scope were set by the project owner. C2 onward is a proposed split, not yet confirmed.

Development is **localhost-first** (no Docker) since 2026-11-12; see "Localhost-first adaptation" below. Container files are kept for later deployment.

| ID | Scope | Status |
|---|---|---|
| C0 | Scaffold and service startup | PASS on localhost; container start BLOCKED (B2, deferred) |
| C1 | FHIR R4 Vital Signs ingestion and HAPI storage (req. 1); Synthea discharge profiles (req. 3) | PASS on localhost with native HAPI; re-verified as Phase 1 |
| R1-MVP | Round 1 end-to-end demo (simulator, prototype risk rules, dashboard, FHIR proof) | PASS, demo scope only (see below) |
| C2 | Virtual wearable simulator and BIDMC replay (req. 2) | Partial: demo simulator exists (R1-MVP); BIDMC replay not started, download BLOCKED here (B4) |
| C3 | (requirement 3 was delivered in C1) | — |
| C4 | NEWS2-style baseline and at least 2 personalization rules (req. 4) | Not started |
| C5 | Sensor artifact detection and false-alert suppression (req. 5) | Not started |
| C6 | Clinician dashboard, Watch/Review/Urgent alerts, explanations (req. 6) | Not started |
| C7 | Scenario replay and comparative performance report (req. 7) | Not started |

## Open blockers

| # | Blocked item | Status |
|---|---|---|
| B1 | PS-03 PDF not in the repository | Open |
| B2 | Container registries (Docker Hub, GHCR, Quay, ECR) and Maven Central denied from the build workspace; no container built or started | Deferred: development is localhost-first. Must be cleared before container deployment |
| B3 | `scripts/smoke.sh` (container smoke test) never executed | Deferred with B2 |
| B4 | Real BIDMC recordings cannot be downloaded in the build workspace: `physionet.org` and the `physionet-open` S3 bucket are both denied by its network policy (checked 2026-11-12) | Open; blocks the BIDMC half of C2 here. Clears if the files are added to the repo machine, or if PhysioNet is allowed for this workspace |

---

## Clinician-facing base prototype (2026-11-12, branch feature/clinical-dashboard)

Checkpoint before changes: branch `checkpoint/pre-clinical-ui` (= main `4e0d637`).

UI: hackathon controls removed from the dashboard (judge controls, demo and replay buttons, evaluation tables, Evidence Console, seeds and fingerprints, "Round 1 MVP"). Their backend endpoints and scripts are kept as developer utilities (docs/DEVELOPMENT.md). New: patient overview (search, risk filter, monitoring status, latest vitals, last reading), patient detail (demographics, discharge, conditions, medications, trusted vitals with personal baselines and trends, risk assessment with reasons, thresholds, source Observations and data reliability, alert history, SpO₂ Scale 2 configuration), header status (backend, FHIR server, monitoring source, last update).

Backend additions: `app/monitoring.py` (server-side assessment after every accepted ingestion and replay batch; alert events stored on level change; no fabricated NORMAL without data), `GET /api/clinical/overview`, `GET /api/alerts`, `GET /api/monitoring/status`, `scripts/dev/simulate.sh`. Scoring thresholds, the safety floor, artifact suppression and baselines are unchanged.

Performance: the live queries now send only subject and date to HAPI and filter code and tag in Python (measured 0.16-0.32 s vs 0.7-2.9 s); overview 39 s → about 2 s; monitor 2.5 s → 0.85 s.

Acceptance (`scripts/acceptance.py`, this Linux workspace, not macOS):

| Check | Status |
|---|---|
| services up | PASS |
| patients 8 | PASS |
| live simulation | PASS |
| levels seen | PASS |
| alert events | PASS |
| overview status | PASS |
| no data not normal | PASS |
| monitoring source status | PASS |
| fhir readback | PASS |
| explanations | PASS |
| news2 scoring | PASS |
| websocket updates | PASS |
| scale2 | PASS |
| personal baselines | PASS |
| artifact suppression | PASS |
| replay lab | PASS |
| bidmc replay | BLOCKED |
| evidence console | PASS |

Tests: `scripts/check.sh`: 121 unit, 28 live HAPI, 28 repo, 5 web, type-check, build: ALL CHECKS PASSED. Browser (desktop 1440 px and mobile 390 px): 8 patient cards, no demo wording, no horizontal overflow, detail page "Live updates" via WebSocket, 0 console errors. The polling fallback is covered by a web test.

Not verified here: macOS startup (this workspace cannot reach the user's Mac; the macOS setup path was verified earlier in a macOS-like simulation only). Limitations unchanged: BIDMC BLOCKED, NEWS2 bands unverified against the RCP PDF, simulated monitoring data, no alert acknowledgement workflow.

---

## Phase 7: end-to-end acceptance (2026-11-12)

Command: `.venv/bin/python scripts/acceptance.py --with-tests` (run 2026-11-12T14:59:28 UTC on this Linux workspace at commit d0b780c; **not run on the macOS machine**, which this workspace cannot reach). Raw report: `docs/acceptance-latest.json`. Result: 14 PASS, 0 FAIL, 1 BLOCKED.

| Check | Status | Evidence |
|---|---|---|
| services up | PASS | HAPI 200 FHIR 4.0.1; API 200; web proxy 200 |
| patients 8 | PASS | 8 patients via API, 8 via web proxy; 8/8 profiles complete with conditions and medications |
| live simulation | PASS | 80 readings accepted, 0 rejected; latest {'heart_rate': 134.0, 'spo2': 88.0, 'respiratory_rate': 31.0, 'body_temperature': 39.3} |
| levels seen | PASS | NORMAL@3.0s → WATCH@8.9s → REVIEW@15.0s → URGENT@18.5s |
| fhir readback | PASS | Observation/52936: HAPI 200, API 200, identical=True, 8310-5 = 39.3 Cel, profile bodytemp, ingest read-back match True, $validate errors 0 |
| explanations | PASS | 5 alerts at URGENT; all have rule/value/unit/reason: True; 8/8 triggering Observations resolve in HAPI; e.g. "NEWS2-style partial aggregate 11 (from 4 of 7 parameters; a single parameter scores 3)." |
| news2 scoring | PASS | NEWS2-style total 11 = sum of {heart_rate: 134.0→3, spo2: 88.0→3, respiratory_rate: 31.0→3, body_temperature: 39.3→2}; partial 4/7; band source not verified against the RCP PDF |
| websocket updates | PASS | direct pushes [(1, 'URGENT', '2026-11-12T15:00:22.626080+00:00'), (2, 'URGENT', '2026-11-12T15:00:25.322663+00:00')]; via Vite proxy [(1, 'URGENT'), (2, 'URGENT')] |
| scale2 | PASS | SpO2 87.0%: Scale 1 score 3 → after FHIR Flag/53181 Scale 2 score 1 (total 10→8) → flag cleared, Scale 1 |
| personal baselines | PASS | baselines from 484 stored readings: heart_rate median 74.0 MAD 1.0 (n=100), spo2 median 97.0 MAD 1.0 (n=100), respiratory_rate median 15.0 MAD 0.0 (n=100), body_temperature median 36.8 MAD 0.1 (n=100); level NORMAL. Rule-level behaviour (deviation, chronic tol |
| artifact suppression | PASS | 11 readings suppressed in the latest window (isolated spike of 15 that reverted; isolated spike of 21 that reverted; isolated spike of 57 that reverted; isolated spike of 60 that reverted; physiologically implausible; probe-off); personalized level NORMAL |
| replay lab | PASS | 2 independent runs, identical metrics: True. Lead before critical (deterioration): fixed 43.0 / personalized 43.0 min; artifact alerts/patient-day fixed 36.0 vs personalized 0.0; false episodes artifact 6→0, deterioration+artifact 2→0 |
| bidmc replay | BLOCKED | no genuine PhysioNet BIDMC files in services/bidmc/data; no substitute data used |
| unit integration frontend | PASS | 116 passed, 28 deselected in 7.09s; 28 passed, 116 deselected in 99.06s (0:01:39); 28 passed in 0.05s; Test Files  1 passed (1); Tests  4 passed (4); ALL CHECKS PASSED |
| evidence console | PASS | /api/evidence 200: R1 PASS, R2 PARTIAL, R3 PASS, R4 PARTIAL, R5 PASS, R6 PASS, R7 PASS; shows this run: True |

Added to pass Phase 7 (minimal changes):
- WebSocket live updates: `/ws/monitor/{id}` pushes the monitor payload; the dashboard uses it, falls back to polling, and shows which is active.
- Judge Evidence Console: `GET /api/evidence` computes each requirement's status now (HAPI, SQLite, saved evaluation and acceptance reports, BIDMC folder) and the dashboard displays it.
- `scripts/acceptance.py`: reproducible end-to-end test writing the report the console shows.

Defects found and fixed:
- Acceptance report written to a different folder from the one the API reads.
- First WebSocket push arrived after the 4 s polling fallback; the patient list took 7.8 s (24 HAPI queries). Patient list now cached 60 s (0.001 s), Scale 2 status cached 15 s, watchdog 10 s.

Limitations: the monitor takes about 2.5 s per refresh because HAPI holds about 50k test Observations (H2); BIDMC BLOCKED; NEWS2 bands not verified against the RCP chart; all evaluation data simulated.

---

## macOS localhost fix (2026-11-12)

Reported on macOS (Apple Silicon): setup and all three services failed. Root causes, verified against package metadata:
- `fastapi==0.162.5` is a real release but needs Python ≥ 3.10 (so do uvicorn 0.54 and pytest 9.2). Under macOS Python 3.9, pip reports "No matching distribution", and the code's `int | None` annotations fail too. Pins kept; setup now finds Python ≥ 3.10 (3.13/3.12/3.11/3.10, Homebrew paths, or uv), moves an incompatible `.venv` aside and recreates it.
- No Java 11 runtime exists for Apple Silicon on PyPI (`jdk4py` 11.x has no macOS arm64 wheel). The original HAPI crash was the class scanner, not the Java version: the patched jar runs on **Java 11, 17 and 21** (verified). Setup uses an installed 11/17/21 or installs `jdk4py==17.0.9.2` (wheels for macOS arm64/x86_64 and Linux x86_64).
- Patching no longer needs `javac`: a pure-Python class-file tool strips the type-use annotations (Jandex re-scan: 0 failures of 92,335 classes).
- Web `ERR_MODULE_NOT_FOUND`: `npm ci` never ran because setup aborted at the pip step. Setup now runs every step and reports PASS/FAIL; it checks Node (Vite 8 needs ^20.19 or ≥ 22.12, Vitest ≥ 22.12). `up.sh` checks prerequisites first and prints the fix.
- `run.sh` uses `shasum -a 256` where `sha256sum` is missing (macOS).

Verification in a fresh clone with a macOS-like PATH (`python3` = 3.9, existing 3.9 `.venv`, no `java`, alternate ports):
- `setup.sh`: 3.9 venv moved aside, Python 3.13 venv (fastapi 0.162.5, pydantic 2.14.3), web packages (vite 8.3.8), private Java 17: SETUP OK.
- `up.sh` → `seed.sh` (80 s) → `health.sh`: 8 PASS, 0 blocked.
- `check.sh`: 114 unit, 28 live HAPI, 28 repo, 4 web, type-check, build: ALL CHECKS PASSED.

Not exercised: the "no Python ≥ 3.10 anywhere" message (this machine has 3.13 under `/usr/local/bin`), and a real Mac. Finding: Synthea output depends on the Java major version (same seed: Java 21 → 18 patients, Java 17 → 17 patients, a different 8 selected). The manifest now records the Java version; reproducibility holds for a fixed Java version only.

---

## P0 features: NEWS2-style scoring, Scale 2, Sensor Trust Engine, baselines, evaluation (2026-11-12)

| Feature | Status | Evidence |
|---|---|---|
| NEWS2-style scoring (RR, SpO2, pulse, temperature) | PASS (partial and labelled) | `detector.py`; boundary tests for every band. 4 of 7 parameters; BP, air/oxygen and consciousness not measured. Bands transcribed from RCP 2017; **verification against the chart PDF is BLOCKED** (PDF not in repo) |
| SpO2 Scale 2 eligibility | PASS | Only with an active, attributed FHIR `Flag` in HAPI (live: set → Flag/25424, scale 2; cleared → scale 1). A diagnosis alone never switches the scale (test) |
| Sensor Trust Engine | PASS | Probe-off zeros, implausible values, isolated spikes, unconfirmed jumps held for one reading; suppressed readings stay in HAPI and are listed with reasons (tests) |
| Personalized rolling baselines (2 rules) | PASS | Rule 1 deviation ≥ max(4·MAD, minimum Δ) from own median → WATCH; rule 2 chronic-baseline tolerance for single score-1 parameters; safety floor: a score of 3 or aggregate ≥5 is never tolerated (tests). The cohort's Synthea history is too sparse, so baselines come from monitoring data with a 20-reading warm-up |
| Explainable live alerts | PASS | Each alert has level, rule (bands), value, unit, Observation id(s), reason; baseline alerts include median, MAD and window. Dashboard shows the NEWS2 breakdown, Scale badge, suppressed artifacts and a fixed vs personalized toggle |
| Scenario comparison and 5 metrics | PASS (simulated data) | `POST /api/evaluation/run`; results in EVALUATION.md, computed from HAPI read-back. Incomplete data is refused (guard) |
| Real BIDMC replay | **BLOCKED** | No BIDMC files in `services/bidmc/`; PhysioNet unreachable from this workspace |
| Mobile overflow | PASS | Browser at 390 px: scroll width 390 (was 663), 0 console errors |
| Regression | PASS | `scripts/check.sh`: 114 unit, 28 live HAPI, 28 repo, 4 web, build: ALL CHECKS PASSED (174 tests) |

Defects found and fixed during this work:
- HAPI 5.7 stops following search pages at 500 results and caps page size at 50. The first evaluation silently used 500 of 964 Observations; those results were discarded. Fixed with a date-cursor fetch and a guard that refuses incomplete data.
- HAPI rejects two upper date bounds; the cursor now replaces the existing bound.
- The monitor took 29 s on long sessions; it now reads the newest 480 readings (about 4 s).
- Evaluation sessions now sit 3 days in the past so they never mix into live views.

Known limitations: monitor about 4 s for long sessions; monitoring window and replay sessions are in memory (lost on API restart); one detector process; Synthea history vs simulated counts not split in the profile.

---

## PHASE 1: deterministic replay engine (2026-11-12)

| # | Checkpoint | Status | Evidence |
|---|---|---|---|
| C1 | Existing MVP still works | PASS | Browser: stable NORMAL throughout; deterioration WATCH 15 s → REVIEW 21 s → URGENT 27 s; HAPI read-back Observation/23860 |
| C2 | Replay controls | PASS | Unit lifecycle test; browser 10×: 8/124 → paused (held at 8 for 5 s) → resumed 12/124 → stopped 16/124 → reset CREATED 0/124 |
| C3 | Same seed → same observations | PASS | Unit fingerprint tests; live: reset session re-read from HAPI identical to original (values, LOINC, UCUM, times, subject) |
| C4 | Accelerated replay | PASS | Unit 1×/5×/10× clock tests; live 10× run of 4 simulated min completed in the expected wall time with pause held |
| C5 | Batch without real-time wait | PASS | 24 simulated h (5,764 Observations) in 55 s, HAPI tag count 5,764, 15/15 batches confirmed; 2 h batch completed in 3.0 s |
| C6 | Persisted resources read back | PASS | Live: 244 Observations read from HAPI match generated events; `/persistence` consistent and complete |
| C7 | No ground-truth leakage | PASS | Ground truth only in SQLite `replay_ground_truth`; tests: event fields, FHIR payload scan, `risk.py` import check, API never calls `ground_truth()` |
| C8 | Tests and build | PASS | `scripts/check.sh`: 95 unit, 28 live HAPI, 28 repo, 4 web, build: ALL CHECKS PASSED (155 tests) |

Also: idempotent retries via conditional create (lost-response test: 0 duplicates); HAPI-down recovery (error state, cursor kept, resume completes).

Incident fixed: about 600 benchmark Observations written straight to HAPI (bypassing validation; future-dated values of 70) polluted the live demo view. They were deleted by their `bench-` identifier, and the monitor now ignores future-dated readings (regression test added).

Design: docs/REPLAY_SCHEMA.md. Not done: Synthea-history vs simulated count split in profile; BIDMC source (blocked, B4).

---

## ROUND 1 MVP: end-to-end demo prototype (2026-11-12)

**Scope: a working demonstration for the Round 1 evaluation. This is NOT completion of Phases 2–6.** It adds a minimal simulator, a prototype risk engine and a dashboard on top of the verified Phase 1 FHIR work. Not built: BIDMC replay, NEWS2 baseline, personalization rules, the Sensor Trust Engine / artifact suppression, Watch/Review/Urgent alert lifecycle beyond the live view, Replay Lab, comparative report, and the Judge Evidence Console.

Pipeline: Synthea patient (HAPI) → virtual wearable → `POST /api/fhir/Observation` (strict validation + HAPI `$validate`) → HAPI FHIR R4 → prototype risk rules over stored observations → React dashboard (polls every 1.5 s).

### What was added

| Item | Where |
|---|---|
| Deterministic wearable simulator: 2 scenarios (Stable Recovery, Gradual Deterioration), 20 steps × 4 vitals, 2 s apart (about 40 s). Posts every reading over HTTP to the existing ingestion endpoint; CLI `python -m app.simulator` | `apps/api/app/simulator.py` |
| Prototype risk rules engine: per-vital threshold bands (WATCH/REVIEW/URGENT), trend rules over the last 6 readings, multi-parameter rule (≥3 abnormal vitals → REVIEW). Labelled "not NEWS2, not clinically validated". Input is only stored values, times and Observation ids; no scenario label | `apps/api/app/risk.py` |
| Endpoints `POST /api/demo/simulator/start`, `POST /api/demo/simulator/stop`, `GET /api/demo/simulator`, `POST /api/demo/reset`, `GET /api/demo/monitor/{patientId}` (vitals series, risk and FHIR proof, all read from HAPI) | `apps/api/app/main.py` |
| `age` on patient list and profile | `apps/api/app/patients.py` |
| Dashboard: patient list, profile (conditions, medications, discharge), judge controls (Stable, Deterioration, Stop, Reset), risk banner with explanation table, 4 live vital cards with trend charts and WATCH lines, FHIR proof panel with live HAPI read-back, FHIR connection pill | `apps/web/src/App.tsx`, `api.ts` |
| 60-second judge script | `docs/DEMO_SCRIPT.md` |

### Verification (all on localhost, no Docker)

| # | Check | Status | Evidence |
|---|---|---|---|
| 1 | Backend health | **PASS** | `scripts/dev/health.sh`: 8 PASS, `HEALTH: no failures, 0 blocked` (HAPI 5.7.0 / FHIR 4.0.1, 8 Synthea patients, API, SQLite, web, proxy, WebSocket) |
| 2 | Frontend loads | **PASS** | Headless Chrome (Playwright) on http://localhost:5173: 8 patients listed, pill "HAPI FHIR R4 connected · 4.0.1", 0 console errors |
| 3 | Patient API | **PASS** | Live tests (≥5 complete profiles); dashboard shows name, age, conditions and medications from `/api/patients` and `/api/patients/{id}/profile` |
| 4 | Simulated readings reach the backend | **PASS** | Each UI run: 80 observations stored in HAPI, 0 rejected. Unit test: 3 steps → 12 observations through the ingestion endpoint, all accepted |
| 5 | HAPI read-back | **PASS** | UI "Read back from HAPI now": deterioration run Observation/11761 (bodytemp 39.3 Cel, versionId 1, profile `bodytemp`), stable run Observation/11841 (36.8 Cel); HAPI `$validate` 0 errors; ingest read-back matched |
| 6 | Risk changes during deterioration | **PASS** | Browser run (patient Ariane Kirlin), risk read from the page every 3 s: NORMAL until about 12 s, **WATCH at 15 s, REVIEW at 21 s, URGENT at 27 s**, scenario done at 39 s. Final alerts: HR 134 /min, RR 31 /min, SpO2 88 % URGENT; temperature 39.3 °C REVIEW; multi-parameter REVIEW; 3 trend WATCH alerts, each with Observation ids |
| 6b | Repeat after polish fixes and restart | **PASS** | Second browser run: WATCH at 15 s, REVIEW at 24 s, URGENT at 30 s (sampled every 3 s), done at 42 s; read-back Observation/11937. Stable run NORMAL throughout; read-back Observation/12017. 0 console errors. Screenshots: `docs/screenshots/r1-*.png` |
| 7 | Stable scenario stays normal | **PASS** | Browser run (patient Mark Lueilwitz): NORMAL at every sample for 43 s. Unit test: NORMAL at every step |
| 8 | Tests and build | **PASS** | `scripts/check.sh`: API unit/flow 75 passed, live HAPI 21 passed, scaffold 28 passed, web type-check, 3 tests and build passed, Compose config valid: `ALL CHECKS PASSED` |

Unit tests added: scenarios deterministic and every generated reading valid FHIR; stable never leaves NORMAL; deterioration escalates monotonically NORMAL→…→URGENT and passes through WATCH and REVIEW; every alert has rule, reason and observation; risk depends on values only; simulator posts through the ingestion endpoint; unknown patient or scenario rejected.

### Final pre-demo verification (2026-11-12, 14:45)

| Step | Status | Evidence |
|---|---|---|
| Start HAPI, API, web with `scripts/dev/up.sh` | PASS | health 8 PASS, 0 blocked |
| 8 Synthea profiles through the API | PASS | `/api/patients` count 8; all 8 profiles `complete` |
| Simulator produces HR, SpO2, RR, temperature | PASS | 4 cards populated, each with a chart line |
| Stable Recovery → NORMAL | PASS | NORMAL at every 3 s sample, 46 s |
| Gradual Deterioration → escalation with explanations | PASS | WATCH 15 s, REVIEW 21 s, URGENT 27 s; 8 alert rows; final HR 134, SpO2 88, RR 31, temperature 39.3 |
| New Observation persisted and read back | PASS | Observation/13531 (stable) and 13611 (deterioration), live HAPI read-back, 0 validation errors |
| Dashboard selector, controls, charts, alerts | PASS | 8 patients selectable; Stop disabled when idle; 0 console errors |
| Health checks and tests | PASS | `scripts/check.sh` `ALL CHECKS PASSED` (75 + 21 + 28 + 3 web, build) |

### Known limitations (honest)

- Risk thresholds are simplified demonstration bands, not NEWS2, not personalised, not clinically validated.
- No artifact detection: a probe-off reading would raise an alert.
- Simulated readings use real current timestamps; the scenario represents a compressed deterioration, not real elapsed physiology.
- One simulator run at a time (single API process, in memory). The monitoring window (`Reset demo`) is in memory and resets when the API restarts (defaults to the last 30 minutes).
- Every demo run adds 80 real Observations to HAPI; they are tagged with the simulator run id.

---

## Phase 1 verification: FHIR and patient profiles, localhost (2026-11-12)

Re-verification of the C1 work under the Phase 1 brief, on localhost with no Docker. Existing code was inspected, not rebuilt. One gap was closed: there was no plain endpoint to retrieve a single stored Observation, so `GET /api/fhir/Observation/{id}` was added. It reads from HAPI and returns the resource as HAPI stores it, with 404/400 as `OperationOutcome`. `scripts/dev/health.sh` now also counts BLOCKED checks in its summary.

| # | Phase 1 item | Status | Evidence (all from this run) |
|---|---|---|---|
| 1 | HAPI FHIR R4 as a local Java service with persistent storage | **PASS** | `scripts/dev/up.sh`: HAPI FHIR Server 5.7.0, FHIR 4.0.1 at `http://localhost:8090/baseR4` (Java 11). Data is the H2 file `.local/hapi/data/target/jpaserver_h2_files.mv.db` (53.8 MB). Its mtime changed when an Observation was ingested. Restart test below |
| 2 | FastAPI ingestion for HR 8867-4, SpO2 2708-6, RR 9279-1, temperature 8310-5, tested | **PASS** | Live: each vital (temperature in °C and °F) returns 201 with HAPI `$validate` 0 errors. Unit: 36 invalid payloads rejected at the expected FHIR path |
| 3 | Each valid Observation stored in HAPI and retrievable | **PASS** | Live tests read every ingested Observation **directly from HAPI**, again via `GET /api/fhir/Observation/{id}` (identical to HAPI's copy), and via patient+code search. Spot check: Observation 11580 (RR 19 /min) → API 201, HAPI GET 200 versionId 1, API GET identical |
| 4 | ≥5 real Synthea profiles with Conditions and medications, imported | **PASS** | `scripts/dev/seed.sh all` regenerated from scratch with Synthea v3.4.0 (18 patients, 29.2 s) and selected the same 8 patients. Cohort ids, source-bundle and import-bundle SHA-256 are identical to the earlier run. Re-import: 8 transactions, 0 errors (4 m 29 s total, slower because every resource was re-versioned). `verify`: 8/8 OK |
| 5 | `GET /api/patients`, `GET /api/patients/{id}/profile`, ingestion and retrieval endpoints | **PASS** | `POST /api/fhir/Observation`, `GET /api/fhir/Observation/{id}`, `GET /api/fhir/Observation?patient=&code=`; patient endpoints covered by live tests (≥5 patients, every profile complete, unknown patient 404) |
| 6 | Environment variables for local service URLs | **PASS** | `.env.local.example` / `.env.local`; scaffold tests assert localhost defaults and no container hostnames in local code |
| 7 | Integration tests with evidence | **PASS** | `scripts/check.sh` (no URL overrides): API unit/flow **67 passed**, live HAPI **21 passed**, scaffold/contract **28 passed**, web type-check, 3 tests and build passed, Compose config valid: `ALL CHECKS PASSED` |
| — | No JSON files or in-memory store standing in for HAPI | **PASS** | The API's SQLite has only `app_meta` and `ingestion_events` (ids, hashes, outcomes, validation summaries); no Observation content. Every read path goes to HAPI. Unit tests use an in-memory stand-in only for API control flow; they make no persistence claim and are counted separately from the live tests |
| — | No Docker | **PASS** | All processes native: Java (HAPI, Synthea), Python (API, pipeline), Node (Vite) |

Restart test: `c1_persistence_check.py record` ingested Observations 11581–11584 (one per vital). `scripts/dev/down.sh` stopped web, API and HAPI (no HAPI process left). `scripts/dev/up.sh hapi api` restarted them. `check` → all 4 Observations unchanged and all 8 patients present: `PERSISTENCE CHECK PASSED`.

Health after the run: 8 PASS, `HEALTH: no failures, 0 blocked`.

Not covered by Phase 1 and unchanged: the Docker/PostgreSQL path (B2, deferred) and the PS-03 PDF (B1).

---

## Localhost-first adaptation (2026-11-12)

Strategy change from the project owner: develop without Docker. Nothing completed was rebuilt; all existing code, APIs, the SQLite schema, the FHIR integration and the web app are unchanged in behaviour.

### What changed

| Change | Files |
|---|---|
| One env file of localhost URLs and ports, overridable by `.env.local` or the shell | `.env.local.example`, `scripts/dev/env.sh` |
| Native start scripts: HAPI (Java 11), API (uvicorn), web (Vite) | `scripts/dev/start-{hapi,api,web}.sh` |
| Background start with readiness waits, stop, health check, Synthea seeding, one-time setup | `scripts/dev/{up,down,health,seed,setup}.sh` |
| Repo-local persistent storage, git-ignored: HAPI H2 database `.local/hapi/data`, HAPI jars `.local/hapi/work`, API SQLite `.local/api/app.db`, logs, pids, Java 11 runtime | `.local/` |
| Defaults now point at localhost (`FHIR_BASE_URL=http://localhost:8090/baseR4`): API config, Synthea pipeline, persistence script, live tests, `check.sh` | as listed |
| Container compatibility kept: Compose still sets `FHIR_BASE_URL=http://hapi-fhir:8080/fhir`; nginx still proxies to `api:8000`; `smoke.sh` remains the container smoke test, with a configurable `FHIR_URL` | `docker-compose.yml`, `infra/nginx`, `scripts/smoke.sh` |
| Guard tests: no container hostnames in code that runs on localhost; env example covers every URL and port; API defaults are localhost; `.local/` and `.env.local` are ignored | `tests/test_scaffold.py` |
| `check.sh` resolves the Python path itself (a relative `PYTHON=` path had broken the API steps, see FAIL below) | `scripts/check.sh` |
| Correction: the HAPI 5.7 CLI server stores data in **H2**, not Derby as the C1 notes said | docs |

The C1 HAPI database (8 Synthea patients plus ingested observations) was moved into `.local/hapi/data`, not regenerated.

### Status by item

| Item | Status | Evidence |
|---|---|---|
| React/Vite on http://localhost:5173 | PASS | health: page served, `/api` proxied, WebSocket heartbeat via proxy |
| FastAPI on http://localhost:8000 | PASS | health: `/health`, SQLite event store, sees HAPI as R4 |
| HAPI FHIR, native Java, persistent local storage | PASS | FHIR 4.0.1, HAPI 5.7.0 on `:8090/baseR4`; data survived a `down.sh`/`up.sh` restart (persistence check below) |
| Synthea, native Java | PASS | `scripts/dev/seed.sh verify`: 8/8 profiles verified (generation itself ran natively in C1, byte-identical across two runs) |
| Simulator as a local Python process | Not built yet (C2) | — |
| Monitoring engine as a local Python process | Not built yet (C4/C5) | — |
| BIDMC replay as a local Python process | Not built yet (C2); **real data BLOCKED here (B4)** | `physionet.org` connect rejected; S3 mirror "no rule allows host" |
| Docker hostnames replaced by configurable localhost URLs | PASS | guard test passes; Compose/nginx keep container names as explicit overrides |
| Full check suite on localhost defaults | PASS | see below |
| Container stack | BLOCKED (B2), deferred | — |

### Commands and actual results

`scripts/dev/setup.sh`: venv and API requirements, `npm ci` (151 packages), Java 11.0.13 runtime into `.local/tools/jdk11`; 16 s. Java 21 found on PATH for Synthea.

`scripts/dev/up.sh` (HAPI, API, web), 32 s, then health:
```
PASS     hapi   http://localhost:8090/baseR4/metadata -> FHIR 4.0.1 HAPI FHIR Server 5.7.0
PASS     hapi   8 Synthea patients stored
PASS     api    http://localhost:8000/health
PASS     api    event store (SQLite /home/claude/arogyadrishti/.local/api/app.db)
PASS     api    sees HAPI as R4
PASS     web    http://localhost:5173/ serves the app
PASS     web    proxies /api to http://localhost:8000
PASS     web    WebSocket /ws/heartbeat via proxy
HEALTH: no failures
```

`scripts/check.sh` with no URL overrides (`FHIR_BASE_URL` and `HAPI_TEST_FHIR_BASE` unset):

| Run | Result |
|---|---|
| First run, invoked with relative `PYTHON=.venv/bin/python` | **FAIL** on both API steps: the interpreter path broke after `check.sh` changed into `apps/api`; other steps passed. Invocation error, not a code failure; `check.sh` now resolves the path |
| Re-run | **PASS**: API unit/flow 66 passed; live HAPI 21 passed; scaffold/contract 28 passed; web type-check, 3 tests, build passed; Compose config valid. `ALL CHECKS PASSED` |

Persistence through the dev scripts: `c1_persistence_check.py record` ingested 4 observations (one per vital), `scripts/dev/down.sh` stopped everything (health then reported `BLOCKED hapi not reachable`), `scripts/dev/up.sh hapi api` restarted, `check` → all 4 observations and 8 patients PASS, `PERSISTENCE CHECK PASSED`.

Known log noise: on every restart against an existing H2 database, HAPI 5.7 logs Hibernate `WARN … Error executing DDL "create index …"` (index already exists). Startup completes and data is intact.

---

## C1: FHIR R4 ingestion, HAPI storage, Synthea discharge profiles

Run on 2026-11-12 in the same Linux cloud workspace as C0.

### How HAPI was run (read this first)

Docker images still cannot be pulled here (B2), so the official `hapiproject/hapi` image on PostgreSQL defined in `docker-compose.yml` was **not** used. The C1 evidence comes from a real HAPI JPA server started from the **official HAPI FHIR 5.7.0 CLI release** (`run-server -v r4`, on-disk H2 database), downloaded from GitHub releases and checked by SHA-256.

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
