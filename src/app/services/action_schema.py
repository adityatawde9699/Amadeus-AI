"""
JSON schemas for the agent's tool-selection step (constrained decoding).

The plan and reflect nodes ask the LLM for ``{"<lead>": ..., "tool": ...,
"args": {...}}``. Small local models often break that format (prose before the
JSON, invented tool names, wrong argument keys). With a schema, llama.cpp
compiles a GBNF grammar (``response_format={"type": "json_object", "schema":
...}``) so the model *cannot* emit anything else:

* small menus (≤ ``MAX_PER_TOOL_BRANCHES`` tools) get one ``anyOf`` branch per
  tool, pinning ``tool`` to a constant and ``args`` to that tool's real
  parameter names (the ones ``ToolExecutor._validate_args`` accepts);
* large menus (the generalist sees every tool) get a compact schema — ``tool``
  restricted to an enum of registered names, ``args`` any object — because a
  70-branch grammar is slow to compile and sample.

Cloud providers ignore the schema; the prompt still describes the format.
"""

from __future__ import annotations

import inspect
from typing import TYPE_CHECKING, Any


if TYPE_CHECKING:
    from collections.abc import Iterable

    from src.infra.tools.base import Tool


FINISH = "FINISH"
MAX_PER_TOOL_BRANCHES = 24
# Bounds the free-text reasoning field so the JSON closes within the token budget.
LEAD_MAX_CHARS = 200

_JSON_TYPES = {"string", "integer", "number", "boolean", "array", "object"}
_PY_TYPES = {"str": "string", "int": "integer", "float": "number", "bool": "boolean",
             "list": "array", "dict": "object"}


def _annotation_type(annotation: Any) -> str | None:
    """JSON type for a simple annotation (``str``, ``"int | None"``, ``list[str]``)."""
    if annotation is inspect.Parameter.empty:
        return None
    # Plain classes render as their name; everything else (string annotations
    # from `from __future__ import annotations`, unions, generics) via str().
    # Don't use __name__ generally: on 3.14 unions report "Union".
    text = annotation.__name__ if isinstance(annotation, type) else str(annotation)
    text = text.replace("typing.", "")
    if text.startswith("Optional[") and text.endswith("]"):
        text = text[len("Optional["):-1]
    parts = [p.strip() for p in text.split("|")]
    names = {p.split("[")[0] for p in parts if p and p != "None"}
    if len(names) != 1:
        return None  # unions of real types stay unconstrained
    return _PY_TYPES.get(names.pop())


def _param_type(tool: Tool, name: str, annotation: Any) -> dict[str, Any]:
    declared = (tool.parameters or {}).get("properties", {}).get(name)
    if isinstance(declared, dict) and declared.get("type") in _JSON_TYPES:
        return {"type": declared["type"]}
    json_type = _annotation_type(annotation)
    return {"type": json_type} if json_type else {}  # else: unconstrained value


def tool_args_schema(tool: Tool) -> dict[str, Any]:
    """Object schema for ``tool``'s arguments, from its function signature."""
    properties: dict[str, Any] = {}
    required: list[str] = []
    try:
        signature = inspect.signature(tool.function)
    except (TypeError, ValueError):
        return {"type": "object"}
    for name, param in signature.parameters.items():
        if name in ("self", "cls") or param.kind in (
            inspect.Parameter.VAR_KEYWORD,
            inspect.Parameter.VAR_POSITIONAL,
        ):
            continue
        properties[name] = _param_type(tool, name, param.annotation)
        if param.default is inspect.Parameter.empty:
            required.append(name)
    schema: dict[str, Any] = {
        "type": "object",
        "properties": properties,
        "additionalProperties": False,
    }
    if required:
        schema["required"] = required
    return schema


def _branch(lead: str, tool_value: dict[str, Any], args: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            lead: {"type": "string", "maxLength": LEAD_MAX_CHARS},
            "tool": tool_value,
            "args": args,
        },
        "required": [lead, "tool", "args"],
        "additionalProperties": False,
    }


def build_action_schema(tools: Iterable[Tool], lead: str = "intent") -> dict[str, Any]:
    """Schema for one agent action over ``tools`` plus ``FINISH``.

    ``lead`` is the reasoning key emitted first (``"plan"`` for the plan node,
    ``"intent"`` for the reflect node) so the model reasons before choosing.
    """
    ordered = sorted(tools, key=lambda t: t.name)
    finish_args = {
        "type": "object",
        "properties": {"answer": {"type": "string"}},
        "required": ["answer"],
        "additionalProperties": False,
    }
    if len(ordered) > MAX_PER_TOOL_BRANCHES:
        return {
            "anyOf": [
                _branch(lead, {"enum": [t.name for t in ordered]}, {"type": "object"}),
                _branch(lead, {"const": FINISH}, finish_args),
            ]
        }
    branches = [_branch(lead, {"const": t.name}, tool_args_schema(t)) for t in ordered]
    branches.append(_branch(lead, {"const": FINISH}, finish_args))
    return {"anyOf": branches}
