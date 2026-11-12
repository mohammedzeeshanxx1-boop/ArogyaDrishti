# One-shot Synthea generate + import job (docker compose --profile seed run --rm synthea-import).
# UNTESTED: container images could not be pulled in the C1 build environment.
FROM eclipse-temurin:21-jre
RUN apt-get update && apt-get install -y --no-install-recommends python3 ca-certificates && rm -rf /var/lib/apt/lists/*
WORKDIR /srv/synthea
COPY synthea.lock.json pipeline.py ./
ENTRYPOINT ["python3", "pipeline.py"]
CMD ["all"]
