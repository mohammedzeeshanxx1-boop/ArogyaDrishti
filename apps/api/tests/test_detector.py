"""NEWS2-style scoring, Sensor Trust Engine, personalized baselines, offline scenario evaluation."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app import detector as d
from app import evaluation as ev
from app.replay.scenarios import SCENARIOS, generate

T0 = datetime(2026, 11, 10, 6, 0, tzinfo=timezone.utc)


def rd(vital, value, i, oid=None):
    return {"vital": vital, "value": value, "effective": (T0 + timedelta(minutes=i)).isoformat(), "observation": oid or f"Observation/{vital}-{i}"}


@pytest.mark.parametrize("fn,cases", [
    (d.score_rr, [(8, 3), (9, 1), (11, 1), (12, 0), (20, 0), (21, 2), (24, 2), (25, 3)]),
    (d.score_spo2_scale1, [(91, 3), (92, 2), (93, 2), (94, 1), (95, 1), (96, 0)]),
    (d.score_spo2_scale2, [(83, 3), (84, 2), (85, 2), (86, 1), (87, 1), (88, 0), (92, 0), (97, 0)]),
    (d.score_pulse, [(40, 3), (41, 1), (50, 1), (51, 0), (90, 0), (91, 1), (110, 1), (111, 2), (130, 2), (131, 3)]),
    (d.score_temp, [(35.0, 3), (35.1, 1), (36.0, 1), (36.1, 0), (38.0, 0), (38.1, 1), (39.0, 1), (39.1, 2)]),
])
def test_news2_band_boundaries(fn, cases):
    for value, score in cases:
        assert fn(value) == score, (fn.__name__, value)


def test_level_mapping():
    assert d.level_from_news2(0, False) == "NORMAL"
    assert d.level_from_news2(4, False) == "WATCH"
    assert d.level_from_news2(3, True) == "REVIEW"
    assert d.level_from_news2(5, False) == "REVIEW"
    assert d.level_from_news2(7, False) == "URGENT"


def test_scale2_only_changes_spo2_scoring_when_flagged():
    r = [rd("spo2", 89, 0)]
    assert d.evaluate(r, "fixed", scale2=False)["news2"]["parameters"]["spo2"]["score"] == 3
    res = d.evaluate(r, "fixed", scale2=True)
    assert res["news2"]["parameters"]["spo2"]["score"] == 0 and res["news2"]["spo2Scale"] == 2


def test_partial_score_is_labelled():
    res = d.evaluate([rd("heart_rate", 70, 0)], "fixed")
    assert res["news2"]["partial"] and res["news2"]["of"] == 7 and len(res["news2"]["notAvailable"]) == 3
    assert "not yet verified" in res["label"] and "partial" in res["label"]


def test_trust_engine_suppresses_probe_off_and_isolated_spikes():
    hr = [rd("heart_rate", v, i) for i, v in enumerate([74, 75, 0, 0, 74, 73, 140, 74, 75])]
    res = d.evaluate(hr, "personalized")
    reasons = [s["reason"] for s in res["suppressed"]]
    assert sum("probe-off" in r for r in reasons) == 2 and sum("isolated spike" in r for r in reasons) == 1
    assert res["level"] == "NORMAL"
    assert d.evaluate(hr, "fixed")["level"] == "NORMAL"    # fixed scores only the latest raw value (75)
    assert d.evaluate(hr[:7], "fixed")["level"] == "REVIEW"   # ...which alerts while the spike is the latest reading
    held = d.evaluate(hr[:7], "personalized")
    assert held["level"] == "NORMAL" and "unconfirmed jump" in held["suppressed"][-1]["reason"]


def test_sustained_jump_is_accepted_once_confirmed():
    hr = [rd("heart_rate", v, i) for i, v in enumerate([74, 75, 74, 120, 121, 122])]
    res = d.evaluate(hr, "personalized")
    assert res["news2"]["parameters"]["heart_rate"]["value"] == 122 and res["level"] == "WATCH"   # 111-130 scores 2


def test_baseline_warm_up_then_deviation_rule_raises_watch_inside_normal_bands():
    hr = [rd("heart_rate", 62 + (i % 2), i) for i in range(40)]          # personal baseline ~62
    assert d.evaluate(hr, "personalized")["level"] == "NORMAL"
    hr += [rd("heart_rate", 84, 40 + k) for k in range(3)]              # still NEWS2 score 0 (51-90)
    res = d.evaluate(hr, "personalized")
    assert res["news2"]["total"] == 0 and res["level"] == "WATCH"
    a = next(a for a in res["alerts"] if a["ruleType"] == "personal-baseline")
    assert a["baseline"]["median"] in (62, 62.5) and "personal baseline" in a["reason"]
    assert d.evaluate(hr, "fixed")["level"] == "NORMAL"
    short = [rd("heart_rate", 62, i) for i in range(10)] + [rd("heart_rate", 84, 10 + k) for k in range(3)]
    assert d.evaluate(short, "personalized")["level"] == "NORMAL"      # warm-up: no baseline yet


def test_chronic_baseline_tolerance_and_safety_floor():
    hr = [rd("heart_rate", 96 + (i % 3), i) for i in range(40)]          # chronically 96-98: NEWS2 pulse score 1
    assert d.evaluate(hr, "fixed")["level"] == "WATCH"
    tol = d.evaluate(hr, "personalized")
    assert tol["level"] == "NORMAL" and "tolerated" in tol["summary"] + str(tol["alerts"])
    rr = [rd("respiratory_rate", 26, i) for i in range(40)]             # chronic but scores 3 -> never tolerated
    assert d.evaluate(rr, "personalized")["level"] == "REVIEW"


@pytest.fixture(scope="module")
def offline():
    out = {}
    for sid in SCENARIOS:
        spec = SCENARIOS[sid]
        events, truth = generate(spec, spec.default_seed, T0, 240, 60)
        readings = [{"vital": e.vital, "value": e.value, "effective": e.measured_at.isoformat(), "observation": f"Observation/{e.seq}"} for e in events]
        ids = {r["observation"] for r in readings}
        gt = [{"label": t.label, "start_at": t.start.isoformat(), "end_at": t.end.isoformat() if t.end else None} for t in truth]
        out[sid] = {m: ev.metrics(ev.timeline(readings, m, False), gt, ids) for m in ev.MODES}
    return out


def test_offline_stable_has_no_alerts(offline):
    for m in ev.MODES:
        assert offline["stable"][m]["alertEpisodes"] == 0


def test_offline_artifacts_fixed_alerts_personalized_suppresses(offline):
    fixed, pers = offline["artifact"]["fixed"], offline["artifact"]["personalized"]
    assert fixed["falseAlertEpisodes"] > 0 and fixed["artifactAlertEpisodes"] > 0
    assert pers["falseAlertEpisodes"] < fixed["falseAlertEpisodes"]
    assert pers["suppressedReadings"] > 0


def test_offline_deterioration_detected_before_critical_in_both_modes(offline):
    for sid in ("deterioration", "deterioration_artifact"):
        for m in ev.MODES:
            r = offline[sid][m]
            assert r["peakLevel"] == "URGENT" and r["detectedBeforeCritical"] is True, (sid, m, r)
            assert r["explainabilityPct"] == 100.0
