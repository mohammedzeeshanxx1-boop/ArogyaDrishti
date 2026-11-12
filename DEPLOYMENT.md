# Deployment

> Status: the Docker path below is **untested**. Container registries were unreachable from the build environment, so no container has been built or started (CHECKPOINTS.md, blocker B2). The application itself was tested against a local HAPI 5.7.0 server; see "Without Docker" below.

## Requirements

- Docker with Compose v2 or newer, and access to Docker Hub
- Free ports 8080 (web), 8000 (api), 8090 (HAPI FHIR); change them in `.env`
- About 2 GB of memory for HAPI FHIR (estimate, not measured)

## Start

```bash
cp .env.example .env          # change POSTGRES_PASSWORD
docker compose up -d --build
docker compose ps
docker compose --profile seed run --rm synthea-import   # loads the synthetic cohort
scripts/smoke.sh
```

| URL | What |
|---|---|
| http://localhost:8080 | Dashboard |
| http://localhost:8000/docs | API (OpenAPI) |
| http://localhost:8000/api/v1/status | Dependency status |
| http://localhost:8090/fhir/metadata | HAPI FHIR CapabilityStatement |

Startup order: `database` (healthy) → `hapi-fhir` → `api` → `web`. HAPI has no container healthcheck, so the API starts before HAPI is ready and reports it as `unreachable` until it responds.

## Without Docker

`infra/hapi-local/run.sh` runs the official HAPI FHIR 5.7.0 CLI server (Java 11) on `http://localhost:8090/baseR4` with an on-disk Derby database. Read `infra/hapi-local/README.md` first: the script patches type annotations in 10 Guava classes of a copy of the jar so the server can start. Point the API at it with `FHIR_BASE_URL=http://localhost:8090/baseR4` and load the cohort with `python3 services/synthea/pipeline.py all --fhir-base http://localhost:8090/baseR4`.

## Configuration

All settings are in `.env`; see `.env.example`. `POSTGRES_PASSWORD` is required and Compose refuses to start without it.

## Data and persistence

| Volume | Holds | Survives `docker compose down` |
|---|---|---|
| `hapi-db-data` | PostgreSQL data for HAPI FHIR (all FHIR resources) | yes |
| `api-data` | SQLite file with app-only event metadata (ingestion log) | yes |
| `synthea-cache` | Downloaded Synthea jar | yes |

`docker compose down -v` deletes both.

## If HAPI does not start

Things to check first, since none of this has been run:

1. The image tag in `HAPI_IMAGE` exists; try a newer `hapiproject/hapi` tag.
2. `docker compose logs hapi-fhir` for datasource or Hibernate dialect errors.
3. If Synthea import fails with id errors, confirm `hapi.fhir.client_id_strategy: ALPHANUMERIC` took effect. The settings are passed as environment variables in `docker-compose.yml`; if the image ignores them, mount an `application.yaml` instead.

## Security notes

- Local demonstration only: no authentication, no TLS, HAPI is exposed on the host.
- Do not load real patient data. The project uses Synthea synthetic patients and de-identified public research recordings only.
