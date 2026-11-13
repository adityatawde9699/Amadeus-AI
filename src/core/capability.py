"""
Hardware capability tiering for graceful degradation.

The 4GB/no-GPU host is the *floor* tier, not a hard ceiling. At startup we
probe the machine (total RAM, logical CPU cores, optional GPU) and resolve a
:class:`CapabilityTier`. Heavy agentic features — multi-expert orchestration,
parallel tool calls, larger local models — are gated on the resolved tier so
the same daemon runs everywhere, disabling what a weak host cannot afford
instead of failing.

The resolved tier can always be overridden via the ``CAPABILITY_TIER`` setting
(``auto`` | ``lite`` | ``standard`` | ``power``) so a 4GB dev box can force
``standard`` to exercise orchestration, and a beefy host can force ``lite`` to
measure the floor path.
"""

from __future__ import annotations

import enum
import logging
from dataclasses import dataclass
from functools import lru_cache


logger = logging.getLogger(__name__)


class CapabilityTier(enum.StrEnum):
    """Resolved hardware capability tier (ascending capacity)."""

    LITE = "lite"  # <= ~4GB RAM: single expert, no parallelism (the floor)
    STANDARD = "standard"  # ~8-16GB: sequential multi-expert orchestration
    POWER = "power"  # 16GB+/GPU: parallel sub-agents, deep plans


@dataclass(frozen=True)
class CapabilityProfile:
    """Derived feature budget for the active host.

    Attributes:
        tier: The resolved :class:`CapabilityTier`.
        total_ram_gb: Detected total system RAM in GiB.
        cpu_cores: Detected logical CPU cores.
        has_gpu: Whether a usable GPU was detected.
        max_sub_agents: Cap on experts the orchestrator may chain per request.
        allow_orchestration: Whether multi-expert decomposition is enabled.
        allow_parallel_tools: Whether independent steps may run concurrently.
    """

    tier: CapabilityTier
    total_ram_gb: float
    cpu_cores: int
    has_gpu: bool

    @property
    def allow_orchestration(self) -> bool:
        """Multi-expert chaining is off on the floor tier to protect latency/RAM."""
        return self.tier is not CapabilityTier.LITE

    @property
    def max_sub_agents(self) -> int:
        """Upper bound on experts chained per request, by tier."""
        if self.tier is CapabilityTier.POWER:
            return 5
        if self.tier is CapabilityTier.STANDARD:
            return 3
        return 1

    @property
    def allow_parallel_tools(self) -> bool:
        """Concurrent step execution is reserved for the Power tier."""
        return self.tier is CapabilityTier.POWER


def _detect_total_ram_gb() -> float:
    try:
        import psutil

        return round(psutil.virtual_memory().total / (1024**3), 2)
    except Exception:  # pragma: no cover - psutil should always be present
        logger.warning("RAM detection failed — assuming floor tier (4GB)")
        return 4.0


def _detect_cpu_cores() -> int:
    try:
        import os

        return os.cpu_count() or 2
    except Exception:  # pragma: no cover
        return 2


# llama.cpp backend libraries shipped inside llama_cpp/lib/ by GPU builds.
_GPU_BACKEND_LIBS: tuple[str, ...] = ("cuda", "metal", "vulkan", "hip", "sycl", "opencl")


def _llama_gpu_backend_libs() -> set[str] | None:
    """GPU backends compiled into the installed llama-cpp-python, or None if absent.

    Reads the file names in ``llama_cpp/lib`` instead of importing llama_cpp:
    loading the native library at config time is slow, and a build compiled for
    a newer CPU dies with SIGILL rather than raising.
    """
    import importlib.util
    from pathlib import Path

    try:
        spec = importlib.util.find_spec("llama_cpp")
    except (ImportError, ValueError):
        return None
    if spec is None or not spec.origin:
        return None
    lib_dir = Path(spec.origin).parent / "lib"
    names = [p.name.lower() for p in lib_dir.glob("*ggml-*")] if lib_dir.is_dir() else []
    return {b for b in _GPU_BACKEND_LIBS if any(f"ggml-{b}" in n for n in names)}


def _detect_gpu() -> bool:
    """Whether local inference can actually use a GPU.

    A GPU only helps if the installed llama-cpp-python build can offload to it,
    so ``nvidia-smi`` alone is not enough (a CPU-only build still runs on CPU).
    CUDA additionally needs a visible NVIDIA GPU. Without llama-cpp-python,
    fall back to the cheap ``nvidia-smi`` signal.
    """
    import shutil
    import sys

    backends = _llama_gpu_backend_libs()
    if backends is None:
        return bool(shutil.which("nvidia-smi"))
    if "cuda" in backends and shutil.which("nvidia-smi"):
        return True
    if "metal" in backends and sys.platform == "darwin":
        return True
    return bool(backends - {"cuda", "metal"})


def _tier_from_hardware(ram_gb: float, has_gpu: bool) -> CapabilityTier:
    if has_gpu or ram_gb >= 16:
        return CapabilityTier.POWER
    if ram_gb >= 7.0:  # ~8GB machines report a little under 8 GiB
        return CapabilityTier.STANDARD
    return CapabilityTier.LITE


@lru_cache(maxsize=8)
def resolve_capability(override: str = "auto") -> CapabilityProfile:
    """Resolve the host :class:`CapabilityProfile`.

    Args:
        override: ``auto`` to detect, or a :class:`CapabilityTier` value to force.

    Cached because hardware does not change within a process lifetime.
    """
    ram_gb = _detect_total_ram_gb()
    cpu_cores = _detect_cpu_cores()
    has_gpu = _detect_gpu()

    override = (override or "auto").strip().lower()
    if override != "auto":
        try:
            tier = CapabilityTier(override)
        except ValueError:
            logger.warning("Unknown CAPABILITY_TIER=%r — falling back to auto-detect", override)
            tier = _tier_from_hardware(ram_gb, has_gpu)
    else:
        tier = _tier_from_hardware(ram_gb, has_gpu)

    profile = CapabilityProfile(
        tier=tier, total_ram_gb=ram_gb, cpu_cores=cpu_cores, has_gpu=has_gpu
    )
    logger.info(
        "Capability tier=%s (ram=%.1fGB cores=%d gpu=%s orchestration=%s max_sub_agents=%d)",
        profile.tier.value,
        ram_gb,
        cpu_cores,
        has_gpu,
        profile.allow_orchestration,
        profile.max_sub_agents,
    )
    return profile
