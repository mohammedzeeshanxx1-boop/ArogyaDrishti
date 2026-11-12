# services/bidmc

**Not implemented (planned for C2).** This directory holds no recordings and no replay code yet.

Plan:

- Replay real recordings from the BIDMC PPG and Respiration Dataset on PhysioNet (https://physionet.org/content/bidmc/).
- Download with a script, verify checksums, and keep the data out of git (`services/bidmc/data/` is ignored).
- Confirm the dataset version, licence, citation and signal contents from the PhysioNet page at C2 and record them here before any use.
- Convert replayed vitals to FHIR R4 Observations through the same ingestion path as the simulator.

If PhysioNet cannot be reached from the build environment, C2 is reported as BLOCKED. Simulated data is never presented as BIDMC data.
