# Data sources and references

Audit date: 2026-11-12, Round 1 MVP (branch `localhost-dev`). Status terms: **Implemented + tested** = used by code with passing tests; **Referenced** = cited only; **Not integrated** = no code or data yet; **Unverified** = could not be opened during the audit.

| # | Source | Purpose in Arogya Drishti | Downloaded? | Status | Evidence |
|---|---|---|---|---|---|
| 1 | HL7 FHIR R4 Vital Signs profile — https://hl7.org/fhir/R4/observation-vitalsigns.html | Structure of every ingested Observation: status, `vital-signs` category, LOINC code, Patient subject, effective time, UCUM quantity | Not as a file. HAPI FHIR 5.7.0 ships the official R4 StructureDefinitions | **Implemented + tested** | `apps/api/app/vitals.py` maps 8867-4 `/min`, 2708-6 `%`, 9279-1 `/min`, 8310-5 `Cel`/`[degF]` to profiles `heartrate`, `oxygensat`, `resprate`, `bodytemp`. Every stored Observation passed HAPI `$validate` against its profile with 0 errors. Tests: `test_vitals_validation.py` (36 invalid cases), live `test_official_validator_*`. The audit re-checked the codes and units against the page |
| 2 | RCP NEWS2 chart — https://www.rcp.ac.uk/file/9436/download | Planned NEWS2-style baseline (requirement 4) | No. The RCP site refused automated download during this audit | **Not integrated** | The Round 1 risk engine (`apps/api/app/risk.py`) uses simplified prototype bands, labelled in code, API and UI as "Not NEWS2, not clinically validated". No NEWS2 scoring exists, and its bands have not been checked against the chart |
| 3 | PhysioNet BIDMC PPG and Respiration Dataset v1.0.0 — https://www.physionet.org/content/bidmc/1.0.0/ | Replay of real monitoring recordings (requirement 2) | **No.** `physionet.org` and the `physionet-open` S3 mirror are denied by the build workspace's network policy (CHECKPOINTS.md, B4) | **Not integrated: no recording parsed or replayed** | `services/bidmc/` contains only a README. Facts from the dataset page, for planning only: 53 recordings, about 8 min each, 125 Hz signals; numerics at 1 Hz: HR, RR and SpO2; open access under the ODC Attribution License. **No temperature**, so replay will cover 3 of the 4 vitals |
| 4 | 2025 meta-analysis — https://doi.org/10.1002/jhm.70224 | Background evidence for post-discharge monitoring | No | **Unverified, referenced only** | The DOI link failed at the publisher during the audit and a search found nothing. Title, findings and relevance are unknown, so nothing in the repo relies on it |
| 5 | 2026 JAMA Network Open trial — https://jamanetwork.com/journals/jamanetworkopen/fullarticle/2850152 | Background evidence and design caution | No | **Referenced only** | Remote monitoring RCT after sepsis or lower respiratory infection; RPM did not increase home days, and older patients did worse. Not used by code; supports keeping claims modest |
| 6 | Synthea — https://synthetichealth.github.io/synthea/ | Synthetic discharge patients with conditions and medications (requirement 3) | **Yes**: release jar v3.4.0 from GitHub, SHA-256 `38678aab…5702432` (pinned in `services/synthea/synthea.lock.json`; jar and output git-ignored) | **Implemented + tested** | `services/synthea/pipeline.py`: 18 patients generated (seed 20260301), byte-identical across runs; 8 discharge profiles imported into HAPI, 0 errors; `verify` 8/8. Live tests check ≥5 complete profiles. The dashboard lists them from `/api/patients` |

## What the Round 1 demo really shows

- **Real:** Synthea-generated patients in HAPI (6), R4 vital-sign Observations validated by HAPI against the official profiles (1), HAPI storage and live read-back.
- **Simulated:** every live vital comes from the deterministic simulator (`apps/api/app/simulator.py`), not from BIDMC or a device.
- **Prototype:** risk levels come from simplified rules, not NEWS2 (2).
- **Not claimed:** BIDMC integration (3), NEWS2 scoring (2), and any clinical effectiveness drawn from sources 4–5.

## Next steps (not started)

1. Obtain the BIDMC files: download on a machine that can reach PhysioNet, or allow `physionet.org` for this workspace. Parse one recording, replay its HR, RR and SpO2 numerics through the ingestion endpoint, and record evidence before claiming integration.
2. Get the NEWS2 chart PDF into the repo manually, then implement and test the bands against it.
3. Supply the meta-analysis citation details (title, authors) so it can be verified.
