"""Phase 4 reflective learning: record and recall past tool outcomes.

Mixin of ``AmadeusGraph`` (see ``agent_loop.py``); split out of the former
single 1,300-line module without changing any method body.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from src.app.services.agent_graph.base import GraphBase
from src.core.prompt_safety import (
    wrap_untrusted,
)


if TYPE_CHECKING:
    from src.core.domain.context import RequestContext

logger = logging.getLogger(__name__)


class OutcomeMemory(GraphBase):
    # ------------------------------------------------------------------
    # Phase 4 — reflective learning
    # ------------------------------------------------------------------

    async def _record_outcomes(self, final_state: dict, context: RequestContext) -> None:
        """Persist compact per-tool outcome records for future planning."""
        if self.memory_service is None or not getattr(self.memory_service, "is_enabled", False):
            return
        from src.core.config import get_settings

        if not getattr(get_settings(), "ENABLE_REFLECTIVE_LEARNING", True):
            return

        task = (final_state.get("root_task") or final_state.get("task") or "").strip()
        observations = final_state.get("observations", [])
        if not task or not observations:
            return

        intent = task[:80]
        seen: set[str] = set()
        for obs in observations:
            if ":" not in obs:
                continue
            tool_name, result = obs.split(":", 1)
            tool_name = tool_name.strip()
            result = result.strip()
            if not tool_name or tool_name in ("FINISH",) or tool_name in seen:
                continue
            seen.add(tool_name)
            failed = result.lower().startswith(("error", "skipped"))
            verdict = "FAILED" if failed else "succeeded"
            text = f"[OUTCOME] tool '{tool_name}' {verdict} for intent: {intent} → {result[:160]}"
            try:
                await self.memory_service.store(
                    session_id=context.session_id,
                    role="system",
                    text=text,
                    subtype="outcome",
                    importance=0.55 if failed else 0.45,
                )
            except Exception:
                logger.debug("Failed to store outcome record", exc_info=True)

    async def _retrieve_outcomes(self, task: str, top_k: int = 3) -> str:
        """Return a formatted block of relevant past tool outcomes (or '')."""
        if self.memory_service is None or not getattr(self.memory_service, "is_enabled", False):
            return ""
        from src.core.config import get_settings

        if not getattr(get_settings(), "ENABLE_REFLECTIVE_LEARNING", True):
            return ""
        try:
            results = await self.memory_service.retrieve(task, top_k=top_k * 3)
        except Exception:
            return ""
        lines = [r.text for r in results if getattr(r, "subtype", "") == "outcome"][:top_k]
        if not lines:
            return ""
        # Outcomes are recorded from tool output, so they are persisted
        # untrusted content — fence them like any other tool data.
        return (
            "\n[PAST OUTCOMES — prefer approaches that succeeded, avoid ones that FAILED]\n"
            + wrap_untrusted("\n".join(f"- {ln}" for ln in lines), source="past_outcomes")
            + "\n"
        )
