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

    LITE = "lite"        # <= ~4GB RAM: single expert, no parallelism (the floor)
    STANDARD = "standard"  # ~8-16GB: sequential multi-expert orchestration
    POWER = "power"      # 16GB+/GPU: parallel sub-agents, deep plans


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


def _detect_gpu() -> bool:
    """Best-effort GPU presence check without importing heavy ML stacks."""
    import shutil

    # NVIDIA: nvidia-smi on PATH is a reliable, cheap signal.
    if shutil.which("nvidia-smi"):
        return True
    # Apple Silicon exposes a GPU but we treat it conservatively as CPU-class
    # for the local llama.cpp budget; callers can override via CAPABILITY_TIER.
    return False


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
        profile.tier.value, ram_gb, cpu_cores, has_gpu,
        profile.allow_orchestration, profile.max_sub_agents,
    )
    return profile
