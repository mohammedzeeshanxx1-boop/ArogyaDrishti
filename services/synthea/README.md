# services/synthea

Reproducible pipeline that generates synthetic post-discharge patients with [Synthea](https://github.com/synthetichealth/synthea) and loads them into HAPI FHIR R4. All data is synthetic.

```bash
python3 services/synthea/pipeline.py all --fhir-base http://localhost:8090/fhir
# or step by step: fetch | generate | select | import | verify
# Docker (untested, see CHECKPOINTS.md B2): docker compose --profile seed run --rm synthea-import
```

Needs Python 3.10+ (stdlib only) and Java 11+ for Synthea.

| Step | What it does |
|---|---|
| fetch | Downloads the Synthea release pinned in `synthea.lock.json` and checks its SHA-256 |
| generate | Runs Synthea with the pinned seed, clinician seed, reference date, population, age range and state into `output/raw/` |
| select | Picks discharge profiles: alive, at least one inpatient (`IMP`) encounter with an end date, at least one active Condition and at least one active MedicationRequest. Ordered by most recent discharge. Fails if fewer than 5 qualify |
| import | Loads the hospital and practitioner bundles, then one transaction per selected patient |
| verify | Reads every patient back from HAPI and checks conditions, medications, inpatient stays and that every subject reference is `Patient/<uuid>` |

## What gets imported

Patient, Encounter, Condition, MedicationRequest, Medication, AllergyIntolerance, CarePlan, CareTeam and vital-sign Observations. The pipeline refuses to import a subset that would leave a dangling reference. Entries are converted from POST to PUT with the Synthea UUID as id, so Patient ids are stable and re-imports are idempotent (HAPI must allow client-assigned alphanumeric ids, which is the Compose setting).

## Outputs (not committed)

`output/` is git-ignored and regenerated from the lock file:
- `manifest.json`: Synthea version and SHA-256, exact arguments, the selected cohort with source-file hashes, and why every other patient was not selected
- `import-report.json`: per-bundle HTTP status, entry errors, timings, and the verify results
- `cohort/<uuid>.json`: the import bundles
- `synthea-run.log`

The C1 run is recorded in [CHECKPOINTS.md](../../CHECKPOINTS.md): 18 generated, 8 selected, byte-identical across two runs, imported and verified in HAPI.
