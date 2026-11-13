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
# GPU (NVIDIA CUDA) VARIANT:
#   docker build --build-arg LLAMA_BACKEND=cuda -t amadeus-ai:cuda .
#   docker compose -f docker-compose.yml -f docker-compose.gpu.yml up --build
# Debian 12 base with NVIDIA's CUDA 12.8 packages; compiles llama.cpp's
# CUDA backend. Needs the NVIDIA Container Toolkit on the host and a GPU at run
# time (--gpus all). CUDA_ARCHITECTURES picks the GPU generations to compile
# for; fewer is a faster build (e.g. "120" for RTX 50xx only). See
# wiki/GPU-Acceleration.md.
#
# Operators SHOULD additionally pin the base image by digest
# (FROM python:3.11-slim@sha256:...) after verifying it for their registry.
# =============================================================================

# llama.cpp backend: "cpu" (default) or "cuda". Declared before the first FROM
# so it can select the base image below.
ARG LLAMA_BACKEND=cpu

# Base image per backend. NVIDIA's apt repo for Debian 13 (the current
# python:3.11-slim) only carries CUDA 13 (driver >= 580), and Debian 13 rejects
# the SHA-1 key binding on its Debian 12 repo. The CUDA variant therefore stays
# on Debian 12 (bookworm) with CUDA 12.8 (driver >= 570), the first release that
# targets Blackwell. Only the selected base is pulled.
FROM python:3.11-slim AS base-cpu
FROM python:3.11-slim-bookworm AS base-cuda

# -----------------------------------------------------------------------------
# STAGE 1: Builder
# -----------------------------------------------------------------------------
FROM base-${LLAMA_BACKEND} AS builder

WORKDIR /app

# uv provides fast, lockfile-faithful installs. Its own version does not affect
# the resolved app dependency set (that is fixed by --frozen + uv.lock).
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir uv

