#!/usr/bin/env bash
# =============================================================================
# Rebuild llama-cpp-python with GPU acceleration (CUDA, ROCm, Vulkan or Metal).
#
# PyPI ships llama-cpp-python as source only, and a plain install builds the
# CPU backend (Metal on macOS). Upstream's prebuilt CUDA wheels stop at older
# versions and CUDA 12.4, which cannot target Blackwell (RTX 50xx). So this
# script rebuilds the exact version pinned in uv.lock with the right backend
# flags for this machine. uv.lock is not changed, and `uv sync` keeps the GPU
# build (same version). `uv sync --reinstall` would replace it with a CPU build.
#
# Usage:
#   scripts/install_gpu_backend.sh                 # auto-detect backend
#   scripts/install_gpu_backend.sh --backend cuda  # cuda | rocm | vulkan | metal | cpu
#   scripts/install_gpu_backend.sh --arch "86;120" # CUDA compute capabilities
#   scripts/install_gpu_backend.sh --python /path/to/venv/bin/python --dry-run
#
# Expect a long build: CUDA takes roughly 30-120 minutes, depending on the CPU.
# Afterwards, Amadeus uses the GPU automatically (SLM_N_GPU_LAYERS=auto).
# =============================================================================
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND="auto"
ARCH=""
PY=""
DRY_RUN=0
JOBS="$( (command -v nproc >/dev/null && nproc) || sysctl -n hw.ncpu 2>/dev/null || echo 4)"

die() { echo "error: $*" >&2; exit 1; }
info() { echo "==> $*"; }

while [[ $# -gt 0 ]]; do
    case "$1" in
        --backend) BACKEND="${2:?}"; shift 2 ;;
        --arch) ARCH="${2:?}"; shift 2 ;;
        --python) PY="${2:?}"; shift 2 ;;
        --jobs) JOBS="${2:?}"; shift 2 ;;
        --dry-run) DRY_RUN=1; shift ;;
        -h|--help) sed -n '2,21p' "$0"; exit 0 ;;
        *) die "unknown option: $1 (see --help)" ;;
    esac
done

# --- target interpreter ------------------------------------------------------
if [[ -z "$PY" ]]; then
    if [[ -n "${VIRTUAL_ENV:-}" && -x "$VIRTUAL_ENV/bin/python" ]]; then
        PY="$VIRTUAL_ENV/bin/python"
    elif [[ -x "$ROOT/.venv/bin/python" ]]; then
        PY="$ROOT/.venv/bin/python"
    else
        die "no virtualenv found; create one with 'uv sync' or pass --python"
    fi
fi
[[ -x "$PY" ]] || die "python not executable: $PY"

# --- pinned version (from uv.lock, so the GPU build matches what CI tests) ----
VERSION="$(awk '/^name = "llama-cpp-python"$/ {getline; gsub(/version = |"/, ""); print; exit}' "$ROOT/uv.lock" 2>/dev/null || true)"
[[ -n "$VERSION" ]] || die "could not read the llama-cpp-python version from uv.lock"

# --- backend detection --------------------------------------------------------
if [[ "$BACKEND" == "auto" ]]; then
    if [[ "$(uname -s)" == "Darwin" ]]; then
        BACKEND="metal"
    elif command -v nvidia-smi >/dev/null && nvidia-smi -L >/dev/null 2>&1; then
        BACKEND="cuda"
    elif command -v rocminfo >/dev/null && rocminfo 2>/dev/null | grep -q "gfx"; then
        BACKEND="rocm"
    elif command -v vulkaninfo >/dev/null && vulkaninfo --summary >/dev/null 2>&1; then
        BACKEND="vulkan"
    else
        die "no supported GPU found (looked for NVIDIA, AMD ROCm, Vulkan, Apple). Use --backend to force one."
    fi
fi

