#!/usr/bin/env python3
"""Reproducible Synthea pipeline for Arogya Drishti discharge profiles.

Steps (stdlib only; needs Java 11+ for Synthea):
  fetch     download the pinned Synthea jar and verify its SHA-256
  generate  run Synthea with the pinned seeds into output/raw
  select    pick discharge profiles and write import-ready bundles to output/cohort
  import    load hospital/practitioner bundles, then each cohort bundle, into HAPI FHIR
  verify    read every cohort patient back from HAPI and check its profile and references
  all       every step in order

Usage:
  python3 services/synthea/pipeline.py all --fhir-base http://localhost:8090/baseR4

Inputs are pinned in synthea.lock.json. Outputs are synthetic and stay out of git
(services/synthea/output/ is ignored); output/manifest.json and
output/import-report.json record what was produced.
"""

from __future__ import annotations

import argparse
import glob
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
LOCK = json.loads((HERE / "synthea.lock.json").read_text())
CACHE = HERE / ".cache"
OUT = HERE / "output"
RAW = OUT / "raw"
COHORT = OUT / "cohort"
SYNTHEA_ID_SYSTEM = "https://github.com/synthetichealth/synthea"
VITAL_SIGNS = "vital-signs"


def log(msg: str) -> None:
    print(f"[synthea] {msg}", flush=True)


def jar_path() -> Path:
    return CACHE / f"synthea-{LOCK['synthea']['version']}.jar"


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# ---------------------------------------------------------------- fetch
def fetch(_: argparse.Namespace) -> None:
    jar, want = jar_path(), LOCK["synthea"]["sha256"]
    if jar.exists() and sha256(jar) == want:
        log(f"jar present and verified: {jar.name}")
        return
    CACHE.mkdir(parents=True, exist_ok=True)
    tmp = jar.with_suffix(".part")
    log(f"downloading {LOCK['synthea']['url']}")
    with urllib.request.urlopen(LOCK["synthea"]["url"], timeout=600) as resp, tmp.open("wb") as fh:
        shutil.copyfileobj(resp, fh)
    got = sha256(tmp)
    if got != want:
        tmp.unlink()
        sys.exit(f"[synthea] SHA-256 mismatch: expected {want}, got {got}")
    tmp.rename(jar)
    log(f"verified {jar.name} sha256={got}")


# ---------------------------------------------------------------- generate
def synthea_args() -> list[str]:
    r = LOCK["run"]
    return [
        "-s", str(r["seed"]),
        "-cs", str(r["clinicianSeed"]),
        "-r", r["referenceDate"],
        "-p", str(r["population"]),
        "-a", r["ageRange"],
        f"--exporter.baseDirectory={RAW}",
        "--exporter.fhir.export=true",
        "--exporter.hospital.fhir.export=true",
        "--exporter.practitioner.fhir.export=true",
        f"--exporter.years_of_history={r['yearsOfHistory']}",
        r["state"],
    ]


def generate(_: argparse.Namespace) -> None:
    jar = jar_path()
    if not jar.exists() or sha256(jar) != LOCK["synthea"]["sha256"]:
        sys.exit("[synthea] jar missing or unverified; run 'fetch' first")
    if RAW.exists():
        shutil.rmtree(RAW)
    cmd = [os.environ.get("JAVA", "java"), "-jar", str(jar), *synthea_args()]
    log("running: " + " ".join(cmd))
    started = time.time()
    proc = subprocess.run(cmd, capture_output=True, text=True, cwd=CACHE)
    (OUT).mkdir(parents=True, exist_ok=True)
    (OUT / "synthea-run.log").write_text(proc.stdout + proc.stderr)
    if proc.returncode != 0:
        sys.exit(f"[synthea] Synthea exited with {proc.returncode}; see output/synthea-run.log")
    n = len(patient_bundle_files())
    if n == 0:
        sys.exit("[synthea] Synthea produced no patient bundles")
    log(f"generated {n} patient bundles in {time.time() - started:.1f}s")


