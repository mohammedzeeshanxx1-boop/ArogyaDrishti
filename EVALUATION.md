# Evaluation

## Results (generated 2026-11-12T13:23:14 UTC, simulated data)

Produced by `POST /api/evaluation/run` with `{"patientId": "88967114-c92a-2b59-06ff-a60a2c76e10a", "durationMinutes": 240}`; raw report: `docs/evaluation-latest.json`. Each scenario was replayed in batch mode into HAPI (964 Observations each), read back from HAPI, evaluated causally at every measurement time in both modes, and only then joined with ground truth. Seeds: stable 1001, deterioration 2002, artifact 3003, deterioration_artifact 4004. SpO2 Scale 1.

| Scenario | Mode | Alert episodes | Alerts / patient-day | False alert episodes (from artifacts) | Onset → first WATCH | Lead before scripted critical | Explained alerts | Peak | FHIR confirmed / sample $validate errors |
|---|---|---|---|---|---|---|---|---|---|
| Stable Recovery | fixed | 0 | 0.0 | 0 (0) | — | — | — | NORMAL | 100.0% / 0 |
|  | personalized | 0 | 0.0 | 0 (0) | — | — | — | NORMAL | 100.0% / 0 |
| Gradual Deterioration | fixed | 2 | 12.0 | 0 (0) | 32.0 min | 43.0 min | 100.0% | URGENT | 100.0% / 0 |
|  | personalized | 2 | 12.0 | 0 (0) | 32.0 min | 43.0 min | 100.0% | URGENT | 100.0% / 0 |
| Stable with Sensor Artifacts | fixed | 6 | 36.0 | 6 (6) | — | — | 100.0% | REVIEW | 100.0% / 0 |
|  | personalized | 0 | 0.0 | 0 (0) | — | — | — | NORMAL | 100.0% / 0 |
| Deterioration with Sensor Artifacts | fixed | 8 | 48.0 | 2 (2) | 24.0 min | 93.0 min | 100.0% | URGENT | 100.0% / 0 |
|  | personalized | 5 | 30.0 | 0 (0) | 31.0 min | 46.0 min | 100.0% | URGENT | 100.0% / 0 |

How to read it:
- Artifacts: the Sensor Trust Engine removed every artifact-driven false alert episode in both artifact scenarios (6 → 0, and 2 → 0).
- On clean deterioration, personalized and fixed perform the same (43 min before the scripted critical point); the baseline rule gave no earlier warning in this scenario.
- In "deterioration with artifacts", fixed mode's 93 min "lead" and earlier first WATCH are caused by artifact spikes after onset, not by true detection; personalized gives 46 min with 0 false episodes.
- These are simulated, seeded scenarios with scripted ground truth. They are engineering measurements, not clinical evidence. Only 4 of 7 NEWS2 parameters are measured; the NEWS2 bands are transcribed from the RCP 2017 chart and still need verification against the PDF.

## Metric definitions

This file's earlier section below gave the planned definitions; the implemented ones are in `apps/api/app/evaluation.py` (module docstring).

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
