# Final product gap analysis (Phase 0)

Audit date: 2026-11-12, branch `localhost-dev` @ `90ef940`. Status terms: **PASS** = implemented and verified by executable tests; **PARTIAL** = some of it works; **FAIL** = not implemented, or present in a misleading form; **BLOCKED** = cannot be done in the current environment without outside action.

## 1. Repository state

| Item | Finding |
|---|---|
| Branches | `main` @ `01dbeea` (PR #4 merged). `localhost-dev` is **2 commits ahead of main** (`68ac6bd` DATA_SOURCES.md, `90ef940` final demo verification); they need a new PR |
| Stack | FastAPI 0.162.5, uvicorn 0.54, httpx 0.28; React 19.3, Recharts 3.10, Vite, Tailwind 4, Vitest. HAPI FHIR 5.7.0 CLI (patched jar, Java 11, H2); Synthea v3.4.0 |
| Size | About 2,400 lines of app code (API, web, pipeline), 4 API test modules plus 1 live module, 1 web test module |
| Health (this audit) | `scripts/dev/up.sh` → 8 PASS, 0 blocked |
| Tests (this audit) | `scripts/check.sh` → API unit 75 passed, live HAPI 21 passed, repo 28 passed, web 3 passed, type-check and build OK: `ALL CHECKS PASSED` |
| Secrets / PHI | No secrets in tracked files (only the placeholder `POSTGRES_PASSWORD=change-me-local-only` in `.env.example`). `.env`, `.local/`, Synthea output and jars are git-ignored. No real patient data anywhere |
| Open blockers | B1: PS-03 PDF not in repo. B2: container registries unreachable (Docker deferred). B4: PhysioNet unreachable from the build workspace. New: the RCP NEWS2 chart cannot be fetched automatically (robots-disallowed) |

## 2. Mandatory requirements

| # | Requirement | Status | What exists (verified) | Gap |
|---|---|---|---|---|
| 1 | FHIR R4 Observation ingestion and persistence for HR, SpO2, RR, temperature | **PASS** | `vitals.py` strict validator plus HAPI `$validate` against the official R4 profiles; store, read-back, restart persistence; `GET /api/fhir/Observation/{id}`; 36 invalid-payload unit tests; 21 live tests | Only one Observation per request (replay at scale needs batching). The Docker/PostgreSQL path has never been run |
| 2 | Simulator **and** real BIDMC replay | **PARTIAL** (simulator) / **BLOCKED** (BIDMC) | Deterministic simulator, 2 scenarios × 4 vitals, posting through the ingestion endpoint; tested | **No BIDMC code or data.** `services/bidmc/` holds only a README. No artifact injection, only 2 scenarios, real-time timestamps only (no time compression or backfill), one run at a time, in memory |
| 3 | ≥5 Synthea discharge profiles with conditions and medications | **PASS** | 8 profiles, Synthea v3.4.0, seeded and byte-reproducible, imported and verified; `/api/patients`, `/profile`; live completeness tests | No respiratory or hypercapnic patient, so SpO2 Scale 2 cannot be shown with this cohort. Synthea's own vital history is sparse (142 heart-rate observations for the whole cohort; SpO2 and temperature mostly absent), so it cannot seed baselines |
| 4a | Documented NEWS2-style scoring | **FAIL** | None. `risk.py` is a prototype band engine, labelled "Not NEWS2" in code, API and UI | Needs NEWS2 parameter scoring, aggregate and single-parameter-3 triggers, and the chart in the repo as the source |
| 4b | SpO2 Scale 2 eligibility | **FAIL** | None | Needs an explicit, documented eligibility rule and a FHIR-backed flag; a COPD diagnosis alone must not switch scales |
| 4c | Personalized rolling baselines | **FAIL** | None (the "baseline" hits in the code search were a CSS class) | Needs per-patient rolling statistics from the patient's own monitoring data, a warm-up period, and documented personalization rules (≥2) |
| 5 | Artifact suppression | **FAIL** | None. Ingestion deliberately keeps possible-but-implausible readings for this. "probe" hits in the code search refer to the FHIR connectivity probe | Needs a Sensor Trust Engine (plausibility, rate of change, flatline, dropout, cross-signal consistency), suppression with recorded reasons, and artifact-injection scenarios |
| 6 | Live clinician dashboard with explainable Watch/Review/Urgent alerts | **PARTIAL** | Dashboard: patients, profile, 4 live vitals with charts, risk banner, explanation table (rule, value, Observation id, reason), FHIR proof; verified in headless Chrome; 0 console errors | Alerts are recomputed views, not persistent events (no alert ids, lifecycle or acknowledgement). Polls every 1.5 s; the WebSocket only carries a heartbeat. No multi-patient overview. Mobile layout overflows (scroll width 663 px on a 390 px viewport); the patient list pushes the dashboard far down on phones |
| 7 | Scenario replay and honest evaluation against fixed thresholds | **FAIL** | None. No Replay Lab, no comparison, no report. `EVALUATION.md` says "no results exist yet" | Needs a batch replay engine on simulated time, a fixed-threshold comparator, labelled ground truth from scenario scripts, and a report generator |

## 3. Evaluation metrics

No metric is computed anywhere in the code (searches for lead time, patient-day and false alert return nothing). No hard-coded results were found either; `EVALUATION.md` correctly reports none.

| Metric | Status | Requirement for an honest result |
|---|---|---|
| Detection lead time | **FAIL** (not computed) | Onset time from the scenario script (ground truth independent of the detector) minus the first REVIEW/URGENT alert, for fixed-threshold and personalized modes. Only defined for labelled scenarios; BIDMC has no deterioration labels |
| Alerts per patient-day | **FAIL** | Alerts / monitored patient-days per mode, on simulated time (needs replay with time compression or backfill) |
| False alert reduction | **FAIL** | Alerts during labelled no-deterioration and artifact windows, fixed versus personalized + artifact suppression. On BIDMC, report alert burden only (no labels) |
| FHIR compliance | **PARTIAL** | Per-Observation `$validate` already runs and is logged; no aggregate rate is reported |
| Explainability | **PARTIAL** | Every current alert has rule, value, Observation id and reason (unit-tested). No metric (e.g. % of alerts with complete explanation fields) and no persisted alert record |

## 4. Data provenance

| Data | Kind | Where | Labelled in UI and docs? |
|---|---|---|---|
| Patients, conditions, medications, encounters | **Synthetic** (Synthea v3.4.0) | HAPI | Yes ("Synthetic patients (Synthea)") |
| Synthea historical vital-sign Observations | **Synthetic** | HAPI (no ingest tag) | Excluded from the monitor by tag filter; not shown |
| Live vitals | **Simulated** (deterministic simulator) | HAPI, tagged `api-ingest` plus a run id | Yes ("simulated wearable data"); the Observation carries `device.display` "virtual wearable (simulated)" |
| BIDMC recordings | **Real, de-identified** | Not present | Not claimed |
| Risk levels | **Prototype rules** | Computed on read | Yes ("Not NEWS2, not clinically validated") |

Issue: demo runs accumulate in HAPI (80 Observations per run), and the profile's `vitalObservationCounts` mixes Synthea history with simulated readings. It should be split by source before evaluation.

## 5. UI review

Strong: clear brand and disclaimer, consistent navy/teal palette, readable risk banner, explanation table, FHIR proof panel, no console errors.

Issues:
1. **Mobile overflow** (390 px viewport → 663 px scroll width): cards and the alert table clip on the right.
2. On phones the patient list (8 cards) sits above the dashboard; the risk banner is about 2,000 px down.
3. Alert table is wide; on small screens it needs a stacked or card layout.
4. No alert history or timeline; escalation is visible only as it happens.
5. No multi-patient ward view (every patient's current level at a glance).
6. Synthea names include digits (stripped for display); the Patient id is truncated in the header.
7. The accessibility pass so far covers semantic headings, `aria-live` and focus rings only; colour contrast of amber badges has not been measured.

## 6. Working functionality to preserve

Ingestion and validation pipeline; HAPI client; Synthea pipeline and cohort; patient/profile/inspector endpoints; simulator and `/api/demo/*`; dashboard; `scripts/dev/*`; `scripts/check.sh`; all 127 existing tests.
