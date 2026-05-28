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

COPY pyproject.toml README.md ./

# Create virtual environment and install ALL extras
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir .

# -----------------------------------------------------------------------------
# STAGE 2: Model Cache
# Pre-download Whisper 'small' model and Edge TTS voice list into the venv.
# This layer is cached by Docker — only re-runs if the base image changes.
# -----------------------------------------------------------------------------
FROM builder AS model_cache

ENV PATH="/opt/venv/bin:$PATH"

# (model_cache stage: add any pre-bake steps here when packages are added to pyproject.toml)

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
COPY pyproject.toml alembic.ini ./
# Only copy the example env — NEVER copy .env, .env.prod, .env.staging into the image.
# Real secrets are injected via Railway/Docker environment variables at runtime.
COPY .env.example ./
COPY alembic/ ./alembic/


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
    DATABASE_URL=postgresql://postgres:postgres@postgres:5432/amadeus

# Health check using the /health endpoint
HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')" || exit 1

EXPOSE 8000

CMD ["uvicorn", "src.transports.fastapi_transport:app", \
     "--host", "0.0.0.0", "--port", "8000", \
     "--workers", "1", "--log-level", "info"]
