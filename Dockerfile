# ── Stage 1: build the React frontend ───────────────────────────────────
# Outputs straight into ../static (see frontend/vite.config.ts outDir) —
# stage 2 copies that directory as-is, so this is the only place Node exists
# in the final image.
FROM node:20-slim AS frontend-build
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# ── Stage 2: the FastAPI app ─────────────────────────────────────────────
FROM python:3.11-slim

WORKDIR /app

# System deps: none required — all Python packages ship wheels for slim images.
# curl is included only to power the HEALTHCHECK below.
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY main.py .
COPY app/ ./app/
COPY redmine/ ./redmine/
COPY bitbucket/ ./bitbucket/
# main.py reads these at runtime (brief template + extraction prompts for the
# /brief-resources endpoint) — missing them 404s the Brief tab in the UI.
COPY docs/ ./docs/
COPY prompts/ ./prompts/
# Built frontend (index.html + hashed assets) — replaces the old static/ dir.
COPY --from=frontend-build /app/static ./static/

# SQLite data lives in its own directory, deliberately NOT inside app/ —
# mounting a volume over a source directory would shadow the code in it on
# every container start, freezing it at whatever was in the volume the first
# time it was created (bit us once already). AUTOSDLC_DB_PATH points
# database.py here; compose mounts a volume over just this directory.
RUN mkdir -p /app/data
ENV AUTOSDLC_DB_PATH=/app/data/autosdlc.db
VOLUME ["/app/data"]

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
