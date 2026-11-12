"""C0 repository-level checks: required layout and docker-compose contract."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent

REQUIRED_PATHS = [
    "apps/web",
    "apps/api",
    "services/synthea",
    "services/bidmc",
    "infra",
    "tests",
    "scripts",
    "docs",
    "docker-compose.yml",
    ".env.example",
    "README.md",
    "CHECKPOINTS.md",
    "EVALUATION.md",
    "DEPLOYMENT.md",
]


@pytest.fixture(scope="module")
def compose() -> dict:
    return yaml.safe_load((ROOT / "docker-compose.yml").read_text())


@pytest.mark.parametrize("rel", REQUIRED_PATHS)
def test_required_path_exists(rel):
    assert (ROOT / rel).exists(), f"missing {rel}"


def test_default_stack_is_exactly_the_four_services(compose):
    default = {n for n, svc in compose["services"].items() if not svc.get("profiles")}
    assert default == {"web", "api", "hapi-fhir", "database"}


def test_synthea_import_is_an_opt_in_job_pointing_at_hapi(compose):
    job = compose["services"]["synthea-import"]
    assert job["profiles"] == ["seed"]
    assert job["environment"]["FHIR_BASE_URL"] == "http://hapi-fhir:8080/fhir"


def test_hapi_accepts_client_assigned_ids_for_synthea_put(compose):
    assert compose["services"]["hapi-fhir"]["environment"]["hapi.fhir.client_id_strategy"] == "ALPHANUMERIC"


def test_synthea_inputs_are_pinned():
    import json
    lock = json.loads((ROOT / "services/synthea/synthea.lock.json").read_text())
    assert lock["synthea"]["version"].startswith("v")
    assert re.fullmatch(r"[0-9a-f]{64}", lock["synthea"]["sha256"])
    assert isinstance(lock["run"]["seed"], int) and lock["selection"]["minimumCohort"] >= 5


def test_hapi_is_r4_and_persists_to_postgres(compose):
    env = compose["services"]["hapi-fhir"]["environment"]
    assert env["hapi.fhir.fhir_version"] == "R4"
    assert env["spring.datasource.url"].startswith("jdbc:postgresql://database:")
    db_volumes = compose["services"]["database"]["volumes"]
    assert any(v.endswith(":/var/lib/postgresql/data") for v in db_volumes)
    assert "hapi-db-data" in compose["volumes"]


def test_api_points_at_hapi_and_keeps_sqlite_on_a_volume(compose):
    api = compose["services"]["api"]
    assert api["environment"]["FHIR_BASE_URL"] == "http://hapi-fhir:8080/fhir"
    assert api["environment"]["APP_SQLITE_PATH"].startswith("/data/")
    assert "api-data:/data" in api["volumes"]


def test_startup_order(compose):
    s = compose["services"]
    assert "database" in s["hapi-fhir"]["depends_on"]
    assert "hapi-fhir" in s["api"]["depends_on"]
    assert "api" in s["web"]["depends_on"]


def test_env_example_covers_every_compose_variable():
    used = set(re.findall(r"\$\{([A-Z0-9_]+)", (ROOT / "docker-compose.yml").read_text()))
    declared = {
        line.split("=", 1)[0]
        for line in (ROOT / ".env.example").read_text().splitlines()
        if line and not line.startswith("#")
    }
    assert used <= declared, f"undeclared in .env.example: {sorted(used - declared)}"


def test_no_secrets_or_env_file_committed():
    assert not (ROOT / ".env").exists() or ".env" in (ROOT / ".gitignore").read_text().split()


def test_disclaimer_is_identical_in_api_and_web():
    text = "Clinical decision support only. Not for medical diagnosis."
    assert text in (ROOT / "apps/api/app/config.py").read_text()
    assert text in (ROOT / "apps/web/src/brand.ts").read_text()
