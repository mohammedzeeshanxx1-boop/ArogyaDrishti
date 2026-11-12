# Requirement traceability

Source: the project brief. To be re-verified against the PS-03 PDF once it is in the repository.

## Mandatory requirements

| # | Requirement | Checkpoint | Status at C0 | Evidence |
|---|---|---|---|---|
| 1 | FHIR R4 Vital Signs ingestion and HAPI storage | C1 | Not implemented. HAPI and PostgreSQL are defined in Compose but have never been started | none |
| 2 | Virtual wearable simulator and actual BIDMC replay | C2 | Not implemented | none |
| 3 | At least 5 Synthea-generated patient profiles with conditions and medications | C3 | Not implemented | none |
| 4 | NEWS2-style baseline and at least 2 personalization rules | C4 | Not implemented | none |
| 5 | Sensor artifact detection and false clinical alert suppression | C5 | Not implemented | none |
| 6 | Clinician dashboard, Watch/Review/Urgent alerts and explanations | C6 | Dashboard shell only; no alerts | `apps/web/src/App.test.tsx` |
| 7 | Scenario replay and comparative performance report | C7 | Not implemented | none |

## Evaluation criteria

See [EVALUATION.md](../EVALUATION.md). No criterion has a result yet.
