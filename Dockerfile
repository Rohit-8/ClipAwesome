# syntax=docker/dockerfile:1

# ---------- 1. Build the web UI ----------
FROM node:24-bookworm-slim AS web
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY web/ ./
RUN npm run build

# ---------- 2. Runtime ----------
FROM python:3.13-slim AS runtime

# true = include local Whisper transcription (adds ~150 MB + models downloaded on first use)
ARG INSTALL_TRANSCRIBE=true

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    HF_HUB_DISABLE_SYMLINKS_WARNING=1 \
    CLIPAWESOME_HOST=0.0.0.0 \
    CLIPAWESOME_PORT=8765 \
    CLIPAWESOME_DATA=/data \
    CLIPAWESOME_WEB_DIST=/app/web/dist \
    CLIPAWESOME_ALLOW_LOCAL_PATH=false

WORKDIR /app

# Fonts for burned-in captions (libass finds them via fontconfig): DejaVu for Latin scripts, Lohit for Devanagari (Hindi).
RUN apt-get update \
 && apt-get install -y --no-install-recommends fontconfig fonts-dejavu-core fonts-lohit-deva \
 && rm -rf /var/lib/apt/lists/*

# JavaScript runtime yt-dlp uses to solve YouTube's player challenges.
COPY --from=denoland/deno:bin /deno /usr/local/bin/deno

# Dependencies in their own layer: code-only changes reuse it.
COPY backend/pyproject.toml /tmp/build/pyproject.toml
RUN mkdir -p /tmp/build/clipawesome \
 && touch /tmp/build/clipawesome/__init__.py \
 && if [ "$INSTALL_TRANSCRIBE" = "true" ]; then EXTRA="[transcribe]"; else EXTRA=""; fi \
 && pip install "/tmp/build${EXTRA}" \
 && pip uninstall -y clipawesome \
 && rm -rf /tmp/build

COPY backend/pyproject.toml /tmp/build/pyproject.toml
COPY backend/clipawesome /tmp/build/clipawesome
RUN pip install --no-deps /tmp/build && rm -rf /tmp/build

COPY --from=web /web/dist /app/web/dist

RUN useradd --uid 10001 --create-home --home-dir /home/app --shell /usr/sbin/nologin app \
 && mkdir -p /data \
 && chown app:app /data

USER app
VOLUME ["/data"]
EXPOSE 8765

HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
  CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8765/api/healthz', timeout=4)"]

CMD ["python", "-m", "clipawesome"]
