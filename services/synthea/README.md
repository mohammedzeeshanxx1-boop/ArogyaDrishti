# services/synthea

**Not implemented (planned for C3).** This directory holds no patient data and no generator script yet.

Plan:

- Generate at least 5 synthetic patients with [Synthea](https://github.com/synthetichealth/synthea), exported as FHIR R4, using a fixed seed so the cohort is reproducible.
- Keep each patient's Conditions and Medications, which drive the personalization rules.
- Load the bundles into HAPI FHIR.
- Record the Synthea version, seed and exact command alongside the output.

Profiles must come from an actual Synthea run. Hand-written stand-ins are not acceptable for requirement 3.
