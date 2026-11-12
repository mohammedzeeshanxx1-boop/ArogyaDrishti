# Evaluation

**No results exist yet.** This file defines how each official PS-03 criterion will be measured. Numbers are added only when produced by a seeded, repeatable run, with the command that produced them.

The working definitions below come from the project brief. They must be checked against the PS-03 PDF, which was not available at C0 (see CHECKPOINTS.md, blocker B1).

| # | Criterion | Working definition | Produced at | Result |
|---|---|---|---|---|
| 1 | Detection lead time | Time between the first Review or Urgent alert and the scripted deterioration onset in a seeded scenario, for naive and personalized monitoring | C7 | none yet |
| 2 | Alerts per patient-day | Clinical alerts raised divided by monitored patient-days, per monitoring mode | C7 | none yet |
| 3 | False artifact alerts | Clinical alerts raised during injected sensor-artifact windows where no deterioration is scripted | C5, C7 | none yet |
| 4 | FHIR compliance | Vital-sign Observations accepted by HAPI FHIR R4 and passing `$validate` against the R4 Vital Signs profile | C1 | Mechanism in place and tested on HAPI 5.7.0 (see below); no aggregate metric yet |
| 5 | Alert explainability | Every alert carries the contributing vitals, thresholds, the personalization rule applied and the sensor-trust verdict | C6 | none yet |

## FHIR compliance at C1

Every Observation stored by the API has passed the local strict validator and HAPI's `$validate` against its R4 vital-sign profile with zero errors. Each ingestion is logged with the HAPI validation summary, and the Inspector re-validates stored resources on demand. Live tests show HAPI's validator accepting valid examples of all four vitals and rejecting a missing category and a wrong UCUM unit.

Caveats: measured on a local HAPI 5.7.0 server, not the Docker image; HAPI reports two advisory warnings per Observation (no narrative, no performer). The C7 report will compute the compliance rate over all replayed observations.

## Ground rules

- Scenarios are deterministic: fixed seeds, recorded in the report.
- Ground truth for lead time and artifact windows comes from the scenario script, not from the detector.
- Simulated results are labelled as simulated. BIDMC replay results are reported separately.
- No external LLM takes part in any clinical decision.
- Results are engineering measurements on synthetic and public research data, not evidence of clinical performance.