def patient_bundle_files() -> list[Path]:
    files = glob.glob(str(RAW / "fhir" / "*.json"))
    return sorted(Path(f) for f in files if not Path(f).name.startswith(("hospitalInformation", "practitionerInformation")))


def info_bundle_files() -> list[Path]:
    hosp = sorted(glob.glob(str(RAW / "fhir" / "hospitalInformation*.json")))
    prac = sorted(glob.glob(str(RAW / "fhir" / "practitionerInformation*.json")))
    return [Path(p) for p in hosp + prac]  # organizations/locations first


# ---------------------------------------------------------------- select
def _codes(cc: dict | None) -> set[str]:
    return {c.get("code") for c in (cc or {}).get("coding", [])}


def is_vital_sign(res: dict) -> bool:
    return any(VITAL_SIGNS in _codes(cat) for cat in res.get("category", []))


def summarize(bundle: dict) -> dict:
    res = [e["resource"] for e in bundle["entry"]]
    patient = next(r for r in res if r["resourceType"] == "Patient")
    inpatient = [
        r for r in res
        if r["resourceType"] == "Encounter" and r.get("class", {}).get("code") == "IMP" and r.get("period", {}).get("end")
    ]
    active_conditions = [r for r in res if r["resourceType"] == "Condition" and "active" in _codes(r.get("clinicalStatus"))]
    active_meds = [r for r in res if r["resourceType"] == "MedicationRequest" and r.get("status") == "active"]
    last = max(inpatient, key=lambda r: r["period"]["end"]) if inpatient else None
    return {
        "syntheaId": patient["id"],
        "alive": "deceasedDateTime" not in patient and not patient.get("deceasedBoolean", False),
        "birthDate": patient.get("birthDate"),
        "gender": patient.get("gender"),
        "inpatientEncounters": len(inpatient),
        "lastDischarge": last["period"]["end"] if last else None,
        "lastInpatientEncounterId": last["id"] if last else None,
        "activeConditions": len(active_conditions),
        "activeMedicationRequests": len(active_meds),
    }


def eligible(s: dict) -> bool:
    return s["alive"] and s["inpatientEncounters"] > 0 and s["activeConditions"] > 0 and s["activeMedicationRequests"] > 0


def to_import_bundle(bundle: dict) -> dict:
    """Keep only the profile resource types and turn POSTs into idempotent PUTs."""
    keep_types = set(LOCK["import"]["resourceTypes"])
    entries = []
    for e in bundle["entry"]:
        r = e["resource"]
        if r["resourceType"] not in keep_types:
            continue
        if r["resourceType"] == "Observation" and not is_vital_sign(r):
            continue
        uuid = e["fullUrl"].removeprefix("urn:uuid:")
        r = dict(r, id=uuid)
        entries.append({"fullUrl": e["fullUrl"], "resource": r, "request": {"method": "PUT", "url": f"{r['resourceType']}/{uuid}"}})
    kept = {e["fullUrl"] for e in entries}
    dangling = sorted({ref for e in entries for ref in _refs(e["resource"]) if ref.startswith("urn:uuid:") and ref not in kept})
    if dangling:
        raise ValueError(f"subset leaves {len(dangling)} dangling bundle references, e.g. {dangling[:3]}")
    return {"resourceType": "Bundle", "type": "transaction", "entry": entries}


def _refs(obj):
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k == "reference" and isinstance(v, str):
                yield v
            else:
                yield from _refs(v)
    elif isinstance(obj, list):
        for x in obj:
            yield from _refs(x)


