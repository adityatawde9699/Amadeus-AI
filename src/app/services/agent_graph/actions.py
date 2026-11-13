"""Stateless helpers: JSON parsing, math extraction, approval / taint rules.

Mixin of ``AmadeusGraph`` (see ``agent_loop.py``); split out of the former
single 1,300-line module without changing any method body.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from src.app.services.agent_graph.base import GraphBase


logger = logging.getLogger(__name__)


class ActionHelpers(GraphBase):
    _MATH_EXPR_RE = re.compile(
        r"[(\s]*[-−]?\d+(?:\.\d+)?(?:\s*(?:[-+*/^%x×÷−]|\*\*)\s*[(\s]*[-−]?\d+(?:\.\d+)?\)*)+",
        re.IGNORECASE,
    )

    @classmethod
    def _extract_math_expression(cls, task: str) -> str | None:
        """Return the longest arithmetic expression in *task* (needs an operator)."""
        matches = [
            m.group(0).strip()
            for m in cls._MATH_EXPR_RE.finditer(task)
            if not re.fullmatch(r"\d{4}-\d{1,2}-\d{1,2}", m.group(0).strip())  # ISO date
        ]
        return max(matches, key=len) if matches else None

    # Categories whose tools return content an outside party can control.
    _EXTERNAL_CONTENT_CATEGORIES = frozenset(
        {"web_research", "news", "communication", "finance", "weather"}
    )

    @classmethod
    def _returns_external_content(cls, tool: Any) -> bool:
        """True if the tool's output may contain attacker-controlled text."""
        capability = getattr(tool, "capability", None)
        if getattr(capability, "requires_network", False):
            return True
        category = getattr(getattr(tool, "category", None), "value", None)
        return category in cls._EXTERNAL_CONTENT_CATEGORIES

    @staticmethod
    def _is_mutating(tool: Any) -> bool:
        """True if the tool can change state (anything above READ_ONLY)."""
        capability = getattr(tool, "capability", None)
        if capability is None:
            return True  # unknown → assume it mutates (fail safe)
        return bool(
            capability.modifies_filesystem
            or capability.modifies_system_state
            or str(capability.min_permission) != "read_only"
        )

    @staticmethod
    def _needs_approval(tool: Any) -> bool:
        """Risky tools (confirmation-gated or high/critical risk) require HITL."""
        if getattr(tool, "requires_confirmation", False):
            return True
        capability = getattr(tool, "capability", None)
        risk = getattr(capability, "risk_level", None) or getattr(tool, "risk_level", "low")
        return risk in ("high", "critical")

    @staticmethod
    def _approval_granted(decision: Any) -> bool:
        """Interpret an HITL resume value as approve/deny.

        Accepts a bool, a dict with an ``approved``/``approve`` key, or a
        yes/no-ish string. Anything unrecognized is treated as denial (fail
        safe — never run a risky tool without explicit approval).
        """
        if isinstance(decision, bool):
            return decision
        if isinstance(decision, dict):
            return bool(decision.get("approved", decision.get("approve", False)))
        if isinstance(decision, str):
            return decision.strip().lower() in ("yes", "y", "approve", "approved", "true", "ok")
        return False

    @staticmethod
    def _action_signature(action: str, action_input: dict) -> str:
        """Build a stable, order-independent key for cycle detection."""
        normalized = json.dumps(action_input, sort_keys=True, default=str)
        return f"{action}|{normalized}"

    @staticmethod
    def _parse_json_response(response: str) -> dict:
        """Parse JSON from LLM response, handling markdown code fences."""
        cleaned = response.strip()
        if cleaned.startswith("```json"):
            cleaned = cleaned[7:]
        if cleaned.startswith("```"):
            cleaned = cleaned[3:]
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3]
        cleaned = cleaned.strip()

        try:
            parsed = json.loads(cleaned)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            pass

        # Try to find JSON object in the response
        json_match = re.search(r"\{[^{}]*\}", cleaned, re.DOTALL)
        if json_match:
            try:
                return json.loads(json_match.group())
            except json.JSONDecodeError:
                pass

        logger.warning("Failed to parse JSON from LLM response: %s", cleaned[:200])
        return {}

    @staticmethod
    def _interrupt_payload(interrupts: Any) -> dict:
        """Extract the value dict from LangGraph's __interrupt__ structure."""
        try:
            first = interrupts[0] if isinstance(interrupts, (list, tuple)) else interrupts
            value = getattr(first, "value", first)
            return value if isinstance(value, dict) else {"question": str(value)}
        except Exception:
            return {"question": "Approval required to continue."}
