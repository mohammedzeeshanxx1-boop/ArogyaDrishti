# Round 1 judge demo: 60-second script

**Before judges arrive** (about 1 minute):

```bash
scripts/dev/up.sh        # HAPI :8090/baseR4, API :8000, web :5173; must end with "HEALTH: no failures, 0 blocked"
```

Open http://localhost:5173. The header pill must read **HAPI FHIR R4 connected · 4.0.1**. Pick **Ariane Kirlin** (first patient) and press **↺ Reset demo** so the window starts empty.

---

**0–10 s: the patient.** "Arogya Drishti watches patients after hospital discharge. These are real Synthea-generated synthetic patients stored in a HAPI FHIR R4 server. Here: 57-year-old, discharged 19 August, ischemic heart disease, on metoprolol, nitroglycerin, clopidogrel and simvastatin. All of it is read live from FHIR."

**10–15 s: start.** Press **▶ Demonstrate Gradual Deterioration**. "A virtual wearable now sends heart rate, SpO2, respiratory rate and temperature every 2 seconds. Each reading is a FHIR Observation, validated against the official R4 vital-signs profile and stored in HAPI."

**15–45 s: escalation** (observed timing: WATCH at about 15 s, REVIEW at about 21 s, URGENT at about 27 s, done at about 40 s). Point at the four charts and the risk banner. "Watch the trends: heart rate rising, SpO2 falling. WATCH… now REVIEW… now URGENT. Every alert says *why*: the vital, the measured value, the rule (threshold or trend), and the exact FHIR Observation that triggered it."

**45–55 s: proof.** Scroll to **FHIR persistence proof** and press **Read back from HAPI now**. "This is the latest Observation ID, read back live from HAPI just now: status final, LOINC code, value, the vital-signs profile, 0 validation errors."

**55–60 s: contrast and honesty.** Optionally select another patient and press **▶ Demonstrate Stable Recovery**: it stays NORMAL for the whole run. "The risk engine sees only stored observations, never the scenario name. It is a prototype rules engine, not NEWS2 and not clinically validated: clinical decision support only."

---

If something goes wrong:
- Pill shows API unreachable or HAPI not connected: run `scripts/dev/health.sh`, then `scripts/dev/up.sh` (already-running services are skipped).
- Scenario seems stuck: press **■ Stop**, then **↺ Reset demo**, then start again.
- Fallback without the UI: `cd apps/api && ../../.venv/bin/python -m app.simulator --patient <id> --scenario deterioration`.
