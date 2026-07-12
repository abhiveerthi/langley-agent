# Build context = repo root (so we can see both apps/api/ and packages/).
# In Render, leave "Root Directory" blank and set "Dockerfile path" to
# apps/api/Dockerfile. Locally, build with:
#   docker build -f apps/api/Dockerfile -t marcus-api .
FROM python:3.11-slim

WORKDIR /app

# ffmpeg: the Content Agent's audio path (faster-whisper local decode of the
# podcast source, and any yt-dlp remux) needs it. Harmless when the hosted
# OpenAI transcription backend is used instead.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# uv: fast resolver/installer for the lockfile in apps/api/.
RUN pip install --no-cache-dir uv

# Install deps first (own layer for cache reuse on code-only changes).
COPY apps/api/pyproject.toml apps/api/uv.lock ./
RUN uv sync --frozen --no-install-project

# Put the venv on PATH so subsequent commands (and the CMD) use it directly.
ENV PATH="/app/.venv/bin:$PATH"

# App code + shared monorepo packages.
COPY apps/api/app ./app
COPY apps/api/scripts ./scripts
COPY packages ./packages

# /app is on the import path so `from packages.* import ...` resolves.
ENV PYTHONPATH=/app

# Render injects $PORT; falls back to 8000 for `docker run` locally.
# Render's preDeployCommand runs `python /app/scripts/migrate.py` against
# DATABASE_URL before this CMD takes traffic — see ops/render-deploy.md.
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
