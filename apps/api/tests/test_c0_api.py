"""C0 API tests: startup, meta, dependency status, WebSocket transport."""

from __future__ import annotations

import httpx
import pytest
from fastapi.testclient import TestClient

from app.config import DISCLAIMER, Settings
from app.main import create_app


def make_client(tmp_path, handler) -> TestClient:
    settings = Settings(
        fhir_base_url="http://hapi.test/fhir",
        fhir_timeout_seconds=1,
        sqlite_path=str(tmp_path / "app.db"),
        cors_origins=("http://localhost:5173",),
    )
    return TestClient(create_app(settings, fhir_transport=httpx.MockTransport(handler)))


def capability(version: str):
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/fhir/metadata"
        return httpx.Response(
            200,
            json={"resourceType": "CapabilityStatement", "fhirVersion": version, "software": {"name": "HAPI FHIR Server"}},
        )

    return handler


def refuse(request: httpx.Request) -> httpx.Response:
    raise httpx.ConnectError("refused", request=request)


def test_health(tmp_path):
    with make_client(tmp_path, refuse) as client:
        assert client.get("/health").json() == {"status": "ok"}


def test_meta_carries_brand_and_disclaimer(tmp_path):
    with make_client(tmp_path, refuse) as client:
        body = client.get("/api/v1/meta").json()
    assert body["name"] == "Arogya Drishti"
    assert body["tagline"] == "See the warning signs before they become emergencies."
    assert body["disclaimer"] == DISCLAIMER == "Clinical decision support only. Not for medical diagnosis."
    assert body["checkpoint"] == "C0"


def test_status_reports_r4_server(tmp_path):
    with make_client(tmp_path, capability("4.0.1")) as client:
        services = client.get("/api/v1/status").json()["services"]
    assert services["api"]["status"] == "ok"
    assert services["fhir"]["status"] == "ok"
    assert services["fhir"]["fhirVersion"] == "4.0.1"
    assert services["fhir"]["isR4"] is True
    assert services["eventStore"] == {"status": "ok", "schemaVersion": 1}


def test_status_flags_non_r4_server(tmp_path):
    with make_client(tmp_path, capability("5.0.0")) as client:
        fhir = client.get("/api/v1/status").json()["services"]["fhir"]
    assert fhir["status"] == "ok" and fhir["isR4"] is False


def test_status_does_not_pretend_fhir_is_up(tmp_path):
    with make_client(tmp_path, refuse) as client:
        resp = client.get("/api/v1/status")
    assert resp.status_code == 200
    fhir = resp.json()["services"]["fhir"]
    assert fhir["status"] == "unreachable"
    assert "fhirVersion" not in fhir


@pytest.mark.parametrize(
    "response",
    [httpx.Response(503), httpx.Response(200, text="<html>"), httpx.Response(200, json={"resourceType": "Bundle"})],
)
def test_status_rejects_bad_metadata(tmp_path, response):
    with make_client(tmp_path, lambda request: response) as client:
        assert client.get("/api/v1/status").json()["services"]["fhir"]["status"] == "error"


def test_websocket_heartbeat(tmp_path):
    with make_client(tmp_path, refuse) as client, client.websocket_connect("/ws/heartbeat") as ws:
        assert ws.receive_json()["type"] == "hello"
        ws.send_text("ping")
        assert ws.receive_json()["type"] == "pong"
        ws.send_text("anything-else")
        assert ws.receive_json()["type"] == "error"
