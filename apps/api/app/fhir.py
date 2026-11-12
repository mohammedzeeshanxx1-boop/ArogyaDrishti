"""HAPI FHIR access: connectivity probe and a small async REST client."""

from __future__ import annotations

from dataclasses import dataclass

import httpx

FHIR_JSON = "application/fhir+json"


async def probe_fhir(base_url: str, timeout: float, transport: httpx.AsyncBaseTransport | None = None) -> dict:
    """Read [base]/metadata and report the FHIR version the server declares."""
    url = f"{base_url}/metadata"
    try:
        async with httpx.AsyncClient(timeout=timeout, transport=transport) as client:
            resp = await client.get(url, headers={"Accept": FHIR_JSON})
    except httpx.HTTPError as exc:
        return {"status": "unreachable", "url": url, "detail": type(exc).__name__}
    if resp.status_code != 200:
        return {"status": "error", "url": url, "detail": f"HTTP {resp.status_code}"}
    try:
        body = resp.json()
    except ValueError:
        return {"status": "error", "url": url, "detail": "non-JSON response"}
    if body.get("resourceType") != "CapabilityStatement":
        return {"status": "error", "url": url, "detail": "not a CapabilityStatement"}
    fhir_version = body.get("fhirVersion")
    return {
        "status": "ok",
        "url": url,
        "fhirVersion": fhir_version,
        # R4 is the 4.0.x line; anything else fails the PS-03 R4 requirement.
        "isR4": isinstance(fhir_version, str) and fhir_version.startswith("4.0"),
        "software": (body.get("software") or {}).get("name"),
    }


class FhirUnavailable(Exception):
    """HAPI could not be reached or answered with a server error."""


@dataclass
class FhirResponse:
    status: int
    body: dict
    headers: httpx.Headers


class FhirClient:
    def __init__(self, base_url: str, timeout: float, transport: httpx.AsyncBaseTransport | None = None):
        self.base_url = base_url.rstrip("/")
        self._client = httpx.AsyncClient(timeout=timeout, transport=transport, headers={"Accept": FHIR_JSON})

    async def aclose(self) -> None:
        await self._client.aclose()

    async def request(self, method: str, path: str, *, json: dict | None = None, params: dict | None = None) -> FhirResponse:
        url = path if path.startswith(("http://", "https://")) else f"{self.base_url}/{path.lstrip('/')}"
        headers = {"Content-Type": FHIR_JSON} if json is not None else None
        try:
            resp = await self._client.request(method, url, json=json, params=params, headers=headers)
        except httpx.HTTPError as exc:
            raise FhirUnavailable(f"{type(exc).__name__} contacting FHIR server") from exc
        if resp.status_code >= 500:
            raise FhirUnavailable(f"FHIR server answered HTTP {resp.status_code}")
        try:
            body = resp.json() if resp.content else {}
        except ValueError as exc:
            raise FhirUnavailable("FHIR server returned non-JSON") from exc
        return FhirResponse(resp.status_code, body, resp.headers)

    async def read(self, resource_type: str, rid: str) -> dict | None:
        r = await self.request("GET", f"{resource_type}/{rid}")
        if r.status in (404, 410):
            return None
        if r.status != 200:
            raise FhirUnavailable(f"read {resource_type}/{rid} -> HTTP {r.status}")
        return r.body

    async def create(self, resource: dict) -> FhirResponse:
        return await self.request("POST", resource["resourceType"], json=resource)

    async def validate(self, resource: dict, profile: str) -> dict:
        """Run the server's $validate against a profile. Returns the OperationOutcome.

        HAPI 5.7 was observed to ignore the ``profile`` URL parameter and to enforce
        only profiles declared in ``meta.profile``, so the profile is always added
        to meta.profile of the copy sent for validation. The parameter is still sent
        for servers that honor it.
        """
        body = dict(resource)
        meta = dict(body.get("meta", {}))
        meta["profile"] = list(dict.fromkeys([*meta.get("profile", []), profile]))
        body["meta"] = meta
        r = await self.request("POST", f"{resource['resourceType']}/$validate", json=body, params={"profile": profile})
        if r.body.get("resourceType") != "OperationOutcome":
            raise FhirUnavailable(f"$validate returned HTTP {r.status} without an OperationOutcome")
        return r.body

    async def search(self, resource_type: str, params: dict, limit: int = 1000) -> list[dict]:
        """Search and follow next links; returns matching resources (search mode 'match' and 'include')."""
        out: list[dict] = []
        r = await self.request("GET", resource_type, params=params)
        while True:
            if r.status != 200 or r.body.get("resourceType") != "Bundle":
                raise FhirUnavailable(f"search {resource_type} -> HTTP {r.status}")
            out += [e["resource"] for e in r.body.get("entry", []) if "resource" in e]
            nxt = next((l["url"] for l in r.body.get("link", []) if l.get("relation") == "next"), None)
            if not nxt or len(out) >= limit:
                return out[:limit]
            r = await self.request("GET", nxt)

    async def count(self, resource_type: str, params: dict) -> int:
        r = await self.request("GET", resource_type, params={**params, "_summary": "count"})
        if r.status != 200:
            raise FhirUnavailable(f"count {resource_type} -> HTTP {r.status}")
        return int(r.body.get("total", 0))


def outcome(issues: list[dict]) -> dict:
    """A FHIR R4 OperationOutcome."""
    return {"resourceType": "OperationOutcome", "issue": issues}


def outcome_issue(severity: str, code: str, diagnostics: str, expression: str | None = None) -> dict:
    issue = {"severity": severity, "code": code, "diagnostics": diagnostics}
    if expression:
        issue["expression"] = [expression]
    return issue


def summarize_outcome(oo: dict) -> dict:
    """Counts by severity, ignoring HAPI's informational 'no issues' entries."""
    issues = [i for i in oo.get("issue", []) if i.get("severity") in ("fatal", "error", "warning")]
    return {
        "errors": sum(i["severity"] in ("fatal", "error") for i in issues),
        "warnings": sum(i["severity"] == "warning" for i in issues),
        "issues": [
            {"severity": i["severity"], "location": (i.get("location") or i.get("expression") or [None])[0], "diagnostics": i.get("diagnostics")}
            for i in issues
        ],
    }
