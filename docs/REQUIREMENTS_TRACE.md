# Requirement traceability

Source: the project brief. To be re-verified against the PS-03 PDF once it is in the repository (blocker B1).

## Mandatory requirements

| # | Requirement | Checkpoint | Status | Evidence |
|---|---|---|---|---|
| 1 | FHIR R4 Vital Signs ingestion and HAPI storage | C1 | **Met on a local HAPI 5.7.0 server.** Not yet run on the Docker HAPI/PostgreSQL stack (B2) | `apps/api/app/ingest.py`, `vitals.py`; `tests/integration/test_live_hapi.py`; `scripts/c1_persistence_check.py`; CHECKPOINTS.md C1 |
| 2 | Virtual wearable simulator and actual BIDMC replay | C2 | Not implemented. Real BIDMC download BLOCKED in the build workspace (CHECKPOINTS.md B4) | none |
| 3 | At least 5 Synthea-generated patient profiles with conditions and medications | C1 | **Met:** 8 real Synthea v3.4.0 discharge profiles imported into HAPI and verified | `services/synthea/`; `test_every_profile_is_complete_and_references_its_patient`; CHECKPOINTS.md C1 |
| 4 | NEWS2-style baseline and at least 2 personalization rules | C4 | Not implemented | none |
| 5 | Sensor artifact detection and false clinical alert suppression | C5 | Not implemented. Ingestion deliberately keeps possible-but-implausible readings for it | `test_possible_but_implausible_readings_are_accepted_for_artifact_detection` |
| 6 | Clinician dashboard, Watch/Review/Urgent alerts and explanations | C6 | Dashboard shell only; no alerts | `apps/web/src/App.test.tsx` |
| 7 | Scenario replay and comparative performance report | C7 | Not implemented | none |

## Evaluation criteria

See [EVALUATION.md](../EVALUATION.md).
