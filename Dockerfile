# =============================================================================
# Amadeus AI - Multi-stage Dockerfile
# =============================================================================
# Stage 1: Builder (installs Python packages)
# Stage 2: Model Cache (downloads Whisper + Edge TTS voices)
# Stage 3: Production runtime (final slim image)
#
# TRADE-OFF:
#   - Without pre-baked Whisper: ~400MB image, 45-90s cold start (Railway)
#   - With pre-baked Whisper:    ~900MB image, <5s cold start
#   Baking into the image is STRONGLY recommended for Railway deployments.
# =============================================================================

# -----------------------------------------------------------------------------
# STAGE 1: Builder
# -----------------------------------------------------------------------------
FROM python:3.11-slim AS builder

WORKDIR /app

# Install build tools
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml ./

# Create virtual environment and install ALL extras
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir ".[voice,llm]"

# -----------------------------------------------------------------------------
# STAGE 2: Model Cache
# Pre-download Whisper 'small' model and Edge TTS voice list into the venv.
# This layer is cached by Docker — only re-runs if the base image changes.
# -----------------------------------------------------------------------------
FROM builder AS model_cache

ENV PATH="/opt/venv/bin:$PATH"

# Pre-bake faster-whisper 'small' model (~460MB)
# libgomp1 is required for faster-whisper CPU inference
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

RUN python -c "\
from faster_whisper import WhisperModel; \
print('Downloading Whisper small model...'); \
WhisperModel('small', device='cpu', compute_type='int8'); \
print('Whisper model pre-baked successfully.')" || \
    echo "WARNING: Whisper pre-bake failed (faster-whisper not installed). Will download at startup."

# Pre-fetch Edge TTS voice list (tiny HTTP call, cached in aiohttp)
RUN python -c "\
import asyncio, edge_tts; \
asyncio.run(edge_tts.list_voices()); \
print('Edge TTS voice list cached.')" || \
    echo "WARNING: Edge TTS voice list pre-fetch failed. Will fetch at runtime."

# -----------------------------------------------------------------------------
# STAGE 3: Production Runtime
# -----------------------------------------------------------------------------
FROM python:3.11-slim AS runtime

WORKDIR /app

# Runtime system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

# Copy pre-built venv (with models baked in) from the model_cache stage
COPY --from=model_cache /opt/venv /opt/venv
COPY --from=model_cache /root/.cache /root/.cache

ENV PATH="/opt/venv/bin:$PATH"

# Copy application source
COPY src/ ./src/
COPY pyproject.toml ./

# Create non-root user for security
RUN useradd --create-home --shell /bin/bash amadeus && \
    chown -R amadeus:amadeus /app && \
    mkdir -p /app/data && \
    chown amadeus:amadeus /app/data

USER amadeus

# Environment defaults (override via Railway environment variables)
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    ENV=production \
    DEBUG=false \
    API_HOST=0.0.0.0 \
    API_PORT=8000 \
    WHISPER_MODEL=small \
    WHISPER_DEVICE=cpu \
    WHISPER_COMPUTE_TYPE=int8 \
    DATABASE_URL=sqlite:///./data/amadeus.db

# Health check using the /health endpoint
HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')" || exit 1

EXPOSE 8000

# Run Alembic migrations then start the server
CMD ["sh", "-c", "python -m alembic upgrade head 2>/dev/null || true && uvicorn src.api.server:app --host 0.0.0.0 --port 8000 --workers 1"]
