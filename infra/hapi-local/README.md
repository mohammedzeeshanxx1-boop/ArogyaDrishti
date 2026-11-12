# Local HAPI FHIR fallback (no Docker)

**Supported path:** `docker compose up`, which runs the official `hapiproject/hapi` image on PostgreSQL.

**This fallback** runs the official HAPI FHIR **5.7.0** CLI `run-server` command, a real HAPI JPA server with an on-disk Derby database. It was used to produce the C1 evidence because the build environment could not pull container images (Docker Hub, GHCR, Quay, ECR and Maven Central were all denied by its network policy; GitHub release downloads were allowed).

```bash
JAVA11=/path/to/java11/bin/java infra/hapi-local/run.sh          # http://localhost:8090/baseR4
FHIR_BASE_URL=http://localhost:8090/baseR4 uvicorn app.main:app  # in apps/api
```

## The patch, and why

Out of the box, `run-server` fails on both Java 11 and Java 21 with `ArrayIndexOutOfBoundsException` in `org.jboss.jandex.Indexer`. Hibernate scans the whole 550 MB CLI jar, and the bundled Jandex cannot parse 10 Guava classes that carry Checker Framework type-use annotations.

`run.sh` (1) verifies the official zip and jar by SHA-256, (2) lists the classes Jandex cannot index (`Scan.java`), (3) removes only the type-use annotation attributes from those classes (`Strip.java`, using the ASM copy inside the jar), and (4) re-scans and requires `bad=0`. Method bytecode is not changed. The original jar is kept; the patched copy is `hapi-fhir-cli-patched.jar`.

Observed on 2026-11-12: 92,335 classes scanned, 10 failed before the patch and 0 after. HAPI then served `CapabilityStatement` with `fhirVersion 4.0.1` and software `HAPI FHIR Server 5.7.0`.

## Known differences from the Docker image

- HAPI 5.7.0 instead of the newer image tag; base URL `/baseR4` instead of `/fhir`.
- Derby instead of PostgreSQL. Persistence was verified across a restart of this server, not for the PostgreSQL volume.
- This build's `$validate` ignores the `?profile=` parameter and enforces only profiles declared in `meta.profile`. The API always declares the profile, so it is correct on either server.
