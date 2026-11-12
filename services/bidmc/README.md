# services/bidmc

**Not implemented (planned for C2).** This directory holds no recordings and no replay code yet.

Plan:

- Replay real recordings from the BIDMC PPG and Respiration Dataset on PhysioNet (https://physionet.org/content/bidmc/).
- Download with a script, verify checksums, and keep the data out of git (`services/bidmc/data/` is ignored).
- Confirm the dataset version, licence, citation and signal contents from the PhysioNet page at C2 and record them here before any use.
- Convert replayed vitals to FHIR R4 Observations through the same ingestion path as the simulator.

Status 2026-11-12: `physionet.org` and the `physionet-open` S3 mirror are both denied by the build workspace's network policy (CHECKPOINTS.md, B4). Until the recordings are available locally, the BIDMC part of C2 is BLOCKED. Simulated data is never presented as BIDMC data.

Replay will run as a local Python process reading files from `services/bidmc/data/` (git-ignored).
