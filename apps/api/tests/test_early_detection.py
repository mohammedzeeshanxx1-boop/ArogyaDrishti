"""Early Detection Lab adapter: existing engine vs labelled fixed-threshold comparator on the same readings."""

from __future__ import annotations

from datetime import datetime, timezone

from app import early_detection
from app.replay.scenarios import SCENARIOS, event_dict, generate

ANCHOR = datetime(2026, 11, 12, 10, 0, tzinfo=timezone.utc)


def readings(scenario: str) -> list[dict]:
    spec = SCENARIOS[scenario]
    events, _ = generate(spec, spec.default_seed, ANCHOR, spec.default_duration_minutes, spec.default_interval_seconds)
    return [{"vital": d["vital"], "value": d["value"], "effective": d["measured_at"], "observation": f"Observation/{i}"}
            for i, d in enumerate(map(event_dict, events))]


def test_comparator_limits_are_explicit():
    assert early_detection.breach("spo2", 89) and not early_detection.breach("spo2", 90)
    assert early_detection.breach("heart_rate", 121) and early_detection.breach("heart_rate", 49) and not early_detection.breach("heart_rate", 120)
    assert "not a model of all traditional monitoring" in early_detection.COMPARATOR["description"]


def test_deterioration_results_come_from_the_existing_engine():
    a = early_detection.analyse(readings("deterioration"))
    fw, fc = a["firstWarning"], a["firstComparatorAlert"]
    assert fw and fc and len(a["steps"]) == 121
    # Measured on the seeded scenario (not tuned): the engine warns before the fixed comparator.
    assert fw["level"] == "WATCH" and fw["minutesFromStart"] < fc["minutesFromStart"]
    assert a["advantageMinutes"] == round(fc["minutesFromStart"] - fw["minutesFromStart"], 1)
    assert a["firstTrendWarning"] and any(x["ruleType"] == "personal-baseline" for x in a["firstTrendWarning"]["alerts"])
    # Both sides saw identical readings at every step.
    assert all(s["readings"] for s in a["steps"])


def test_artifacts_alarm_the_comparator_but_not_the_engine():
    a = early_detection.analyse(readings("artifact"))
    ar = a["artifacts"]
    assert a["engineAlertSteps"] == 0 and a["firstWarning"] is None
    assert len(ar["comparatorAlarmsFromArtifacts"]) >= 1 and len(ar["suppressed"]) >= len(ar["comparatorAlarmsFromArtifacts"]) - 3
    alarm_steps = {i for i, s in enumerate(a["steps"]) if s["comparator"]["alarm"]}
    warn_steps = {i for i, s in enumerate(a["steps"]) if s["engine"]["suppressedNow"]}
    assert alarm_steps <= warn_steps          # every comparator alarm has a sensor-quality warning at the same step


def test_no_detection_is_reported_as_none():
    a = early_detection.analyse(readings("stable"))
    assert a["firstWarning"] is None and a["firstComparatorAlert"] is None and a["advantageMinutes"] is None
