# syntax=docker/dockerfile:1
#
# One image, three process types (Spec §15 Factors I, V, VIII): `web`, `ingest-worker` and one-off
# `vsir` admin commands all run from this image and the same release. Build and release are
# strictly separated — the image carries no configuration and no secret; a release is image + env.
#
#   docker build -t vsir:$VSIR_RELEASE_ID -f backend/Dockerfile backend
#
# Tag with the release id, never `latest` (§15.2). Run read-only, with a writable tmpfs for the
# raster cache — rasters are re-rendered on demand and are never a source of truth (§4.2):
#
#   docker run --read-only --tmpfs /tmp:rw,noexec,nosuid,size=512m --env-file .env vsir:$VSIR_RELEASE_ID
#
# The base is pinned by digest, not by tag: `python:3.11-slim` moves, a digest does not, and
# Factor II wants the exact minor pinned by the image (§4.2).
ARG PYTHON_BASE=python:3.11-slim@sha256:9534e5a8e315485d4061ed659af0fd78a284c015f9b73661b41d6bab25604534

# ── build ────────────────────────────────────────────────────────────────────────────────────────
# Wheels are resolved and installed here so that no build tooling survives into the runtime layer.
FROM ${PYTHON_BASE} AS build

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /src

# requirements.lock is the transitive, hash-pinned resolution of requirements.txt (Factor II).
# --require-hashes makes a substituted artefact a build failure rather than a runtime surprise.
COPY requirements.lock ./
RUN python -m venv /opt/venv \
 && /opt/venv/bin/pip install --no-cache-dir --require-hashes -r requirements.lock

COPY pyproject.toml requirements.txt ./
COPY vsir ./vsir
RUN /opt/venv/bin/pip install --no-cache-dir --no-deps .

# ── runtime ──────────────────────────────────────────────────────────────────────────────────────
FROM ${PYTHON_BASE} AS runtime

LABEL org.opencontainers.image.title="vsir" \
      org.opencontainers.image.description="Vision segmentation, index and retrieval (POC Part B)"

# PYTHONUNBUFFERED keeps the JSON event stream flowing to stdout as it happens (§15 Factor XI).
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/opt/venv/bin:$PATH" \
    TMPDIR=/tmp

# Non-root, and no login shell: nothing in this image needs to write to its own filesystem, which
# is what makes `--read-only` viable (§15 Factor V).
RUN useradd --uid 10001 --no-create-home --shell /usr/sbin/nologin vsir

COPY --from=build /opt/venv /opt/venv

# The document store's mount point, created here and owned by the runtime user — and it has to be
# in the image rather than only in `docker-compose.yml`. Docker initialises a **fresh named volume**
# from whatever is at its mount point in the image, ownership included; with nothing there it
# creates the directory root-owned, and a container running as uid 10001 then cannot write to its
# own volume. Found by running the stack: the first seed refused `document_store_unwritable` at
# step 02, correctly and unhelpfully. Rasters are still never persisted (§4.2) — this is where
# the SOURCE documents they are re-rendered from live (U029), and it is the one writable path
# outside `/tmp` that `--read-only` allows.
RUN mkdir -p /srv/documents && chown 10001:10001 /srv/documents

USER 10001
WORKDIR /srv

# No configuration is baked in: every value arrives as an environment variable and boot refuses a
# missing one (§4.3, §15 Factor III). The default command is the boot self-check, because at M0
# there is no server yet — `web` overrides it with `serve` from U014 onwards.
ENTRYPOINT ["vsir"]
CMD ["doctor"]
