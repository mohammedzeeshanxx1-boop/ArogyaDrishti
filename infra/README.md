# infra

- `nginx/default.conf`: config for the `web` container. Serves the built dashboard and proxies `/api/`, `/health` and `/ws/` to the `api` service.

HAPI FHIR is configured through environment variables in `docker-compose.yml`.
