# Final product plan

Builds on the verified MVP without replacing it. Each phase must keep `scripts/check.sh` green and record PASS / FAIL / BLOCKED evidence in CHECKPOINTS.md. Order is chosen so that every later phase has the inputs it needs.

## Prerequisites (owner actions, do first)

| ID | Action | Unblocks |
|---|---|---|
| P1 | Merge `localhost-dev` → `main` (2 commits behind) | clean base |
| P2 | Add the PS-03 PDF to the repo | final requirement wording (B1) |
| P3 | Add the RCP NEWS2 chart PDF to `docs/references/` (the site blocks automated download) | Phase 2 |
| P4 | Get BIDMC files: download `bidmc_csv` (numerics CSVs, small) on a machine with PhysioNet access into `services/bidmc/data/`, **or** allow `physionet.org` for this workspace | Phase 4 |

## Phases

### Phase 1: Replay engine and simulated time (foundation)
**Why first:** every metric needs replay at scale on a simulated clock; the live simulator is real-time only.
- Scenario definition format (YAML/JSON): vitals curves, **labelled deterioration onset**, artifact windows, duration in simulated hours, seed.
- Batch ingestion: FHIR transaction Bundle of Observations (one HAPI round-trip per batch) with the same validation gate. Per-Observation `$validate` stays on the live path; batch mode validates a deterministic sample plus all distinct shapes (documented).
- Replay runner writes historical `effectiveDateTime` values (backfill) and a run id tag; cleanup by tag.
- Split Synthea-history vs simulated counts in the profile.

**Accept:** 24 simulated hours × 4 vitals at 1/min for one patient replays in under 5 min; all stored; deterministic (same seed → same values); the existing live demo is unchanged.
**Risk:** HAPI 5.7/H2 write throughput. Mitigation: 1-minute aggregates; measure before scaling.

### Phase 2: NEWS2-style scoring and Scale 2 (depends on P3, Phase 1)
- `news2.py`: per-parameter scores for RR, SpO2 Scale 1 / Scale 2, HR, temperature, implemented **only from the chart in `docs/references/`**, with a unit test per band boundary. Blood pressure, air/oxygen and consciousness are not measured by the wearable: report them as "not available" and **label the score partial**, never imputed.
- Scale 2 eligibility: only when an explicit flag is present (a documented clinician decision, recorded as FHIR, e.g. a Flag or Observation with a target SpO2 range). A COPD diagnosis alone does not enable it. Add one Synthea patient with a chronic respiratory condition (new seed, same pipeline) to demonstrate eligibility; keep the 8 existing patients.
- Mapping to WATCH / REVIEW / URGENT documented (e.g. aggregate bands plus single-parameter 3).

**Accept:** boundary tests for every band; Scale 2 never applied without the flag (test); the UI shows "NEWS2-style (partial: 4 of 7 parameters)".
**Risk:** over-claiming. Mitigation: label "NEWS2-style, partial parameters, not clinically validated".

### Phase 3: Sensor Trust Engine (artifact suppression) (depends on Phase 1)
- Per-reading trust checks: physiological plausibility, rate of change, flatline, dropout and gaps, SpO2 / HR consistency; each check has an id, threshold and reason.
- Suppressed readings stay stored in HAPI (never deleted) and are excluded from scoring, with the reason recorded; the dashboard shows "suppressed: probe-off suspected".
- Artifact-injection scenarios (probe off → SpO2 0 / HR 0, motion spikes).

**Accept:** each check has positive and negative tests; artifact scenarios produce 0 escalations without suppressing true deteriorations in the labelled scenarios.

### Phase 4: BIDMC replay (depends on P4, Phase 1, Phase 3)
- Parse the numerics CSV (HR, RR, SpO2, 1 Hz; **no temperature**) and verify column names and units against the dataset page before use.
- Replay through the batch path, downsampled (documented, e.g. 15 s median), linked to a dedicated Patient (BIDMC age and gender only; record id as identifier; labelled "real de-identified recording").
- Record dataset version, licence (ODC-By) and citation in DATA_SOURCES.md.

**Accept:** at least one authentic record parsed, replayed and read back from HAPI, with file SHA-256 logged; then all 53 if throughput allows.
**Honesty:** BIDMC has no deterioration labels, so it supports alert burden and artifact behaviour, **not** lead time.

### Phase 5: Personalized rolling baselines (depends on Phases 1–3)
- Rolling per-patient median and MAD per vital over a configurable window (e.g. 6 h) from the patient's own trusted readings, with a warm-up period before personalization activates.
- At least 2 documented personalization rules, e.g. (a) deviation from baseline ≥ k·MAD sustained for N minutes raises WATCH even inside fixed bands; (b) a chronically elevated but stable HR (e.g. at discharge) does not repeatedly alert, provided absolute safety thresholds always remain.
- Absolute safety floor: personalization may **add** sensitivity or remove repeat alerts, but never suppress an URGENT single-parameter extreme.

**Accept:** unit tests per rule; a safety-floor test; explanations name the baseline value and window.

### Phase 6: Alerts as events and dashboard upgrade (depends on Phases 2, 3, 5)
- Persist alerts (SQLite metadata plus FHIR `Flag` or `DetectedIssue` references), with id, level, opened/escalated/resolved times, acknowledgement and an explanation snapshot.
- Push updates over the existing WebSocket (polling kept as fallback).
- Ward overview (all patients' levels), alert timeline, artifact markers on charts, baseline band on charts.
- Fix the mobile overflow; collapsible patient list; stacked alert cards under 640 px; contrast check.

**Accept:** Playwright runs at 390, 820 and 1440 px with no horizontal overflow; WebSocket and polling both tested; acknowledgement persists across an API restart.

### Phase 7: Replay Lab and honest evaluation (depends on all above)
- Run a fixed scenario suite (stable, gradual, rapid, artifact-only, artifact + deterioration, Scale 2 patient) plus BIDMC through three modes: **fixed thresholds** (prototype / NEWS2-style), **personalized**, **personalized + artifact suppression**.
- Compute lead time, alerts per patient-day, false alerts in labelled windows, FHIR compliance rate (from logged `$validate` results) and explanation completeness, each from stored data, with the generating command and seed in the report.
- Report: `EVALUATION.md` plus a generated HTML/JSON report; results shown in a Replay Lab page and a Judge Evidence Console mapping each requirement to its test and evidence.

**Accept:** the report regenerates byte-identically from seeds; no metric is hand-entered (test: report values equal recomputed values); simulated and real results are reported separately.

## Recommended order and timeline estimate

P1–P4 → Phase 1 → Phase 2 → Phase 3 → Phase 4 → Phase 5 → Phase 6 → Phase 7.
Phases 2 and 3 can run in parallel after Phase 1. If P4 stays blocked, Phase 4 is recorded as BLOCKED and everything else proceeds.

## Cross-cutting risks

| Risk | Mitigation |
|---|---|
| HAPI 5.7 is an old, patched jar; the Docker image is untested | Keep the API server-agnostic (already true); test on the official image once registries are reachable |
| Simulated results presented as clinical evidence | Every metric labelled with its data source; disclaimer kept everywhere |
| HAPI growth from repeated runs | Run-id tags and a cleanup command; separate evaluation patients |
| Metric gaming (tuning thresholds to scenarios) | Freeze thresholds before running the evaluation suite; record their version in the report |
| Personalization hiding real deterioration | Absolute safety floor and a dedicated test |