# The default CUDA architecture list spans Turing (RTX 20xx, T4) to Blackwell
# (RTX 50xx).
ARG LLAMA_BACKEND
ARG CUDA_VERSION=12-8
ARG CUDA_ARCHITECTURES="75;80;86;89;90;120"
RUN if [ "$LLAMA_BACKEND" = "cuda" ]; then \
        apt-get update && apt-get install -y --no-install-recommends curl ca-certificates \
        && curl -fsSL -o /tmp/cuda-keyring.deb \
           https://developer.download.nvidia.com/compute/cuda/repos/debian12/x86_64/cuda-keyring_1.1-1_all.deb \
        && dpkg -i /tmp/cuda-keyring.deb && rm /tmp/cuda-keyring.deb \
        && apt-get update && apt-get install -y --no-install-recommends \
           cuda-nvcc-${CUDA_VERSION} cuda-cudart-dev-${CUDA_VERSION} \
           cuda-driver-dev-${CUDA_VERSION} libcublas-dev-${CUDA_VERSION} \
        && rm -rf /var/lib/apt/lists/*; \
    elif [ "$LLAMA_BACKEND" != "cpu" ]; then \
        echo "Unsupported LLAMA_BACKEND=$LLAMA_BACKEND (use cpu or cuda)" >&2; exit 1; \
    fi \
    # CUDA's driver stub, used by docker-entrypoint.sh only when the host has no
    # NVIDIA driver (the image then runs on CPU instead of failing). Empty for cpu.
    && mkdir -p /opt/cuda-stub \
    && if [ "$LLAMA_BACKEND" = "cuda" ]; then \
        cp "/usr/local/cuda-$(echo "$CUDA_VERSION" | tr - .)/targets/x86_64-linux/lib/stubs/libcuda.so" \
           /opt/cuda-stub/libcuda.so.1; \
    fi

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
# llama-cpp-python is source-only on PyPI, so this step compiles it. For the
# CUDA variant the same build gets the CUDA flags (slow: tens of minutes per
# architecture on a small builder).
# GGML_NATIVE=OFF: llama.cpp otherwise compiles for the build machine's CPU
# and the image crashes (SIGILL) on hosts with an older one.
RUN export CMAKE_ARGS="-DGGML_NATIVE=OFF"; \
    if [ "$LLAMA_BACKEND" = "cuda" ]; then \
        CUDA_HOME="/usr/local/cuda-$(echo "$CUDA_VERSION" | tr - .)"; \
        export PATH="$CUDA_HOME/bin:$PATH" CUDACXX="$CUDA_HOME/bin/nvcc" \
               CMAKE_ARGS="$CMAKE_ARGS -DGGML_CUDA=on -DCMAKE_CUDA_ARCHITECTURES=${CUDA_ARCHITECTURES}"; \
    fi; \
    CMAKE_BUILD_PARALLEL_LEVEL="$(nproc)" uv sync --frozen --no-dev --no-install-project ${UV_SYNC_EXTRAS}

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
# STAGE 2b: Optional local LLM (GGUF). Opt-in: it adds the whole model to the
# image (0.8-2.5 GB). Default is empty and the model is fetched at first start
# into a volume instead (see docker-compose.yml). To bake one in:
#   docker build --build-arg GGUF_REPO_ID=bartowski/Llama-3.2-3B-Instruct-GGUF \
#                --build-arg GGUF_FILENAME=Llama-3.2-3B-Instruct-Q4_K_M.gguf .
# -----------------------------------------------------------------------------
FROM builder AS gguf

ARG GGUF_REPO_ID=""
ARG GGUF_FILENAME=""
RUN mkdir -p /gguf && if [ -n "$GGUF_REPO_ID" ] && [ -n "$GGUF_FILENAME" ]; then \
        /opt/venv/bin/python -c "import sys; from huggingface_hub import hf_hub_download; \
hf_hub_download(repo_id=sys.argv[1], filename=sys.argv[2], local_dir='/gguf')" \
        "$GGUF_REPO_ID" "$GGUF_FILENAME" && rm -rf /gguf/.cache; \
    fi

# -----------------------------------------------------------------------------
# STAGE 3: Production Runtime
# -----------------------------------------------------------------------------
FROM base-${LLAMA_BACKEND} AS runtime

WORKDIR /app

# Runtime system dependencies (onnxruntime needs libgomp1). The CUDA variant
# adds only the CUDA runtime + cuBLAS libraries; the driver (libcuda) comes from
# the host through the NVIDIA Container Toolkit.
ARG LLAMA_BACKEND
ARG CUDA_VERSION=12-8
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgomp1 \
    && if [ "$LLAMA_BACKEND" = "cuda" ]; then \
        apt-get install -y --no-install-recommends curl ca-certificates \
        && curl -fsSL -o /tmp/cuda-keyring.deb \
           https://developer.download.nvidia.com/compute/cuda/repos/debian12/x86_64/cuda-keyring_1.1-1_all.deb \
        && dpkg -i /tmp/cuda-keyring.deb && rm /tmp/cuda-keyring.deb \
        && apt-get update && apt-get install -y --no-install-recommends \
           cuda-cudart-${CUDA_VERSION} libcublas-${CUDA_VERSION} \
        && echo "/usr/local/cuda-$(echo "$CUDA_VERSION" | tr - .)/targets/x86_64-linux/lib" \
           > /etc/ld.so.conf.d/zz-amadeus-cuda.conf \
        && ldconfig \
        && apt-get purge -y curl && apt-get autoremove -y; \
    fi \
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

# CUDA driver stub (cuda variant only) + entrypoint that falls back to it.
COPY --from=builder /opt/cuda-stub/ /opt/cuda-stub/
COPY scripts/docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh

# Router artifacts from stage 2.
COPY --from=artifacts /app/Model/category_classifier.npz ./Model/
COPY --from=artifacts /app/Model/embed/all-MiniLM-L6-v2-onnx/ ./Model/embed/all-MiniLM-L6-v2-onnx/
# Baked-in GGUF, if one was requested (empty directory otherwise).
COPY --from=gguf /gguf/ ./Model/
ARG GGUF_FILENAME=""
ENV SLM_MODEL_FILENAME=${GGUF_FILENAME}

# Create non-root user for security. Model/ stays writable: the semantic
# router builds Model/unified_semantic_cache.npz on first start. /app/gguf is
# the mount point for the persistent model volume (docker-compose).
RUN useradd --create-home --shell /bin/bash amadeus && \
    mkdir -p /app/data /app/gguf && \
    chown -R amadeus:amadeus /app

USER amadeus

# Environment defaults (override via Railway / Docker environment variables).
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    ENV=production \
    DEBUG=false \
    API_HOST=0.0.0.0 \
    API_PORT=8000 \
    NVIDIA_VISIBLE_DEVICES=all \
    NVIDIA_DRIVER_CAPABILITIES=compute,utility \
    DATABASE_URL=postgresql://postgres:postgres@postgres:5432/amadeus

# Health check using the /health endpoint.
HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')" || exit 1

EXPOSE 8000

ENTRYPOINT ["docker-entrypoint.sh"]
CMD ["uvicorn", "src.transports.fastapi_transport:app", \
     "--host", "0.0.0.0", "--port", "8000", \
     "--workers", "1", "--log-level", "info"]
