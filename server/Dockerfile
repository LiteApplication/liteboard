# syntax=docker/dockerfile:1
# Build context is the repository root (see docker-compose.yml).

# --- Stage 1: build the Vue SPA ------------------------------------------- #
FROM node:22-slim AS web
WORKDIR /web
COPY web/package.json web/package-lock.json* ./
RUN npm install
COPY web/ ./
RUN npm run build

# --- Stage 2: python runtime ---------------------------------------------- #
FROM python:3.12-slim AS runtime
WORKDIR /app

COPY server/pyproject.toml ./
COPY server/liteboard ./liteboard
# Installs declared dependencies (and the package) into site-packages. At
# runtime we import from /app/liteboard (cwd), which also carries the daemon
# source added below.
RUN pip install --no-cache-dir .

# Ship the canonical daemon source so the server can serve signed self-updates.
COPY daemon/liteboard_daemon.py daemon/protocol.py daemon/metrics.py \
     daemon/netinspect.py daemon/selfupdate.py daemon/dockerapi.py daemon/images.py \
     ./liteboard/daemon_dist/src/

# Built SPA served as static files.
COPY --from=web /web/dist ./static

ENV LITEBOARD_STATIC_DIR=/app/static \
    PYTHONUNBUFFERED=1

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=3s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/healthz',timeout=2).status==200 else 1)"

CMD ["uvicorn", "liteboard.main:app", "--host", "0.0.0.0", "--port", "8000"]
