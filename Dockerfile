# =============================================================================
# Amadeus AI — Multi-stage Dockerfile (reproducible, ONNX-only runtime)
# =============================================================================
# Stage 1: Builder   — installs locked dependencies into /opt/venv via uv.
# Stage 2: Artifacts — builds the router artifacts (ONNX embedder + numpy SVM)
#                      with a throwaway CPU-only torch/sklearn toolchain.
# Stage 3: Production runtime — slim image with the venv, source and artifacts.
#
# REPRODUCIBILITY / SUPPLY CHAIN:
#   Dependencies are installed with `uv sync --frozen`, which installs EXACTLY
#   the versions in uv.lock (the same set CI tests and `pip-audit` vets). The
#   previous `pip install .` re-resolved `>=` ranges at build time, so the image
#   could ship untested/unaudited versions. Never reintroduce that.
#
# MEMORY BUDGET (CLAUDE.md §1/§3):
#   `uv sync` installs only core dependencies — NOT the [ml-fallback] extra —
#   so torch / transformers / scikit-learn are NOT in the image. The daemon
#   embeds via onnxruntime and routes via the pre-trained numpy SVM, keeping it
#   within the 4GB / <300MB RSS budget. Do NOT add `--extra ml-fallback` here.
#
# Operators SHOULD additionally pin the base image by digest
# (FROM python:3.11-slim@sha256:...) after verifying it for their registry.
# =============================================================================

# -----------------------------------------------------------------------------
# STAGE 1: Builder
# -----------------------------------------------------------------------------
FROM python:3.11-slim AS builder

WORKDIR /app

# uv provides fast, lockfile-faithful installs. Its own version does not affect
# the resolved app dependency set (that is fixed by --frozen + uv.lock).
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv

# Dependency layer: copy only resolution inputs so this layer is cached unless
# pyproject.toml / uv.lock change. --no-dev excludes test/lint tooling;
# --no-install-project installs deps only (the app runs from /app/src, matching
# the runtime layout and BASE_DIR detection).
COPY pyproject.toml uv.lock README.md ./
# Optional extras from the lockfile, e.g. --build-arg UV_SYNC_EXTRAS="--extra scale"
# for the Postgres checkpointer (CHECKPOINT_BACKEND=postgres). Empty = core only.
ARG UV_SYNC_EXTRAS=""
RUN uv sync --frozen --no-dev --no-install-project ${UV_SYNC_EXTRAS}

# -----------------------------------------------------------------------------
# STAGE 2: Router artifacts (build-time only — nothing here reaches runtime
# except the two output directories copied below)
# -----------------------------------------------------------------------------
# Model/ is .dockerignored and gitignored, so a fresh image previously started
# without the ONNX embedder or the category classifier and semantic routing
# failed to load (the sentence-transformers fallback is not installed either).
# This stage produces both from source:
#   Model/embed/all-MiniLM-L6-v2-onnx/  (scripts/export_embedding_onnx.py;
#                                        downloads the HF checkpoint)
#   Model/category_classifier.npz       (scripts/train_category_classifier.py)
# The export toolchain is installed into this stage's copy of the venv only.
# torch comes from the CPU wheel index to avoid ~3GB of CUDA wheels. The
# toolchain is pinned (versions verified to export + quantize successfully) so
# the artifacts are reproducible; bump deliberately.
FROM builder AS artifacts

RUN uv pip install --python /opt/venv/bin/python \
        --index-url https://download.pytorch.org/whl/cpu "torch==2.15.0+cpu" \
    && uv pip install --python /opt/venv/bin/python \
        "transformers==5.22.2" "onnx==1.23.2" "onnxscript==0.7.2" "ml-dtypes==0.5.4" \
        "scikit-learn==1.9.1" "numpy>=1.26.0,<2.0.0"

COPY src/ ./src/
COPY scripts/export_embedding_onnx.py scripts/train_category_classifier.py ./scripts/
RUN /opt/venv/bin/python scripts/export_embedding_onnx.py \
    && /opt/venv/bin/python scripts/train_category_classifier.py Model \
    && rm -f Model/embed/all-MiniLM-L6-v2-onnx/model_fp32.onnx*

# -----------------------------------------------------------------------------
# STAGE 3: Production Runtime
# -----------------------------------------------------------------------------
FROM python:3.11-slim AS runtime

WORKDIR /app

# Runtime system dependencies (onnxruntime needs libgomp1).
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

# Copy the locked virtual environment from the builder.
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Copy application source.
COPY src/ ./src/
COPY pyproject.toml alembic.ini ./
# Only copy the example env — NEVER copy .env / .env.* into the image.
# Real secrets are injected via Railway/Docker environment variables at runtime.
COPY .env.example ./
COPY alembic/ ./alembic/
# MCP server definitions (src/runtime/host.py reads config/mcp_servers.yaml).
COPY config/ ./config/

# Router artifacts from stage 2.
COPY --from=artifacts /app/Model/category_classifier.npz ./Model/
COPY --from=artifacts /app/Model/embed/all-MiniLM-L6-v2-onnx/ ./Model/embed/all-MiniLM-L6-v2-onnx/

# Create non-root user for security. Model/ stays writable: the semantic
# router builds Model/unified_semantic_cache.npz on first start.
RUN useradd --create-home --shell /bin/bash amadeus && \
    mkdir -p /app/data && \
    chown -R amadeus:amadeus /app

USER amadeus

# Environment defaults (override via Railway / Docker environment variables).
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    ENV=production \
    DEBUG=false \
    API_HOST=0.0.0.0 \
    API_PORT=8000 \
    DATABASE_URL=postgresql://postgres:postgres@postgres:5432/amadeus

# Health check using the /health endpoint.
HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')" || exit 1

EXPOSE 8000

CMD ["uvicorn", "src.transports.fastapi_transport:app", \
     "--host", "0.0.0.0", "--port", "8000", \
     "--workers", "1", "--log-level", "info"]
