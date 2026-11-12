# Deployment

> Status: the Docker path below is **untested**. Docker Hub was unreachable from the environment where C0 was built, so no container has been built or started. See CHECKPOINTS.md, blocker B2.

## Requirements

- Docker with Compose v2 or newer, and access to Docker Hub
- Free ports 8080 (web), 8000 (api), 8090 (HAPI FHIR); change them in `.env`
- About 2 GB of memory for HAPI FHIR (estimate, not measured)

## Start

```bash
cp .env.example .env          # change POSTGRES_PASSWORD
docker compose up -d --build
docker compose ps
scripts/smoke.sh
```

| URL | What |
|---|---|
| http://localhost:8080 | Dashboard |
| http://localhost:8000/docs | API (OpenAPI) |
| http://localhost:8000/api/v1/status | Dependency status |
| http://localhost:8090/fhir/metadata | HAPI FHIR CapabilityStatement |

Startup order: `database` (healthy) → `hapi-fhir` → `api` → `web`. HAPI has no container healthcheck, so the API starts before HAPI is ready and reports it as `unreachable` until it responds.

## Configuration

All settings are in `.env`; see `.env.example`. `POSTGRES_PASSWORD` is required and Compose refuses to start without it.

## Data and persistence

| Volume | Holds | Survives `docker compose down` |
|---|---|---|
| `hapi-db-data` | PostgreSQL data for HAPI FHIR (all FHIR resources) | yes |
| `api-data` | SQLite file with app-only event metadata | yes |

`docker compose down -v` deletes both.

## If HAPI does not start

Things to check first, since none of this has been run:

1. The image tag in `HAPI_IMAGE` exists; try a newer `hapiproject/hapi` tag.
2. `docker compose logs hapi-fhir` for datasource or Hibernate dialect errors. The settings are passed as environment variables in `docker-compose.yml`; if the image ignores them, mount an `application.yaml` instead.

## Security notes

- Local demonstration only: no authentication, no TLS, HAPI is exposed on the host.
- Do not load real patient data. The project uses Synthea synthetic patients and de-identified public research recordings only.