def select(_: argparse.Namespace) -> None:
    files = patient_bundle_files()
    if not files:
        sys.exit("[synthea] no raw bundles; run 'generate' first")
    summaries = []
    for f in files:
        s = summarize(json.loads(f.read_text()))
        s["sourceFile"] = f.name
        s["sourceSha256"] = sha256(f)
        summaries.append(s)
    chosen = sorted((s for s in summaries if eligible(s)), key=lambda s: (s["lastDischarge"], s["syntheaId"]))
    chosen.reverse()
    minimum = LOCK["selection"]["minimumCohort"]
    if len(chosen) < minimum:
        sys.exit(f"[synthea] only {len(chosen)} eligible discharge profiles; need {minimum}. Increase run.population.")
    if COHORT.exists():
        shutil.rmtree(COHORT)
    COHORT.mkdir(parents=True)
    for s in chosen:
        bundle = to_import_bundle(json.loads((RAW / "fhir" / s["sourceFile"]).read_text()))
        out = COHORT / f"{s['syntheaId']}.json"
        out.write_text(json.dumps(bundle))
        s["importEntries"] = len(bundle["entry"])
        s["importBundleSha256"] = sha256(out)
    manifest = {
        "synthea": LOCK["synthea"],
        "run": LOCK["run"],
        "commandArgs": synthea_args(),
        "selection": LOCK["selection"],
        "generatedPatients": len(summaries),
        "eligible": len(chosen),
        "cohort": chosen,
        "rejected": [
            {k: s[k] for k in ("syntheaId", "alive", "inpatientEncounters", "activeConditions", "activeMedicationRequests")}
            for s in summaries if not eligible(s)
        ],
        "infoBundles": [{"file": p.name, "sha256": sha256(p)} for p in info_bundle_files()],
    }
    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=2))
    log(f"selected {len(chosen)} of {len(summaries)} patients; wrote output/manifest.json")


