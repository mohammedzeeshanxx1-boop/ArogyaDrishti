# Replay engine: event schema and evaluation design

Phase 1 builds the data needed for evaluation; **no metric is computed yet** and none may be reported until a later phase computes it from these records.

## Data flow

```
EventSource (SimulatedSource now; BidmcSource later)
   ├── events()        -> MeasurementEvent[]   detector-visible: seq, vital, loinc, value, ucum, measured_at, source
   └── ground_truth()  -> GroundTruth[]        evaluation-only: label, start, end, detail
ReplaySession (simulated clock, speed 1x/5x/10x/batch)
   └── persist_batch -> FHIR transaction (conditional create) -> HAPI FHIR R4
Detector (risk engine) reads Observations from HAPI only.
```

## Where each piece lives

| Data | Store | Detector can read? |
|---|---|---|
| Measurement value, LOINC, UCUM, Patient reference, `effectiveDateTime` (= measurement time) | HAPI `Observation` | Yes (only via HAPI) |
| Replay identifier `urn:arogya-drishti:replay-event\|<session>:<seq>`, session tag `urn:arogya-drishti:replay-session\|<session>`, `device.display` (simulated vs BIDMC) | HAPI `Observation` | Visible, carries no label |
| Session parameters (source, scenario, seed, anchor, duration, interval, speed, fingerprint, state, counts) | SQLite `replay_sessions` | No (API status only) |
| Per-event persistence: seq, LOINC, `measured_at`, `ingested_at` (when HAPI confirmed), Observation id, `created`/`existing`, batch number, HAPI shape-validated flag. **No values** | SQLite `replay_events` | No |
| Per-batch outcome: confirmed or failed, sizes, error | SQLite `replay_batches` | No |
| Ground truth: label (`stable`, `deterioration_onset`), start, end | SQLite `replay_ground_truth` | **No.** Read only by `app.replay.store.ground_truth()` |

Leak guards (tests in `apps/api/tests/test_replay.py`): MeasurementEvent has exactly the 7 detector fields; serialized FHIR payloads contain no scenario id, scenario name or label words; `risk.py` imports nothing from replay, store or db; `main.py` never calls `ground_truth()`; API and monitor responses contain no onset.

## Time model

- `measured_at` = simulated measurement time = `Observation.effectiveDateTime`.
- `ingested_at` = wall-clock time HAPI confirmed the batch (also `meta.lastUpdated` in HAPI).
- Anchor default = now − duration (rounded to the minute), so no measurement time is ever in the future, even at 10×. An explicit anchor makes runs fully reproducible: identical (scenario, seed, anchor, duration, interval) give byte-identical events (SHA-256 `fingerprint`).

## How later phases will compute each metric

| Metric | Computation from these records |
|---|---|
| Detection lead time | For sessions with a `deterioration_onset` ground-truth row: (first alert of the required level whose triggering Observation's `measured_at` ≥ session anchor) − onset. Negative means detected before onset (false early alert); none means missed. Alerts must be persisted with their triggering Observation ids (Phase 6) |
| Alerts per patient-day | Count of alert episodes ÷ (sum of `measured_at` span per session ÷ 86,400 s), per detector mode |
| False alert episodes | Alert episodes whose time lies inside a ground-truth `stable` or artifact window. Artifact windows get a ground-truth label in Phase 3. On BIDMC (no labels), report alert burden only |
| FHIR compliance | Share of events confirmed by HAPI (`replay_events`, `replay_batches`) plus `$validate` outcomes (live path: every Observation, `ingestion_events`; replay path: once per vital per session plus strict local validation of every Observation). Report the validation coverage alongside the rate |
| Explainability | Share of persisted alerts with all explanation fields (rule, measured value, unit, triggering Observation id that resolves in HAPI, reason) |

## Throughput (measured 2026-11-12, HAPI 5.7.0 / H2, this workspace)

- Transaction with conditional create: about 80 Observations/s; re-sending an already-stored batch: about 800/s (all `200`).
- 24 simulated hours × 4 vitals at 60 s (5,764 Observations): 55 s in batch mode, 15 batches of 400, all confirmed.
