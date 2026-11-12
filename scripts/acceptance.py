#!/usr/bin/env python3
"""End-to-end acceptance test for Arogya Drishti against a RUNNING localhost stack.

Every check talks to the real services (FastAPI, HAPI FHIR, Vite proxy, WebSocket) and records
PASS / FAIL / BLOCKED with the evidence it saw. Nothing is assumed or hard-coded.

Usage (from the repo root, services started with scripts/dev/up.sh):
  .venv/bin/python scripts/acceptance.py            # about 3 minutes
  .venv/bin/python scripts/acceptance.py --with-tests   # also runs scripts/check.sh

Writes .local/api/reports/acceptance-latest.json (shown in the dashboard's Judge Evidence Console).
URLs come from the environment (.env.local / .env.local.example defaults).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def env_defaults() -> dict:
    vals = {}
    for f in (ROOT / ".env.local.example", ROOT / ".env.local"):
        if f.exists():
            for line in f.read_text().splitlines():
                if "=" in line and not line.lstrip().startswith("#"):
                    k, v = line.split("=", 1)
                    vals[k.strip()] = v.strip()
    vals.update({k: v for k, v in os.environ.items() if k in vals})
    return vals


E = env_defaults()

# The API requires sign-in. Use the local doctor account created by scripts/dev/accounts.sh.
import http.cookiejar
JAR = http.cookiejar.CookieJar()
urllib.request.install_opener(urllib.request.build_opener(urllib.request.HTTPCookieProcessor(JAR)))


def sign_in() -> None:
    db = Path(E.get("APP_SQLITE_PATH", ".local/api/app.db"))
    creds = (db if db.is_absolute() else ROOT / db).resolve().parent / "credentials.json"
    if not creds.exists():
        print(f"BLOCKED  sign_in  no {creds}; run scripts/dev/accounts.sh"); return
    doc = next(x for x in json.loads(creds.read_text())["accounts"] if x["role"] == "doctor")
    req = urllib.request.Request(f"http://localhost:{E.get('API_PORT', '8000')}/api/auth/login", method="POST",
                                 data=json.dumps({"username": doc["username"], "password": doc["password"]}).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        print(f"signed in as {doc['username']} (HTTP {r.status})")


def cookie_header() -> dict:
    return {"Cookie": "; ".join(f"{c.name}={c.value}" for c in JAR)} if len(JAR) else {}
API = f"http://localhost:{E.get('API_PORT', '8000')}"
WEB = f"http://localhost:{E.get('WEB_PORT', '5173')}"
FHIR = E.get("FHIR_BASE_URL", "http://localhost:8090/baseR4").rstrip("/")
checks: dict[str, dict] = {}


def record(name: str, status: str, evidence: str) -> None:
    checks[name] = {"status": status, "evidence": evidence}
    print(f"{status:8} {name:28} {evidence}", flush=True)


def call(method: str, url: str, body=None, timeout: float = 300):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method,
                                 headers={"Content-Type": "application/json", "Accept": "application/fhir+json, application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read() or b"null")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read() or b"null")
        except ValueError:
            return e.code, None
    except (urllib.error.URLError, ConnectionError, TimeoutError) as e:
        return 0, {"error": str(e)}


def guard(name):
    def deco(fn):
        def run(*a, **k):
            try:
                return fn(*a, **k)
            except Exception as exc:  # a crashed check is a FAIL with the reason, never a silent pass
                record(name, "FAIL", f"check raised {type(exc).__name__}: {exc}")
        return run
    return deco


# ------------------------------------------------------------------ checks
@guard("services_up")
def services():
    c1, meta = call("GET", f"{FHIR}/metadata", timeout=30)
    c2, _ = call("GET", f"{API}/health", timeout=10)
    c3, _ = call("GET", f"{WEB}/api/v1/meta", timeout=10)
    ok = c1 == 200 and (meta or {}).get("fhirVersion", "").startswith("4.0") and c2 == 200
    record("services_up", "PASS" if ok and c3 == 200 else ("PARTIAL" if ok else "BLOCKED"),
           f"HAPI {c1} FHIR {(meta or {}).get('fhirVersion')}; API {c2}; web proxy {c3}")
    return ok


@guard("patients_8")
def patients():
    c, body = call("GET", f"{API}/api/patients")
    everyone = (body or {}).get("patients", [])
    # The 8 Synthea discharge profiles must stay complete. Patients registered in the Doctor Portal (form or
    # CSV import) legitimately have no conditions or medications and are reported separately.
    pts = [p for p in everyone if p.get("source", "synthea") == "synthea"]
    portal = len(everyone) - len(pts)
    cw, bw = call("GET", f"{WEB}/api/patients")
    complete = 0
    for p in pts:
        _, prof = call("GET", f"{API}/api/patients/{p['id']}/profile")
        complete += bool(prof and prof["completeness"]["complete"] and prof["activeConditions"] and prof["activeMedications"])
    ok = len(pts) >= 8 and complete == len(pts) and (bw or {}).get("count") == len(everyone)
    record("patients_8", "PASS" if ok else "FAIL",
           f"{len(pts)} Synthea patients ({complete} complete with conditions and medications) + {portal} registered in the Doctor Portal; "
           f"{len(everyone)} via API, {(bw or {}).get('count')} via web proxy")
    return pts


@guard("live_simulation")
def live_simulation(pid):
    call("POST", f"{API}/api/demo/reset", {"patientId": pid})
    c, st = call("POST", f"{API}/api/demo/simulator/start", {"patientId": pid, "scenario": "deterioration", "steps": 20, "intervalSeconds": 1.0})
    if c != 200:
        record("live_simulation", "FAIL", f"start returned {c}: {st}")
        return None
    t0, levels, last = time.time(), [], None
    while time.time() - t0 < 120:
        _, m = call("GET", f"{API}/api/demo/monitor/{pid}")
        if m and m.get("risk"):
            lvl = m["risk"]["level"]
            if not levels or levels[-1][1] != lvl:
                levels.append((round(time.time() - t0, 1), lvl))
            last = m
        if m and m.get("simulator") and not m["simulator"]["running"] and m["simulator"]["step"] == 20:
            time.sleep(1.5)
            _, last = call("GET", f"{API}/api/demo/monitor/{pid}")
            if levels[-1][1] != last["risk"]["level"]:
                levels.append((round(time.time() - t0, 1), last["risk"]["level"]))
            break
        time.sleep(0.7)
    sim = last["simulator"]
    vit = {k: v["latest"]["value"] for k, v in last["vitals"].items() if v["latest"]}
    ok = sim["accepted"] == 80 and sim["rejected"] == 0 and len(vit) == 4
    record("live_simulation", "PASS" if ok else "FAIL",
           f"{sim['accepted']} readings accepted, {sim['rejected']} rejected; latest {vit}")
    seen = [l for _, l in levels]
    need = ["WATCH", "REVIEW", "URGENT"]
    record("levels_seen", "PASS" if all(n in seen for n in need) else "FAIL",
           " → ".join(f"{l}@{t}s" for t, l in levels))
    return last


@guard("clinical_workflow")
def clinical_workflow(pid, idle_pid):
    """Server-side assessment and alert events after the live simulation, plus the clinician views."""
    time.sleep(3)
    _, al = call("GET", f"{API}/api/alerts?patient={pid}&limit=50")
    events = (al or {}).get("alerts", [])
    levels = [e["level"] for e in reversed(events)]
    _, ov = call("GET", f"{API}/api/clinical/overview")
    me = next((p for p in (ov or {}).get("patients", []) if p["id"] == pid), None)
    idle = next((p for p in (ov or {}).get("patients", []) if p["id"] == idle_pid), None)
    _, src = call("GET", f"{API}/api/monitoring/status")
    ok_alerts = {"WATCH", "REVIEW", "URGENT"} <= set(levels) and all(e["reason"] and e["observation"] for e in events if e["level"] != "NORMAL")
    record("alert_events", "PASS" if ok_alerts else "FAIL",
           f"{len(events)} alert events recorded server-side for this patient; recent sequence: {' → '.join(levels[-6:])}; e.g. \"{events[0]['reason'][:90] if events else ''}\"")
    ok_ov = me and me["monitoring"]["assessable"] and me["monitoring"]["level"] == "URGENT" and me["monitoring"]["monitoringStatus"] == "active"
    record("overview_status", "PASS" if ok_ov else "FAIL",
           f"overview: {len((ov or {}).get('patients', []))} patients; this patient {me['monitoring']['level'] if me else None} / {me['monitoring']['monitoringStatus'] if me else None}")
    if idle:
        ok_idle = idle["monitoring"]["level"] is None and not idle["monitoring"]["assessable"] or idle["monitoring"]["monitoringStatus"] != "no_recent_data"
        record("no_data_not_normal", "PASS" if ok_idle else "FAIL",
               f"patient without recent readings: status {idle['monitoring']['monitoringStatus']}, level {idle['monitoring']['level']} (no fabricated NORMAL)")
    record("monitoring_source_status", "PASS" if (src or {}).get("status") == "receiving" and "simulated" in str(src.get("latestSourceLabel")) else "FAIL",
           f"status {(src or {}).get('status')}, label {(src or {}).get('latestSourceLabel')!r}, physical devices {(src or {}).get('physicalDevicesConnected')}")


@guard("fhir_readback")
def fhir_readback(m, pid):
    oid = m["fhirProof"]["id"]
    c1, hapi = call("GET", f"{FHIR}/Observation/{oid}")
    c2, api = call("GET", f"{API}/api/fhir/Observation/{oid}")
    ok = (c1 == 200 and c2 == 200 and hapi == api and hapi["subject"]["reference"] == f"Patient/{pid}"
          and hapi["meta"]["profile"] and m["fhirProof"]["readBackMatches"] is True and m["fhirProof"]["hapiValidationErrors"] == 0)
    record("fhir_readback", "PASS" if ok else "FAIL",
           f"Observation/{oid}: HAPI {c1}, API {c2}, identical={hapi == api}, {hapi['code']['coding'][0]['code']} = {hapi['valueQuantity']['value']} "
           f"{hapi['valueQuantity']['code']}, profile {hapi['meta']['profile'][0].rsplit('/', 1)[1]}, ingest read-back match {m['fhirProof']['readBackMatches']}, $validate errors {m['fhirProof']['hapiValidationErrors']}")


@guard("explanations")
def explanations(m):
    alerts = [a for a in m["risk"]["alerts"] if a["level"] != "NORMAL"]
    bad, resolved = [], 0
    for a in alerts:
        if not (a.get("rule") and a.get("reason") and a.get("unit") is not None and a.get("value") is not None and a.get("observation")):
            bad.append(a.get("vitalLabel"))
        for ref in str(a["observation"]).split(","):
            c, _ = call("GET", f"{FHIR}/{ref.strip()}")
            resolved += c == 200
    refs = sum(len(str(a["observation"]).split(",")) for a in alerts)
    record("explanations", "PASS" if alerts and not bad and resolved == refs else "FAIL",
           f"{len(alerts)} alerts at {m['risk']['level']}; all have rule/value/unit/reason: {not bad}; {resolved}/{refs} triggering Observations resolve in HAPI; e.g. \"{alerts[0]['reason'] if alerts else ''}\"")


@guard("news2_scoring")
def news2(m):
    n = m["risk"]["news2"]
    s = sum(p["score"] for p in n["parameters"].values())
    ok = n["total"] == s and n["measuredParameters"] == 4 and n["partial"]
    record("news2_scoring", "PASS" if ok else "FAIL",
           f"NEWS2-style total {n['total']} = sum of {{{', '.join(f'{k}: {p['value']}→{p['score']}' for k, p in n['parameters'].items())}}}; partial {n['measuredParameters']}/7; band source not verified against the RCP PDF")


@guard("websocket_updates")
def websocket(pid):
    import websockets  # installed with uvicorn[standard]

    async def run(url):
        got = []
        async with websockets.connect(url, open_timeout=10, max_size=None, additional_headers=cookie_header()) as ws:
            while len(got) < 2:
                msg = json.loads(await asyncio.wait_for(ws.recv(), 30))
                if msg["type"] == "monitor":
                    got.append((msg["seq"], msg["data"]["risk"]["level"], msg["data"]["evaluatedAt"]))
        return got

    direct = asyncio.run(run(f"{API.replace('http', 'ws', 1)}/ws/monitor/{pid}?interval=0.5"))
    proxied = asyncio.run(run(f"{WEB.replace('http', 'ws', 1)}/ws/monitor/{pid}?interval=0.5"))
    ok = [s for s, _, _ in direct] == [1, 2] and [s for s, _, _ in proxied] == [1, 2] and direct[0][2] != direct[1][2]
    record("websocket_updates", "PASS" if ok else "FAIL",
           f"direct pushes {direct}; via Vite proxy {[(s, l) for s, l, _ in proxied]}")


def replay(pid, scenario, minutes):
    c, s = call("POST", f"{API}/api/replay/sessions", {"patientId": pid, "scenario": scenario, "speed": "batch", "durationMinutes": minutes})
    c2, done = call("POST", f"{API}/api/replay/sessions/{s['sessionId']}/start?wait=true", {})
    return done


@guard("scale2")
def scale2(pid):
    call("DELETE", f"{API}/api/patients/{pid}/scale2")
    done = replay(pid, "deterioration", 60)
    _, m1 = call("GET", f"{API}/api/demo/monitor/{pid}")
    c, st = call("POST", f"{API}/api/patients/{pid}/scale2", {"prescribedBy": "Acceptance test (synthetic clinician)", "reason": "target 88-92% for confirmed hypercapnic respiratory failure (test)"})
    _, m2 = call("GET", f"{API}/api/demo/monitor/{pid}")
    _, st3 = call("DELETE", f"{API}/api/patients/{pid}/scale2")
    _, m3 = call("GET", f"{API}/api/demo/monitor/{pid}")
    p = lambda m: m["risk"]["news2"]["parameters"]["spo2"]
    ok = (done["state"] == "completed" and m1["risk"]["news2"]["spo2Scale"] == 1 and m2["risk"]["news2"]["spo2Scale"] == 2
          and m3["risk"]["news2"]["spo2Scale"] == 1 and p(m2)["score"] <= p(m1)["score"] and st["flag"] and st3["flag"] is None)
    record("scale2", "PASS" if ok else "FAIL",
           f"SpO2 {p(m1)['value']}%: Scale 1 score {p(m1)['score']} → after FHIR {st['flag']['reference']} Scale 2 score {p(m2)['score']} "
           f"(total {m1['risk']['news2']['total']}→{m2['risk']['news2']['total']}) → flag cleared, Scale {m3['risk']['news2']['spo2Scale']}")


@guard("personal_baselines")
def baselines(pid):
    done = replay(pid, "stable", 120)
    _, m = call("GET", f"{API}/api/demo/monitor/{pid}")
    b = {k: v["baseline"] for k, v in m["risk"]["news2"]["parameters"].items()}
    ok = done["state"] == "completed" and all(x and x["n"] >= 20 for x in b.values()) and m["risk"]["level"] == "NORMAL"
    record("personal_baselines", "PASS" if ok else "FAIL",
           f"baselines from {done['persisted']} stored readings: " + ", ".join(f"{k} median {x['median']} MAD {x['mad']} (n={x['n']})" for k, x in b.items() if x)
           + f"; level {m['risk']['level']}. Rule-level behaviour (deviation, chronic tolerance, safety floor) is covered by unit tests")


@guard("artifact_suppression")
def artifacts(pid):
    done = replay(pid, "artifact", 120)
    _, mp = call("GET", f"{API}/api/demo/monitor/{pid}?mode=personalized")
    reasons = sorted({s["reason"].split(":")[0].split(" (")[0] for s in mp["risk"]["suppressed"]})
    ok = done["state"] == "completed" and mp["risk"]["suppressedCount"] > 0 and any("probe-off" in r for r in reasons)
    record("artifact_suppression", "PASS" if ok else "FAIL",
           f"{mp['risk']['suppressedCount']} readings suppressed in the latest window ({'; '.join(reasons)}); personalized level {mp['risk']['level']}")


@guard("bidmc_replay")
def bidmc():
    d = ROOT / "services" / "bidmc" / "data"
    files = sorted(d.glob("*.csv")) if d.exists() else []
    record("bidmc_replay", "BLOCKED" if not files else "FAIL",
           "no genuine PhysioNet BIDMC files in services/bidmc/data; no substitute data used" if not files
           else f"{len(files)} files present but BIDMC replay is not implemented yet")


@guard("replay_lab")
def replay_lab(pid):
    runs = []
    for _ in range(2):
        c, r = call("POST", f"{API}/api/evaluation/run", {"patientId": pid, "durationMinutes": 240}, timeout=900)
        if c != 200:
            record("replay_lab", "FAIL", f"evaluation returned {c}: {r}")
            return None
        runs.append(r)
    key = lambda r: {s["scenario"]: s["modes"] for s in r["scenarios"]}
    same = key(runs[0]) == key(runs[1])
    sc = {s["scenario"]: s for s in runs[1]["scenarios"]}
    a, d, da = sc["artifact"]["modes"], sc["deterioration"]["modes"], sc["deterioration_artifact"]["modes"]
    ok = same and a["personalized"]["falseAlertEpisodes"] < a["fixed"]["falseAlertEpisodes"] and d["personalized"]["detectedBeforeCritical"]
    record("replay_lab", "PASS" if ok else "FAIL",
           f"2 independent runs, identical metrics: {same}. Lead before critical (deterioration): fixed {d['fixed']['leadTimeBeforeCriticalMin']} / personalized {d['personalized']['leadTimeBeforeCriticalMin']} min; "
           f"artifact alerts/patient-day fixed {a['fixed']['alertsPerPatientDay']} vs personalized {a['personalized']['alertsPerPatientDay']}; "
           f"false episodes artifact {a['fixed']['falseAlertEpisodes']}→{a['personalized']['falseAlertEpisodes']}, deterioration+artifact {da['fixed']['falseAlertEpisodes']}→{da['personalized']['falseAlertEpisodes']}")
    return runs[1]


@guard("unit_integration_frontend")
def run_tests():
    p = subprocess.run(["bash", str(ROOT / "scripts" / "check.sh")], capture_output=True, text=True, cwd=ROOT, timeout=1800)
    lines = [l.strip() for l in p.stdout.splitlines() if " passed" in l or "Tests " in l or "CHECKS" in l]
    record("unit_integration_frontend", "PASS" if p.returncode == 0 else "FAIL", "; ".join(lines)[:400])


@guard("evidence_console")
def evidence(report_path):
    c, ev = call("GET", f"{API}/api/evidence")
    acc = (ev or {}).get("acceptance") or {}
    ok = c == 200 and acc.get("ranAt") == json.loads(report_path.read_text())["ranAt"] and len(ev["requirements"]) == 7
    record("evidence_console", "PASS" if ok else "FAIL",
           f"/api/evidence {c}: " + ", ".join(f"R{r['id']} {r['status']}" for r in (ev or {}).get("requirements", [])) + f"; shows this run: {ok}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--with-tests", action="store_true")
    args = ap.parse_args()
    sign_in()
    started = datetime.now(timezone.utc)
    print(f"Arogya Drishti acceptance · API {API} · web {WEB} · FHIR {FHIR}\n")
    if not services():
        print("\nCore services are not running: start them with scripts/dev/up.sh")
    else:
        pts = patients() or []
        if len(pts) >= 4:
            m = live_simulation(pts[0]["id"])
            if m:
                clinical_workflow(pts[0]["id"], pts[-1]["id"])
                fhir_readback(m, pts[0]["id"])
                explanations(m)
                news2(m)
            websocket(pts[0]["id"])
            scale2(pts[1]["id"])
            baselines(pts[2]["id"])
            artifacts(pts[3]["id"])
            replay_lab(pts[4]["id"] if len(pts) > 4 else pts[3]["id"])
    bidmc()
    if args.with_tests:
        run_tests()
    commit = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, cwd=ROOT).stdout.strip()
    report = {"ranAt": started.isoformat(), "finishedAt": datetime.now(timezone.utc).isoformat(), "commit": commit,
              "command": "scripts/acceptance.py" + (" --with-tests" if args.with_tests else ""),
              "platform": sys.platform, "api": API, "web": WEB, "fhir": FHIR, "checks": checks}
    db = Path(E.get("APP_SQLITE_PATH", ".local/api/app.db"))
    out = (db if db.is_absolute() else ROOT / db).parent / "reports"   # same folder the API reads (next to its SQLite file)
    out.mkdir(parents=True, exist_ok=True)
    path = out / "acceptance-latest.json"
    path.write_text(json.dumps(report, indent=2))
    if checks.get("services_up", {}).get("status") in ("PASS", "PARTIAL"):
        evidence(path)
        report["checks"] = checks
        path.write_text(json.dumps(report, indent=2))
    counts = {s: sum(c["status"] == s for c in checks.values()) for s in ("PASS", "PARTIAL", "FAIL", "BLOCKED")}
    print(f"\n{counts} · report: {path}")
    sys.exit(1 if counts["FAIL"] else 0)


if __name__ == "__main__":
    main()
