"""A minimal in-memory stand-in for the HAPI endpoints used by ingestion.

Used only by unit tests to exercise API control flow. It does NOT perform FHIR
validation; real validation is covered by tests/integration against HAPI.
"""

from __future__ import annotations

import copy
import itertools
import json

import httpx


class FakeHapi:
    def __init__(self, patients=("p1",), validate_errors=None, alter_on_store=None, down=False):
        self.patients = set(patients)
        self.validate_errors = validate_errors or []
        self.alter_on_store = alter_on_store
        self.down = down
        self.observations: dict[str, dict] = {}
        self._ids = itertools.count(1000)
        self.validate_calls: list[tuple[str, dict]] = []

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handle)

    def handle(self, req: httpx.Request) -> httpx.Response:
        if self.down:
            raise httpx.ConnectError("refused", request=req)
        path = req.url.path.removeprefix("/fhir/")
        if req.method == "GET" and path.startswith("Patient/"):
            pid = path.split("/", 1)[1]
            if pid in self.patients:
                return httpx.Response(200, json={"resourceType": "Patient", "id": pid})
            return httpx.Response(404, json={"resourceType": "OperationOutcome", "issue": []})
        if req.method == "POST" and path == "Observation/$validate":
            self.validate_calls.append((req.url.params.get("profile"), json.loads(req.content)))
            issues = [{"severity": "warning", "code": "informational", "diagnostics": "All observations should have a performer"}]
            issues += [{"severity": "error", "code": "processing", "diagnostics": d, "location": ["Observation"]} for d in self.validate_errors]
            return httpx.Response(412 if self.validate_errors else 200, json={"resourceType": "OperationOutcome", "issue": issues})
        if req.method == "POST" and path == "Observation":
            body = json.loads(req.content)
            oid = str(next(self._ids))
            stored = copy.deepcopy(body)
            stored["id"] = oid
            stored.setdefault("meta", {}).update(versionId="1", lastUpdated="2026-11-12T08:00:00Z")
            if self.alter_on_store:
                self.alter_on_store(stored)
            self.observations[oid] = stored
            return httpx.Response(201, json=stored)
        if req.method == "GET" and path.startswith("Observation/"):
            oid = path.split("/", 1)[1]
            if oid in self.observations:
                return httpx.Response(200, json=self.observations[oid])
            return httpx.Response(404, json={"resourceType": "OperationOutcome", "issue": []})
        return httpx.Response(400, json={"resourceType": "OperationOutcome", "issue": [{"severity": "error", "diagnostics": f"fake: {req.method} {path}"}]})
