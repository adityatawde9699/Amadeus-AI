"""GPU auto-detection, backend naming and CPU fallback for the llama.cpp adapter."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from unittest.mock import MagicMock, patch

import pytest

from src.core.exceptions import LLMConnectionError
from src.infra.llm.llama_cpp_adapter import (
    LlamaCppAdapter,
    detect_gpu_backend,
    resolve_gpu_layers,
)


if TYPE_CHECKING:
    from pathlib import Path

CUDA_INFO = b"CUDA : ARCHS = 1200 | USE_GRAPHS = 1 | CPU : SSE3 = 1 | AVX2 = 1 | "
CPU_INFO = b"CPU : SSE3 = 1 | AVX2 = 1 | "


def _llama_module(gpu: bool, info: bytes, fail_on_gpu: bool = False) -> tuple[MagicMock, list]:
    calls: list[dict[str, Any]] = []

    def fake_llama(
        model_path: str,
        n_threads: int,
        n_ctx: int,
        n_batch: int,
        use_mmap: bool,
        use_mlock: bool,
        verbose: bool,
        n_gpu_layers: int = 0,
        main_gpu: int = 0,
        flash_attn: bool = False,
        type_k: int | None = None,
        type_v: int | None = None,
    ) -> MagicMock:
        calls.append({"n_gpu_layers": n_gpu_layers, "flash_attn": flash_attn})
        if fail_on_gpu and n_gpu_layers != 0:
            raise RuntimeError("CUDA error: out of memory")
        return MagicMock()

    module = MagicMock(
        Llama=fake_llama,
        llama_supports_gpu_offload=MagicMock(return_value=gpu),
        llama_print_system_info=MagicMock(return_value=info),
    )
    return module, calls


@pytest.fixture
def model_path(tmp_path: Path) -> str:
    p = tmp_path / "m.gguf"
    p.write_bytes(b"\x00" * 16)
    return str(p)


@pytest.mark.parametrize(
    ("gpu", "info", "expected"),
    [
        (True, CUDA_INFO, "CUDA"),
        (True, b"Metal : EMBED_LIBRARY = 1 | CPU : NEON = 1 | ", "Metal"),
        (True, b"Vulkan : COOPMAT = 1 | CPU : AVX2 = 1 | ", "Vulkan"),
        (True, b"HIP : ARCHS = gfx1100 | CPU : AVX2 = 1 | ", "HIP"),
        (True, b"SOMETHING_NEW : X = 1 | ", "GPU"),
        (False, CPU_INFO, None),
    ],
)
def test_detect_gpu_backend(gpu: bool, info: bytes, expected: str | None) -> None:
    module, _ = _llama_module(gpu, info)
    with patch.dict("sys.modules", {"llama_cpp": module}):
        assert detect_gpu_backend() == expected


def test_detect_gpu_backend_never_raises() -> None:
    with patch.dict("sys.modules", {"llama_cpp": None}):
        assert detect_gpu_backend() is None
    module = MagicMock(llama_supports_gpu_offload=MagicMock(side_effect=OSError("no libcuda")))
    with patch.dict("sys.modules", {"llama_cpp": module}):
        assert detect_gpu_backend() is None


@pytest.mark.parametrize(
    ("requested", "gpu", "expected"),
    [
        ("auto", True, -1),
        ("auto", False, 0),
        ("AUTO", True, -1),
        (-1, False, -1),
        (0, True, 0),
        (12, True, 12),
        ("8", False, 8),
    ],
)
def test_resolve_gpu_layers(requested: int | str, gpu: bool, expected: int) -> None:
    module, _ = _llama_module(gpu, CUDA_INFO if gpu else CPU_INFO)
    with patch.dict("sys.modules", {"llama_cpp": module}):
        assert resolve_gpu_layers(requested) == expected


@pytest.mark.asyncio
async def test_auto_offloads_all_layers_on_gpu_build(model_path: str) -> None:
    adapter = LlamaCppAdapter(model_path=model_path, n_gpu_layers="auto")
    module, calls = _llama_module(True, CUDA_INFO)
    with patch.dict("sys.modules", {"llama_cpp": module}):
        await adapter._get_llm()
    assert calls == [{"n_gpu_layers": -1, "flash_attn": True}]
    assert adapter.n_gpu_layers == -1 and adapter.gpu_backend == "CUDA"


@pytest.mark.asyncio
async def test_auto_stays_on_cpu_build(model_path: str) -> None:
    adapter = LlamaCppAdapter(model_path=model_path, n_gpu_layers="auto")
    module, calls = _llama_module(False, CPU_INFO)
    with patch.dict("sys.modules", {"llama_cpp": module}):
        await adapter._get_llm()
    assert calls == [{"n_gpu_layers": 0, "flash_attn": False}]
    assert adapter.gpu_backend is None


@pytest.mark.asyncio
async def test_gpu_load_failure_falls_back_to_cpu(model_path: str) -> None:
    adapter = LlamaCppAdapter(model_path=model_path, n_gpu_layers="auto", quantize_kv_4bit=True)
    module, calls = _llama_module(True, CUDA_INFO, fail_on_gpu=True)
    with patch.dict("sys.modules", {"llama_cpp": module}):
        llm = await adapter._get_llm()
    assert llm is not None
    assert [c["n_gpu_layers"] for c in calls] == [-1, 0]
    assert calls[1]["flash_attn"] is True  # still needed for the quantized V cache
    assert adapter.n_gpu_layers == 0 and adapter.gpu_backend is None


@pytest.mark.asyncio
async def test_cpu_load_failure_still_raises(model_path: str) -> None:
    adapter = LlamaCppAdapter(model_path=model_path, n_gpu_layers=0)
    module, _ = _llama_module(False, CPU_INFO)
    module.Llama = MagicMock(side_effect=MemoryError("Out of memory"))
    with patch.dict("sys.modules", {"llama_cpp": module}):
        with pytest.raises(LLMConnectionError, match="Model load failed"):
            await adapter._get_llm()


def test_settings_accept_auto_and_ints(monkeypatch: pytest.MonkeyPatch) -> None:
    from src.core.config import Settings

    monkeypatch.delenv("SLM_N_GPU_LAYERS", raising=False)
    assert Settings(_env_file=None).SLM_N_GPU_LAYERS == "auto"
    for raw, parsed in (("auto", "auto"), ("-1", -1), ("0", 0), ("20", 20)):
        monkeypatch.setenv("SLM_N_GPU_LAYERS", raw)
        value = Settings(_env_file=None).SLM_N_GPU_LAYERS
        assert value == parsed


def test_capability_gpu_follows_llama_build() -> None:
    from src.core.capability import _detect_gpu

    for gpu in (True, False):
        module, _ = _llama_module(gpu, CUDA_INFO)
        with patch.dict("sys.modules", {"llama_cpp": module}):
            assert _detect_gpu() is gpu
