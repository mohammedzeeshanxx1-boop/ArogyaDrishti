"""Deterministic replay engine (Phase 1).

Modules:
  clock        simulated clock with speed and pause/resume
  scenarios    seeded scenario definitions -> measurement events (+ separate ground truth)
  sources      EventSource interface; simulated source now, BIDMC source later
  persistence  FHIR transaction-bundle writer with idempotent conditional create
  store        SQLite metadata: sessions, per-event persistence status, ground truth
  engine       session lifecycle (start/pause/resume/stop/reset) and the manager

Separation rule: ground-truth annotations live only in store.ground_truth tables and
are written by the engine at session creation. Nothing that the detector reads (FHIR
Observations, MeasurementEvent) carries a label, a scenario id or an onset time.
"""
