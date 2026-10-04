# syntax=docker/dockerfile:1.7
#
# OneAquaHealth backend image for Cloud Run (docs/deployment.md).
#
# Build (the three prebuilt SQLite stores come from an additional, named build context; see
# scripts/stage_deploy_stores.py). Cloud Run needs linux/amd64:
#
#   docker buildx build --platform linux/amd64 --build-context stores=<STAGE_DIR> -t <IMAGE> .
#
# Design notes
# - Two stages: the builder installs the RUNTIME-only, hash-pinned dependencies (a strict subset of
#   requirements-lock.txt, derived by scripts/runtime_requirements.py) into a virtual environment; the runtime
#   stage copies that environment, the source and the stores. No compiler, no pip cache and no development
#   packages reach the final image.
# - The application is NOT pip-installed: src/oah/paths.py finds the project root by walking up to pyproject.toml,
#   so the source tree is kept as /app/pyproject.toml + /app/src and put on PYTHONPATH. The i18n strings and the
#   denylists are JSON files inside src/oah, so they ship with the source. Nothing from docs/, fixtures/,
#   reference/ or ig/ is needed at run time, and no .env file is ever copied (see .dockerignore).
# - The three stores (Waterbase, bathing-water classification, bathing-water samples; about 260 MiB together) are
#   baked in (read-only, 0444): the image is the single versioned artifact, with no storage mount to fail at
#   start-up. The environment variables below point the app at them (they must be absolute paths).
# - The external-context package (src/oah/external) makes outbound https calls to three allow-listed hosts at run
#   time and reads src/oah/external/data/gbif_taxa.json, which ships with the source tree (COPY src). No setting is
#   needed here: OAH_EXTERNAL_* and OAH_CONTACT_URL are optional and set in the service file.
# - ONE uvicorn worker, on purpose: the rate limiter, the daily LLM caps, the response caches and the audit hash
#   chain live in process memory. A second worker (or instance) would split those counters and double the budgets.
# - Runs as an unprivileged user. Cloud Run's root filesystem is writable but in memory and ephemeral: the app's
#   data directory (audit log files, review database, caches) is /data/runtime and is lost when the instance
#   restarts; the audit records are also written to standard output, where Cloud Logging keeps them.

# Base image pinned by digest: a rebuild gets the same bytes, and a new base patch is adopted on purpose (refresh
# procedure: docs/predeploy_checklist.md, section 5). Human-readable tag: python:3.12-slim-bookworm. The digest below
# is the one the last Cloud Build used for that tag (taken from its build log, not re-resolved here).
ARG PYTHON_IMAGE=python:3.12-slim-bookworm@sha256:54c85f3c47607a77f32adec749d3c81d1348bf25833671f512b26a9b6d778cb3

FROM ${PYTHON_IMAGE} AS builder
ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1
WORKDIR /build
COPY pyproject.toml requirements-lock.txt ./
COPY scripts/runtime_requirements.py ./
RUN python runtime_requirements.py --lock requirements-lock.txt --pyproject pyproject.toml --output requirements-runtime.txt \
    && python -m venv /venv \
    && /venv/bin/python -m pip install --require-hashes --no-deps -r requirements-runtime.txt

FROM ${PYTHON_IMAGE} AS runtime
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH=/venv/bin:$PATH \
    PYTHONPATH=/app/src \
    PORT=8080 \
    OAH_DATA_DIR=/data/runtime \
    OAH_WATERBASE_STORE=/data/stores/waterbase_icm_2026.sqlite \
    OAH_BATHING_WATER_STORE=/data/stores/bathing_water_2025.sqlite \
    OAH_BATHING_SAMPLES_STORE=/data/stores/bathing_samples_discodata.sqlite

RUN groupadd --system --gid 10001 oah \
    && useradd --system --uid 10001 --gid oah --no-create-home --shell /usr/sbin/nologin oah \
    && mkdir -p /data/stores /data/runtime \
    && chown oah:oah /data/runtime

COPY --from=builder /venv /venv
WORKDIR /app
COPY pyproject.toml ./
COPY src ./src
COPY scripts/container_healthcheck.py ./container_healthcheck.py
RUN python -m compileall -q /app/src

# The prebuilt stores and their manifest (sizes, SHA-256, schema versions, build dates). The additional build
# context "stores" is required; without --build-context the build stops here, which is intended.
COPY --from=stores --chmod=0444 waterbase_icm_2026.sqlite bathing_water_2025.sqlite bathing_samples_discodata.sqlite manifest.json /data/stores/

USER oah
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 CMD ["python", "/app/container_healthcheck.py"]

# exec: uvicorn is PID 1 and receives SIGTERM directly. Cloud Run allows 10 s between SIGTERM and SIGKILL, so the
# graceful-shutdown wait is 8 s (a longer chat request in flight is cut). --no-proxy-headers: the application's own
# oah.api.client_ip decides which X-Forwarded-For entries to believe (OAH_TRUSTED_PROXIES), uvicorn must not rewrite
# the client address as well. No --reload.
CMD ["sh", "-c", "exec uvicorn oah.api.app:app --host 0.0.0.0 --port \"${PORT:-8080}\" --workers 1 --no-proxy-headers --no-server-header --timeout-graceful-shutdown 8 --log-level info"]
