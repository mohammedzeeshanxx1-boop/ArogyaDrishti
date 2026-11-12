# Local HAPI FHIR fallback (no Docker)

**Supported path:** `docker compose up`, which runs the official `hapiproject/hapi` image on PostgreSQL.

**This fallback** runs the official HAPI FHIR **5.7.0** CLI `run-server` command, a real HAPI JPA server with an on-disk H2 database. It was used to produce the C1 evidence because the build environment could not pull container images (Docker Hub, GHCR, Quay, ECR and Maven Central were all denied by its network policy; GitHub release downloads were allowed).

```bash
HAPI_JAVA=/path/to/java infra/hapi-local/run.sh   # Java 11, 17 or 21; http://localhost:8090/baseR4
FHIR_BASE_URL=http://localhost:8090/baseR4 uvicorn app.main:app  # in apps/api
```

## The patch, and why

Out of the box, `run-server` fails on both Java 11 and Java 21 with `ArrayIndexOutOfBoundsException` in `org.jboss.jandex.Indexer`. Hibernate scans the whole 550 MB CLI jar, and the bundled Jandex cannot parse 10 Guava classes that carry Checker Framework type-use annotations.

`run.sh` (1) verifies the official zip and jar by SHA-256, (2) removes only the type-use annotation attributes from the 10 classes listed in `patch-classes.txt` with the pure-Python `strip_type_annotations.py` (no JDK or `javac` needed), and (3) writes the patched copy `hapi-fhir-cli-patched.jar`. Method bytecode is not changed. Verified 2026-11-12: the Jandex scan (`Scan.java`, optional, needs a JDK) reports 0 failures of 92,335 classes, and HAPI starts and stores data on Java 11, 17 and 21 (including the PyPI `jdk4py` Java 17 runtime that `scripts/dev/setup.sh` installs on macOS).

Observed on 2026-11-12: 92,335 classes scanned, 10 failed before the patch and 0 after. HAPI then served `CapabilityStatement` with `fhirVersion 4.0.1` and software `HAPI FHIR Server 5.7.0`.

## Known differences from the Docker image

- HAPI 5.7.0 instead of the newer image tag; base URL `/baseR4` instead of `/fhir`.
- H2 file database instead of PostgreSQL. Persistence was verified across a restart of this server, not for the PostgreSQL volume.
- This build's `$validate` ignores the `?profile=` parameter and enforces only profiles declared in `meta.profile`. The API always declares the profile, so it is correct on either server.
