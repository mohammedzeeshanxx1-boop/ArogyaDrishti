#!/usr/bin/env python3
"""Prove that HAPI keeps data across a server restart.

  record  ingest one Observation per supported vital through the API and save
          the ids plus each resource's SHA-256 to a state file
  check   read each saved id directly from HAPI and compare; also confirm the
          Synthea cohort patients are still present

Restart HAPI (e.g. `docker compose restart hapi-fhir`) between the two steps.

Usage:
  scripts/c1_persistence_check.py record --api http://localhost:8000 --fhir http://localhost:8090/fhir
  scripts/c1_persistence_check.py check  --fhir http://localhost:8090/fhir
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

STATE = Path(__file__).resolve().parent.parent / "services" / "synthea" / "output" / "persistence-state.json"
VITALS = {"8867-4": (76, "/min", "beats/minute", "Heart rate"), "2708-6": (96, "%", "%", "Oxygen saturation in Arterial blood"),
          "9279-1": (17, "/min", "breaths/minute", "Respiratory rate"), "8310-5": (36.8, "Cel", "Cel", "Body temperature")}


def http(method: str, url: str, body=None):
    req = urllib.request.Request(url, data=json.dumps(body).encode() if body is not None else None, method=method,
                                 headers={"Content-Type": "application/fhir+json", "Accept": "application/fhir+json"})
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return r.status, json.load(r)
    except urllib.error.HTTPError as e:
        return e.code, json.load(e)


def digest(resource: dict) -> str:
    core = {k: v for k, v in resource.items() if k != "meta"}
    return hashlib.sha256(json.dumps(core, sort_keys=True).encode()).hexdigest()


def record(args) -> None:
    code, patients = http("GET", f"{args.api}/api/patients")
    if code != 200 or not patients["patients"]:
        sys.exit(f"no cohort patients (HTTP {code})")
    pid = patients["patients"][0]["id"]
    when = (datetime.now(timezone.utc) - timedelta(minutes=1)).replace(microsecond=0).isoformat()
    saved = []
    for loinc, (value, ucum, unit, display) in VITALS.items():
        obs = {"resourceType": "Observation", "status": "final",
               "category": [{"coding": [{"system": "http://terminology.hl7.org/CodeSystem/observation-category", "code": "vital-signs"}]}],
               "code": {"coding": [{"system": "http://loinc.org", "code": loinc, "display": display}]},
               "subject": {"reference": f"Patient/{pid}"}, "effectiveDateTime": when,
               "valueQuantity": {"value": value, "unit": unit, "system": "http://unitsofmeasure.org", "code": ucum}}
        code, body = http("POST", f"{args.api}/api/fhir/Observation", obs)
        if code != 201:
            sys.exit(f"ingest {loinc} failed: HTTP {code} {body}")
        _, stored = http("GET", f"{args.fhir}/Observation/{body['id']}")
        saved.append({"id": body["id"], "loinc": loinc, "sha256": digest(stored)})
        print(f"recorded Observation/{body['id']} ({loinc})")
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps({"recordedAt": datetime.now(timezone.utc).isoformat(), "patients": [p["id"] for p in patients["patients"]], "observations": saved}, indent=2))
    print(f"state saved to {STATE}; now restart HAPI and run 'check'")


def check(args) -> None:
    state = json.loads(STATE.read_text())
    failed = False
    for o in state["observations"]:
        code, stored = http("GET", f"{args.fhir}/Observation/{o['id']}")
        ok = code == 200 and digest(stored) == o["sha256"]
        failed |= not ok
        print(f"{'PASS' if ok else 'FAIL'}  Observation/{o['id']} ({o['loinc']}) HTTP {code}")
    for pid in state["patients"]:
        code, _ = http("GET", f"{args.fhir}/Patient/{pid}")
        failed |= code != 200
        print(f"{'PASS' if code == 200 else 'FAIL'}  Patient/{pid} HTTP {code}")
    print("PERSISTENCE CHECK " + ("FAILED" if failed else "PASSED"))
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("step", choices=["record", "check"])
    ap.add_argument("--api", default="http://localhost:8000")
    ap.add_argument("--fhir", default="http://localhost:8090/fhir")
    a = ap.parse_args()
    {"record": record, "check": check}[a.step](a)
