"""
Agent tool-selection eval: does the LangGraph agent pick the right first tool
with the right arguments?

Runs every case in ``datasets/agent_tasks.yaml`` through the real
``AmadeusGraph`` and the real tool registry (70 tools), with the local
llama.cpp model as the LLM, in four configurations:

    expert / generalist  x  grammar (JSON-schema constrained) / free (json_object)

Nothing executes: a recording executor captures the first call and returns a
stub observation, and ``max_iterations=1`` stops the run there. The process
pins an isolated temp SQLite DB and blanks cloud keys before importing ``src``,
so it never touches a real database or provider.

    uv run python -m evals.agent_eval [--model Model/<file>.gguf] [--limit N]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


ROOT = Path(__file__).resolve().parents[1]
DATASET = Path(__file__).parent / "datasets" / "agent_tasks.yaml"
DEFAULT_MODEL = ROOT / "Model" / "Qwen_Qwen3-4B-Instruct-2507-Q4_K_M.gguf"


@dataclass
class Case:
    task: str
    expert: str
    expect: list[str]
    args: dict[str, str] = field(default_factory=dict)


def load_cases(path: Path = DATASET) -> list[Case]:
    return [Case(**raw) for raw in yaml.safe_load(path.read_text(encoding="utf-8"))]


def judge(case: Case, tool: str | None, args: dict[str, Any]) -> tuple[bool, str]:
    """Pass iff the first tool is expected and each arg check matches."""
    if not tool:
        return False, "no tool call (FINISH or error)"
    if tool not in case.expect:
        return False, f"wrong tool {tool}"
    for keys, needle in case.args.items():
        values = [args[k] for k in keys.split("|") if k in args]
        if not values:
            return False, f"missing arg {keys}"
        if not any(str(needle).lower() in str(v).lower() for v in values):
            return False, f"arg {keys}={values[0]!r} lacks {needle!r}"
    return True, "ok"


def _isolate_env() -> None:
    tmp = tempfile.mkdtemp(prefix="amadeus-eval-")
    os.environ.update(
        DATABASE_URL=f"sqlite+aiosqlite:///{tmp}/eval.db",  # override, never setdefault
        DATA_DIR=tmp,
        REDIS_URL="redis://127.0.0.1:1/0",
        TELEGRAM_BOT_TOKEN="", GEMINI_API_KEY="", GROQ_API_KEY="", SENTRY_DSN="",
        ENABLE_MCP="false", LOCAL_ONLY_MODE="true", ENABLE_INGRAPH_HITL="false",
    )


class _RecordingExecutor:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    async def execute(self, tool: Any, args: dict, **_: Any) -> Any:
        self.calls.append((tool.name, dict(args)))
        return type("R", (), {"success": True, "result": f"[stub] {tool.name} ok",
                              "error_message": None})()


async def _run_case(registry: Any, llm_generate: Any, case: Case, expert: str) -> dict:
    from src.app.services.agent_loop import AmadeusGraph
    from src.core.domain.context import RequestContext
    from src.core.domain.models import PermissionProfile

    executor = _RecordingExecutor()
    graph = AmadeusGraph(tool_registry=registry, tool_executor=executor,
                         llm_generate=llm_generate, max_iterations=1)
    ctx = RequestContext(request_id="eval", session_id=f"eval-{time.monotonic_ns()}",
                         user_id="eval", permissions=PermissionProfile.SYSTEM_FULL)
    await graph.ainvoke(task=case.task, context=ctx, routing_intent="expert",
                        routing_target=expert, allow_orchestration=False)
    tool, args = executor.calls[0] if executor.calls else (None, {})
    ok, why = judge(case, tool, args)
    return {"task": case.task, "expert": expert, "tool": tool, "args": args,
            "pass": ok, "reason": why}


async def run(model: Path, limit: int | None = None, only: list[str] | None = None) -> dict:
    from src.container import _build_tool_registry
    from src.infra.llm.llama_cpp_adapter import LlamaCppAdapter

    cases = load_cases()[:limit]
    registry = _build_tool_registry()
    missing = {t for c in cases for t in c.expect if registry.get(t) is None}
    if missing:
        raise ValueError(f"dataset expects unregistered tools: {sorted(missing)}")

    adapter = LlamaCppAdapter(model_path=str(model), threads=os.cpu_count() or 4,
                              context_length=4096)

    async def grammar(prompt: str, structured: bool = False, json_schema: dict | None = None,
                      **_: Any) -> str:
        fmt: dict[str, Any] = {"type": "json_object"}
        if json_schema:
            fmt["schema"] = json_schema
        return await adapter.generate_response(prompt, temperature=0.1, max_tokens=256,
                                               response_format=fmt if structured else None)

    async def free(prompt: str, structured: bool = False) -> str:
        fmt = {"type": "json_object"} if structured else None
        return await adapter.generate_response(prompt, temperature=0.1, max_tokens=256,
                                               response_format=fmt)

    configs = {
        "expert+grammar": (grammar, None), "expert+free": (free, None),
        "generalist+grammar": (grammar, "generalist"), "generalist+free": (free, "generalist"),
    }
    if only:
        unknown = set(only) - set(configs)
        if unknown:
            raise ValueError(f"unknown configs {sorted(unknown)}; choose from {sorted(configs)}")
        configs = {k: v for k, v in configs.items() if k in only}
    report: dict[str, Any] = {"model": model.name, "n": len(cases), "configs": {}}
    for name, (fn, expert_override) in configs.items():
        start = time.monotonic()
        results = [await _run_case(registry, fn, c, expert_override or c.expert) for c in cases]
        report["configs"][name] = {
            "pass_rate": sum(r["pass"] for r in results) / len(results),
            "seconds": round(time.monotonic() - start, 1),
            "results": results,
        }
    return report


def render(report: dict) -> str:
    lines = [
        f"# Agent tool-selection eval — {report['model']}",
        "",
        f"{report['n']} tasks; first tool call + argument checks. Tools are not executed.",
        "",
        "| Config | Pass rate | Time |",
        "|---|---|---|",
    ]
    for name, c in report["configs"].items():
        lines.append(f"| {name} | {c['pass_rate']:.0%} | {c['seconds']}s |")
    for name, c in report["configs"].items():
        fails = [r for r in c["results"] if not r["pass"]]
        lines += ["", f"## Failures — {name}", ""]
        lines += [f"- `{r['task']}` — {r['reason']}"
                  + (f" (`{r['tool']}` {json.dumps(r['args'])})" if r["tool"] else "")
                  for r in fails] or ["- none"]
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    parser.add_argument("--model", type=Path, default=DEFAULT_MODEL)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--json", type=Path)
    parser.add_argument("--markdown", type=Path)
    parser.add_argument(
        "--configs",
        help="comma-separated subset, e.g. expert+grammar,generalist+grammar (default: all)",
    )
    args = parser.parse_args()
    if not args.model.exists():
        print(f"model not found: {args.model}", file=sys.stderr)
        return 2
    _isolate_env()
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    import logging

    logging.disable(logging.WARNING)
    only = [c.strip() for c in args.configs.split(",")] if args.configs else None
    report = asyncio.run(run(args.model, args.limit, only))
    text = render(report)
    print(text)
    for target, payload in ((args.markdown, text), (args.json, json.dumps(report, indent=2))):
        if target:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(payload, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
