"""Minimal HAPI FHIR connectivity probe (C0).

Reads the server CapabilityStatement at ``[base]/metadata`` and reports the
FHIR version the server declares. Ingestion and storage arrive at C1.
"""

from __future__ import annotations

import httpx


async def probe_fhir(base_url: str, timeout: float, transport: httpx.AsyncBaseTransport | None = None) -> dict:
    url = f"{base_url}/metadata"
    try:
        async with httpx.AsyncClient(timeout=timeout, transport=transport) as client:
            resp = await client.get(url, headers={"Accept": "application/fhir+json"})
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