CMAKE_ARGS=""
case "$BACKEND" in
    cuda)
        # Pick the newest nvcc available: distros often ship an older toolkit in
        # /usr/bin alongside NVIDIA's newer one in /usr/local/cuda-X.Y.
        NVCC=""; BEST=""
        for c in "${CUDA_HOME:+$CUDA_HOME/bin/nvcc}" "${CUDA_PATH:+$CUDA_PATH/bin/nvcc}" \
                 "$(command -v nvcc || true)" /usr/local/cuda/bin/nvcc /usr/local/cuda-*/bin/nvcc; do
            [[ -n "$c" && -x "$c" ]] || continue
            v="$("$c" --version 2>/dev/null | sed -n 's/.*release \([0-9]*\.[0-9]*\).*/\1/p')"
            [[ -n "$v" ]] || continue
            if [[ -z "$BEST" || "$(printf '%s\n%s\n' "$BEST" "$v" | sort -V | tail -1)" == "$v" && "$v" != "$BEST" ]]; then
                NVCC="$c"; BEST="$v"
            fi
        done
        [[ -n "$NVCC" ]] || die "nvcc not found. Install the CUDA Toolkit (12.8+ for RTX 50xx): https://developer.nvidia.com/cuda-downloads"
        CUDA_BIN="$(dirname "$NVCC")"
        CUDA_VER="$("$NVCC" --version | sed -n 's/.*release \([0-9]*\.[0-9]*\).*/\1/p')"
        info "CUDA toolkit $CUDA_VER at $CUDA_BIN"

        if [[ -z "$ARCH" ]]; then
            ARCH="$(nvidia-smi --query-gpu=compute_cap --format=csv,noheader 2>/dev/null | tr -d ' .' | sort -u | paste -sd ';' -)"
            [[ -n "$ARCH" ]] || die "could not read the GPU compute capability; pass --arch (e.g. 86 or 120)"
        fi
        info "GPU architectures: $ARCH"
        # Blackwell (sm_100/sm_120) needs CUDA 12.8; Hopper (sm_90) needs 12.0.
        for a in ${ARCH//;/ }; do
            need=""
            (( a >= 100 )) && need="12.8"
            (( a >= 90 && a < 100 )) && need="12.0"
            if [[ -n "$need" ]] && [[ "$(printf '%s\n%s\n' "$need" "$CUDA_VER" | sort -V | head -1)" != "$need" ]]; then
                die "sm_$a needs CUDA $need or newer; found $CUDA_VER"
            fi
        done

        CMAKE_ARGS="-DGGML_CUDA=on -DCMAKE_CUDA_ARCHITECTURES=$ARCH"

        # nvcc rejects host compilers newer than it supports (e.g. CUDA 12.8 vs
        # GCC 15). Read the limit from its headers and pick an older g++ if needed.
        HOST_CFG="$(dirname "$CUDA_BIN")/targets/x86_64-linux/include/crt/host_config.h"
        [[ -f "$HOST_CFG" ]] || HOST_CFG="$(dirname "$CUDA_BIN")/include/crt/host_config.h"
        if [[ -f "$HOST_CFG" ]] && command -v g++ >/dev/null; then
            MAX_GCC="$(sed -n 's/^#if __GNUC__ > \([0-9]*\).*/\1/p' "$HOST_CFG" | head -1)"
            SYS_GCC="$(g++ -dumpversion | cut -d. -f1)"
            if [[ -n "$MAX_GCC" && "$SYS_GCC" -gt "$MAX_GCC" ]]; then
                HOST_CXX=""
                for v in $(seq "$MAX_GCC" -1 9); do
                    command -v "g++-$v" >/dev/null && { HOST_CXX="$(command -v "g++-$v")"; break; }
                done
                [[ -n "$HOST_CXX" ]] || die "CUDA $CUDA_VER supports GCC <= $MAX_GCC but the system has $SYS_GCC. Install g++-$MAX_GCC (e.g. 'sudo apt install g++-$MAX_GCC')."
                info "Using host compiler $HOST_CXX (CUDA $CUDA_VER supports GCC <= $MAX_GCC)"
                CMAKE_ARGS="$CMAKE_ARGS -DCMAKE_CUDA_HOST_COMPILER=$HOST_CXX"
            fi
        fi
        export PATH="$CUDA_BIN:$PATH" CUDACXX="$NVCC"
        ;;
    rocm)
        command -v hipconfig >/dev/null || die "hipconfig not found; install ROCm: https://rocm.docs.amd.com"
        if [[ -z "$ARCH" ]]; then
            ARCH="$(rocminfo | grep -o 'gfx[0-9a-f]*' | grep -v gfx000 | sort -u | paste -sd ';' -)"
        fi
        [[ -n "$ARCH" ]] || die "could not detect the AMD GPU target; pass --arch (e.g. gfx1100)"
        info "AMD GPU targets: $ARCH"
        CMAKE_ARGS="-DGGML_HIP=on -DAMDGPU_TARGETS=$ARCH"
        HIPCXX="$(hipconfig -l)/clang"
        HIP_PATH="$(hipconfig -R)"
        export HIPCXX HIP_PATH
        ;;
    vulkan)
        command -v glslc >/dev/null || die "glslc not found; install the Vulkan SDK (e.g. 'sudo apt install libvulkan-dev glslc')"
        CMAKE_ARGS="-DGGML_VULKAN=on"
        ;;
    metal)
        [[ "$(uname -s)" == "Darwin" ]] || die "Metal is only available on macOS"
        CMAKE_ARGS="-DGGML_METAL=on"
        ;;
    cpu)
        CMAKE_ARGS="-DGGML_CUDA=off -DGGML_HIP=off -DGGML_VULKAN=off"
        ;;
    *) die "unknown backend: $BACKEND (cuda | rocm | vulkan | metal | cpu)" ;;
esac

info "Rebuilding llama-cpp-python==$VERSION for $BACKEND into $PY"
info "CMAKE_ARGS=$CMAKE_ARGS (jobs=$JOBS)"
export CMAKE_ARGS CMAKE_BUILD_PARALLEL_LEVEL="$JOBS"

if command -v uv >/dev/null; then
    CMD=(uv pip install --python "$PY" --reinstall-package llama-cpp-python
         --no-binary llama-cpp-python --no-cache "llama-cpp-python==$VERSION")
else
    CMD=("$PY" -m pip install --force-reinstall --no-deps --no-binary llama-cpp-python
         --no-cache-dir "llama-cpp-python==$VERSION")
fi
if (( DRY_RUN )); then
    printf 'would run:'; printf ' %q' "${CMD[@]}"; echo
    exit 0
fi
[[ "$BACKEND" == "cpu" ]] || info "This can take 30-120 minutes. Build output is quiet until it finishes."
"${CMD[@]}"

info "Verifying"
"$PY" - "$BACKEND" <<'EOF'
import sys
import llama_cpp

gpu = bool(llama_cpp.llama_supports_gpu_offload())
info = llama_cpp.llama_print_system_info().decode("utf-8", "replace").split(" | ")[0]
print(f"llama-cpp-python {llama_cpp.__version__}: GPU offload {'available' if gpu else 'NOT available'} ({info})")
sys.exit(0 if gpu or sys.argv[1] == "cpu" else 1)
EOF
info "Done. Amadeus will use the GPU automatically (SLM_N_GPU_LAYERS=auto)."