# ---------------------------------------------------------------- import / verify
def fhir_request(base: str, method: str, path: str, body: dict | None = None, timeout: int = 600) -> tuple[int, dict]:
    data = json.dumps(body).encode() if body is not None else None
    if path.startswith(("http://", "https://")):
        url = path  # paging links from the server are absolute
    else:
        url = f"{base.rstrip('/')}/{path.lstrip('/')}" if path else base.rstrip("/")
    req = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={"Content-Type": "application/fhir+json", "Accept": "application/fhir+json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read() or b"{}")
    except urllib.error.HTTPError as exc:
        payload = exc.read()
        try:
            return exc.code, json.loads(payload)
        except ValueError:
            return exc.code, {"raw": payload[:500].decode(errors="replace")}


def _bundle_errors(resp: dict) -> list[str]:
    errs = []
    for e in resp.get("entry", []):
        status = e.get("response", {}).get("status", "")
        if not status[:1] in ("2",):
            errs.append(status)
    return errs


def do_import(args: argparse.Namespace) -> None:
    manifest = json.loads((OUT / "manifest.json").read_text())
    base = args.fhir_base
    code, meta = fhir_request(base, "GET", "metadata", timeout=30)
    if code != 200 or meta.get("fhirVersion", "")[:3] != "4.0":
        sys.exit(f"[synthea] FHIR server at {base} is not an R4 server (HTTP {code}, fhirVersion={meta.get('fhirVersion')})")
    report = {"fhirBase": base, "server": meta.get("software"), "fhirVersion": meta.get("fhirVersion"), "info": [], "patients": []}
    for p in info_bundle_files():
        t = time.time()
        code, resp = fhir_request(base, "POST", "", json.loads(p.read_text()))
        errs = _bundle_errors(resp) if code == 200 else [f"HTTP {code}"]
        report["info"].append({"file": p.name, "http": code, "entries": len(resp.get("entry", [])), "errors": errs, "seconds": round(time.time() - t, 1)})
        log(f"{p.name}: HTTP {code}, {len(errs)} entry errors, {time.time() - t:.1f}s")
        if code != 200 or errs:
            (OUT / "import-report.json").write_text(json.dumps(report, indent=2))
            sys.exit(f"[synthea] failed to load {p.name}: {errs[:3] or resp}")
    for s in manifest["cohort"]:
        t = time.time()
        bundle = json.loads((COHORT / f"{s['syntheaId']}.json").read_text())
        code, resp = fhir_request(base, "POST", "", bundle)
        errs = _bundle_errors(resp) if code == 200 else [f"HTTP {code}: {_outcome_text(resp)}"]
        report["patients"].append({"syntheaId": s["syntheaId"], "http": code, "entries": len(bundle["entry"]), "errors": errs[:5], "seconds": round(time.time() - t, 1)})
        log(f"Patient/{s['syntheaId']}: HTTP {code}, {len(bundle['entry'])} entries, {len(errs)} errors, {time.time() - t:.1f}s")
        if code != 200 or errs:
            (OUT / "import-report.json").write_text(json.dumps(report, indent=2))
            sys.exit(f"[synthea] import failed for {s['syntheaId']}")
    (OUT / "import-report.json").write_text(json.dumps(report, indent=2))
    log("import complete")


def _outcome_text(resp: dict) -> str:
    return "; ".join(i.get("diagnostics", "") for i in resp.get("issue", []))[:300] or json.dumps(resp)[:300]


def search_all(base: str, query: str) -> list[dict]:
    out, path = [], query
    while path:
        code, b = fhir_request(base, "GET", path, timeout=120)
        if code != 200:
            raise RuntimeError(f"search {query} -> HTTP {code}")
        out += [e["resource"] for e in b.get("entry", [])]
        path = next((l["url"] for l in b.get("link", []) if l["relation"] == "next"), None)
    return out


def verify(args: argparse.Namespace) -> None:
    manifest = json.loads((OUT / "manifest.json").read_text())
    base, results, failed = args.fhir_base, [], False
    for s in manifest["cohort"]:
        pid = s["syntheaId"]
        code, patient = fhir_request(base, "GET", f"Patient/{pid}", timeout=60)
        conds = search_all(base, f"Condition?subject=Patient/{pid}&_count=200")
        meds = search_all(base, f"MedicationRequest?subject=Patient/{pid}&_count=200")
        encs = search_all(base, f"Encounter?subject=Patient/{pid}&class=IMP&_count=200")
        subj_ok = all(r.get("subject", {}).get("reference") == f"Patient/{pid}" for r in conds + meds + encs)
        ok = (
            code == 200
            and any(i.get("system") == SYNTHEA_ID_SYSTEM and i.get("value") == pid for i in patient.get("identifier", []))
            and any("active" in _codes(c.get("clinicalStatus")) for c in conds)
            and any(m.get("status") == "active" for m in meds)
            and len(encs) == s["inpatientEncounters"]
            and subj_ok
        )
        failed |= not ok
        results.append({"patient": f"Patient/{pid}", "http": code, "conditions": len(conds), "medicationRequests": len(meds), "inpatientEncounters": len(encs), "subjectsReferencePatient": subj_ok, "ok": ok})
        log(f"verify Patient/{pid}: {'OK' if ok else 'FAIL'} conditions={len(conds)} meds={len(meds)} inpatient={len(encs)}")
    report_path = OUT / "import-report.json"
    report = json.loads(report_path.read_text()) if report_path.exists() else {}
    report["verify"] = results
    report_path.write_text(json.dumps(report, indent=2))
    if failed:
        sys.exit("[synthea] verification FAILED")
    log(f"verified {len(results)} discharge profiles in HAPI")


def run_all(args: argparse.Namespace) -> None:
    for step in (fetch, generate, select, do_import, verify):
        step(args)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("step", choices=["fetch", "generate", "select", "import", "verify", "all"])
    ap.add_argument("--fhir-base", default=os.environ.get("FHIR_BASE_URL", "http://localhost:8090/baseR4"))
    args = ap.parse_args()
    {"fetch": fetch, "generate": generate, "select": select, "import": do_import, "verify": verify, "all": run_all}[args.step](args)


if __name__ == "__main__":
    main()
