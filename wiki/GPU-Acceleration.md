# GPU Acceleration

Local inference (llama.cpp through `llama-cpp-python`) can run on an NVIDIA, AMD, Apple or Vulkan-capable GPU. On an RTX 5050 laptop GPU, Qwen3-4B Q4_K_M ran about 15× faster than on CPU:

| | CPU (16 threads) | GPU (all layers) |
|---|---|---|
| ~1k-token prompt + 64 tokens | 16.8 s | 1.1 s |
| Generation speed | – | ~67 tok/s |
| Memory | 4.8 GB RAM | 3.4 GB VRAM |

Amadeus uses the GPU **automatically** when the installed llama-cpp-python build has a GPU backend. `SLM_N_GPU_LAYERS=auto` (the default) offloads every layer on a GPU build and stays on CPU otherwise. If a GPU load fails, for example because the model doesn't fit in VRAM, Amadeus logs a warning and loads the model on CPU instead of disabling local inference. Startup logs show the result:

```
llama.cpp GPU offload enabled: backend=CUDA, layers=all, main_gpu=0.
LlamaCpp initialized successfully (backend=CUDA).
```

The catch is that **a plain install is CPU-only** on Linux and Windows. PyPI only publishes llama-cpp-python as source code, and the default build has no GPU backend. Upstream's prebuilt CUDA wheels stop at older versions and CUDA 12.4, which can't target RTX 50xx cards. So a GPU build has to be compiled once, as shown below. macOS is the exception: its default build already uses Metal.

---

## Local install (Linux, macOS)

After `uv sync`:

```bash
scripts/install_gpu_backend.sh            # detects NVIDIA / AMD / Vulkan / Apple
```

The script:
- rebuilds the **exact llama-cpp-python version pinned in `uv.lock`** with the right backend flags;
- detects the GPU architecture (`nvidia-smi` compute capability, or the ROCm `gfx` target);
- picks the newest CUDA toolkit installed;
- chooses a host compiler that `nvcc` accepts. For example, CUDA 12.8 rejects GCC 15, so the script uses `g++-14` when it is installed.

At the end it verifies that GPU offload works.

| Option | Example |
|---|---|
| Force a backend | `--backend cuda` · `rocm` · `vulkan` · `metal` · `cpu` (back to the CPU build) |
| Choose GPU architectures | `--arch "86;120"` (CUDA compute capabilities), `--arch gfx1100` (ROCm) |
| Another virtualenv | `--python /path/to/venv/bin/python` |
| Show the command only | `--dry-run` |

**Expect a long build.** A CUDA build takes roughly 30–120 minutes depending on the CPU: a few heavy CUDA files compile one at a time at the end. You only build once per llama-cpp-python version. `uv sync` keeps the GPU build because the version is unchanged. `uv sync --reinstall`, or a lockfile bump of llama-cpp-python, replaces it with a CPU build, and you then need to rerun the script.

### Prerequisites

| Backend | Needs |
|---|---|
| **CUDA** (NVIDIA) | Driver plus [CUDA Toolkit](https://developer.nvidia.com/cuda-downloads). RTX 50xx (Blackwell, sm_120) needs **CUDA 12.8 or newer**, and Hopper (sm_90) needs 12.0 or newer. You also need a GCC version that the toolkit supports. |
| **ROCm** (AMD) | [ROCm](https://rocm.docs.amd.com) with `hipconfig` and `rocminfo` |
| **Vulkan** | Vulkan SDK / `libvulkan-dev` and `glslc`. Works on most GPUs, but is usually slower than CUDA or ROCm. |
| **Metal** (Apple Silicon) | Xcode command-line tools. The default build already uses Metal. |

### Windows

Install the CUDA Toolkit and the Visual Studio Build Tools (C++ workload). Then run this in a Developer PowerShell, using the version from `uv.lock`:

```powershell
$env:CMAKE_ARGS = "-DGGML_CUDA=on -DCMAKE_CUDA_ARCHITECTURES=120"   # your GPU's compute capability
uv pip install --reinstall-package llama-cpp-python --no-binary llama-cpp-python --no-cache "llama-cpp-python==0.3.23"
```

---

## Docker (NVIDIA)

```bash
# Host: NVIDIA driver >= 570 + NVIDIA Container Toolkit
docker compose -f docker-compose.yml -f docker-compose.gpu.yml up --build
```

- `docker-compose.gpu.yml` builds the CUDA image variant (`--build-arg LLAMA_BACKEND=cuda`) and reserves the GPU for the `amadeus` service. The worker runs no model, so it keeps the CPU image.
- The CUDA variant uses a Debian 12 base with CUDA 12.8. NVIDIA's Debian 13 repository only carries CUDA 13, which needs driver 580 or newer. The runtime image adds only the CUDA runtime and cuBLAS. It is about 3.2 GB, against 1.1 GB for the CPU image. The driver comes from the host.
- `CUDA_ARCHITECTURES` defaults to `75;80;86;89;90;120`, which covers T4 / RTX 20xx through RTX 50xx. Each architecture adds build time, so build only for your card:

| GPU | Value |
|---|---|
| RTX 20xx, T4 | `75` |
| A100 | `80` |
| RTX 30xx, A10 | `86` |
| RTX 40xx, L4, L40S | `89` |
| H100 | `90` |
| RTX 50xx | `120` |

  ```bash
  CUDA_ARCHITECTURES=120 docker compose -f docker-compose.yml -f docker-compose.gpu.yml up --build
  # or: docker build --build-arg LLAMA_BACKEND=cuda --build-arg CUDA_ARCHITECTURES=120 -t amadeus-ai:cuda .
  ```

- **Give the container the GPU** with `--gpus all` or the compose override, so the NVIDIA Container Toolkit injects the host driver. If no driver is present, the entrypoint uses CUDA's stub library instead. llama.cpp then finds no device and **runs on CPU** instead of failing, and the log says `no NVIDIA driver found`. On machines that never have a GPU, the CPU image is 2 GB smaller.

Verified on an RTX 5050 with Qwen3-4B: the image detected `backend=CUDA` with all layers offloaded and replied in 0.6 s. Without the GPU, the same image fell back to CPU.

---

## Settings

| Variable | Default | Meaning |
|---|---|---|
| `SLM_N_GPU_LAYERS` | `auto` | `auto`: all layers on a GPU build, CPU otherwise. `0`: CPU only. `-1`: all layers. `N`: offload N layers, for a model larger than VRAM. |
| `SLM_MAIN_GPU` | `0` | GPU index for multi-GPU machines |
| `SLM_CTX_SIZE` | `4096` | The context size also sets the KV-cache VRAM. Lower it if the model doesn't fit. |
| `SLM_QUANTIZE_KV_4BIT` | `true` | A 4-bit KV cache uses about 75% less memory, which helps larger models fit. |

**Sizing:** the model file plus about 0.5–1 GB has to fit in VRAM. For example, Qwen3-4B Q4_K_M uses about 3.4 GB and Qwen3-8B Q4_K_M about 5.5 GB. If it doesn't fit, set `SLM_N_GPU_LAYERS` to a partial count. Splitting layers between GPU and CPU is still much faster than CPU alone.

**Capability tier:** `CAPABILITY_TIER=auto` counts a GPU only if llama.cpp can actually offload to it. `nvidia-smi` alone isn't enough when the build is CPU-only.

---

*← [[Configuration-Reference]] | [[Deployment]] →*
