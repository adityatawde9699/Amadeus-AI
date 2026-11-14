"""
Routing eval: the LLM-free intent router on held-out data.

Three numbers, kept separate on purpose:

* **category** - the category head on ``datasets/routing_heldout.yaml``
  (phrasings never seen in training): accuracy, macro-F1, top-2 accuracy and
  *profile* accuracy (a mistake that lands in the same expert is harmless).
* **end to end** - ``datasets/routing_e2e.yaml`` through the whole LLM-free
  path: route, then rule-based arguments. Reports how many requests finish
  with no LLM call, how many of those are right, and wrong direct dispatches
  (the costly error: a tool runs that should not have).
* **cross-validation** - k-fold over the training phrases; in-distribution, it
  mostly measures how templated the phrases are.

    uv run python -m evals.routing_eval [--json evals/results/routing.json]
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any

import yaml


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.app.services.intent_router import IntentRouter, train_softmax
from src.app.services.routing_data import CHAT_INTENTS, GLOBAL_INTENTS, TOOL_EXAMPLES, TRAINING_DATA
from src.core.domain.agent_profiles import get_profile_for_category
from src.infra.tools.base import ToolCategory


DATASET = Path(__file__).parent / "datasets" / "routing_heldout.yaml"
E2E_DATASET = Path(__file__).parent / "datasets" / "routing_e2e.yaml"


def _training_phrases() -> set[str]:
    tables = (TRAINING_DATA, GLOBAL_INTENTS, TOOL_EXAMPLES)
    return {p.lower().strip() for table in tables for phrases in table.values() for p in phrases}


def load_heldout(path: Path = DATASET) -> list[tuple[str, str]]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    pairs = [(q, cat) for cat, queries in data.items() for q in queries]
    training = _training_phrases()
    leaked = [q for q, _ in pairs if q.lower().strip() in training]
    if leaked:
        raise ValueError(f"held-out queries also in the training phrases: {leaked}")
    unknown = {c for _, c in pairs} - set(TRAINING_DATA) - set(GLOBAL_INTENTS)
    if unknown:
        raise ValueError(f"unknown categories in dataset: {sorted(unknown)}")
    return pairs


def load_e2e(path: Path = E2E_DATASET) -> list[dict[str, Any]]:
    cases = yaml.safe_load(path.read_text(encoding="utf-8"))
    training = _training_phrases()
    leaked = [c["q"] for c in cases if c["q"].lower().strip() in training]
    if leaked:
        raise ValueError(f"end-to-end queries also in the training phrases: {leaked}")
    return list(cases)


def build_router() -> tuple[IntentRouter, Any]:
    """The production router over the real tool registry."""
    from src.container import _build_tool_registry

    registry = _build_tool_registry()
    router = IntentRouter(registry, model_dir=ROOT / "Model")
    router.build()
    if not router.is_ready:
        raise RuntimeError("intent router did not build (is an embedding backend installed?)")
    return router, registry


def _profile(category: str) -> str:
    if category in CHAT_INTENTS:
        return "chat"
    try:
        name = get_profile_for_category(ToolCategory(category)).name
    except ValueError:
        return "chat"
    return "chat" if name == "generalist" else name


def metrics(gold: list[str], pred: list[str], top2: list[list[str]] | None = None) -> dict:
    labels = sorted(set(gold) | set(pred))
    n = len(gold)
    per_class: dict[str, dict[str, float]] = {}
    for label in labels:
        tp = sum(g == p == label for g, p in zip(gold, pred, strict=True))
        fp = sum(p == label != g for g, p in zip(gold, pred, strict=True))
        fn = sum(g == label != p for g, p in zip(gold, pred, strict=True))
        precision = tp / (tp + fp) if tp + fp else 0.0
        recall = tp / (tp + fn) if tp + fn else 0.0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        per_class[label] = {"precision": precision, "recall": recall, "f1": f1,
                            "support": sum(g == label for g in gold)}
    gold_labels = sorted(set(gold))
    out: dict[str, Any] = {
        "n": n,
        "accuracy": sum(g == p for g, p in zip(gold, pred, strict=True)) / n,
        "macro_f1": sum(per_class[c]["f1"] for c in gold_labels) / len(gold_labels),
        "profile_accuracy": sum(
            _profile(g) == _profile(p) for g, p in zip(gold, pred, strict=True)
        ) / n,
        "per_class": per_class,
        "confusions": Counter(
            f"{g} -> {p}" for g, p in zip(gold, pred, strict=True) if g != p
        ).most_common(),
    }
    if top2 is not None:
        out["top2_accuracy"] = sum(g in t for g, t in zip(gold, top2, strict=True)) / n
    return out


def heldout_eval(pairs: list[tuple[str, str]], router: IntentRouter | None = None) -> dict:
    router = router or build_router()[0]
    gold = [c for _, c in pairs]
    pred: list[str] = []
    top2: list[list[str]] = []
    for query, _ in pairs:
        probs = router.category_probabilities(query)
        ranked = sorted(probs, key=lambda c: probs[c], reverse=True)
        pred.append(ranked[0])
        top2.append(ranked[:2])
    result = metrics(gold, pred, top2)
    result["errors"] = [
        {"query": q, "gold": g, "pred": p}
        for (q, g), p in zip(pairs, pred, strict=True) if g != p
    ]
    return result


def _args_ok(case: dict[str, Any], args: dict[str, Any]) -> bool:
    for keys, needle in (case.get("args") or {}).items():
        values = [args[k] for k in keys.split("|") if k in args]
        if not any(str(needle).lower() in str(v).lower() for v in values):
            return False
    return True


def e2e_eval(cases: list[dict[str, Any]], router: IntentRouter, registry: Any) -> dict:
    """Route + rule-based arguments. Outcome per case:

    * ``direct_ok``   - dispatched with no LLM call, right tool and arguments
    * ``direct_bad``  - dispatched with no LLM call, wrong tool or arguments
    * ``llm_ok``      - handed to the right place for the LLM (expert that owns
      an expected tool, or the right chat intent)
    * ``llm_bad``     - handed to the wrong expert / wrong intent
    """
    from src.app.services.slot_extractor import extract_slots

    outcomes: Counter[str] = Counter()
    rows: list[dict[str, Any]] = []
    latencies: list[float] = []
    for case in cases:
        query = case["q"]
        start = time.perf_counter()
        decision = router.route(query)
        kind, target = decision.kind, decision.target
        args: dict[str, Any] | None = None
        if kind == "tool" and target:
            args = extract_slots(target, query, registry)
            if args is None:  # arguments need the LLM: the service uses the expert
                expert = router.expert_for(decision.category)
                kind, target = ("expert", expert) if expert else ("conversational", None)
        latencies.append(time.perf_counter() - start)

        expect: list[str] = case.get("expect") or []
        if kind == "tool":
            good = target in expect and _args_ok(case, args or {})
            outcome = "direct_ok" if good else "direct_bad"
        elif case.get("intent"):
            outcome = "llm_ok" if kind in CHAT_INTENTS else "llm_bad"
        elif case.get("needs_llm"):
            outcome = "llm_ok" if kind == "expert" or kind in CHAT_INTENTS else "llm_bad"
        else:
            owners = {
                _profile(str(getattr(t.category, "value", t.category)))
                for t in map(registry.get, expect) if t is not None
            }
            outcome = "llm_ok" if kind == "expert" and target in owners else "llm_bad"
        outcomes[outcome] += 1
        rows.append({"query": query, "outcome": outcome, "kind": kind, "target": target,
                     "args": args, "reason": decision.reason,
                     "confidence": round(decision.confidence, 3),
                     "tool_margin": round(decision.tool_margin, 3)})

    n = len(cases)
    tool_cases = sum(1 for c in cases if c.get("expect"))
    direct = outcomes["direct_ok"] + outcomes["direct_bad"]
    latencies.sort()
    return {
        "n": n,
        "tool_cases": tool_cases,
        "outcomes": dict(outcomes),
        "correct": (outcomes["direct_ok"] + outcomes["llm_ok"]) / n,
        "llm_free_rate": outcomes["direct_ok"] / tool_cases if tool_cases else 0.0,
        "direct_precision": outcomes["direct_ok"] / direct if direct else 1.0,
        "wrong_dispatches": outcomes["direct_bad"],
        "latency_ms_p50": round(latencies[len(latencies) // 2] * 1000, 2),
        "latency_ms_p95": round(latencies[int(len(latencies) * 0.95)] * 1000, 2),
        "failures": [r for r in rows if r["outcome"].endswith("bad")],
        "needs_llm": [r for r in rows if r["outcome"] == "llm_ok" and r["kind"] == "expert"],
        "rows": rows,
    }


def cross_validation(router: IntentRouter, folds: int = 5, seed: int = 0) -> dict:
    """Stratified k-fold of the category head over its own training phrases."""
    import numpy as np

    texts, labels, _, _ = router._training_sets()
    x = router._embed_cached(texts + router._training_sets()[2])[: len(texts)]
    rng = np.random.default_rng(seed)
    fold_of = np.zeros(len(labels), dtype=int)
    for label in set(labels):
        idx = [i for i, lab in enumerate(labels) if lab == label]
        rng.shuffle(idx)
        for pos, i in enumerate(idx):
            fold_of[i] = pos % folds
    gold: list[str] = []
    pred: list[str] = []
    for fold in range(folds):
        train = np.where(fold_of != fold)[0]
        test = np.where(fold_of == fold)[0]
        classes, w, b = train_softmax(x[train], [labels[i] for i in train])
        scores = x[test] @ w.T + b
        pred.extend(classes[i] for i in scores.argmax(axis=1))
        gold.extend(labels[i] for i in test)
    result = metrics(gold, pred)
    result["folds"] = folds
    return result


def render(report: dict) -> str:
    h, cv, e = report["heldout"], report["cross_validation"], report["e2e"]
    o = e["outcomes"]
    lines = [
        "# Routing eval - LLM-free intent router",
        "",
        "## Category head",
        "",
        "| Split | n | Accuracy | Macro-F1 | Top-2 acc | Profile acc |",
        "|---|---|---|---|---|---|",
        f"| Held-out | {h['n']} | {h['accuracy']:.1%} | {h['macro_f1']:.3f} | "
        f"{h['top2_accuracy']:.1%} | {h['profile_accuracy']:.1%} |",
        f"| {cv['folds']}-fold CV (training phrases) | {cv['n']} | {cv['accuracy']:.1%} | "
        f"{cv['macro_f1']:.3f} | - | {cv['profile_accuracy']:.1%} |",
        "",
        "## End to end (route + rule-based arguments, no LLM)",
        "",
        f"{e['n']} held-out requests, {e['tool_cases']} of them answerable by one tool.",
        "",
        "| Metric | Value |",
        "|---|---|",
        f"| Handled correctly overall | {e['correct']:.1%} |",
        f"| Tool requests finished with **no LLM call** | {e['llm_free_rate']:.1%} "
        f"({o.get('direct_ok', 0)}/{e['tool_cases']}) |",
        f"| Direct dispatches that were right | {e['direct_precision']:.1%} |",
        f"| Wrong direct dispatches | {e['wrong_dispatches']} |",
        f"| Sent to the right expert / chat intent | {o.get('llm_ok', 0)} |",
        f"| Sent to the wrong expert / intent | {o.get('llm_bad', 0)} |",
        f"| Routing latency p50 / p95 | {e['latency_ms_p50']} ms / {e['latency_ms_p95']} ms |",
        "",
        "### Failures",
        "",
    ]
    lines += [
        f"- `{r['query']}` - {r['outcome']}: {r['kind']}:{r['target']}"
        + (f" {json.dumps(r['args'])}" if r["args"] is not None else "")
        for r in e["failures"]
    ] or ["- none"]
    lines += ["", "### Correctly deferred to the LLM (tool requests)", ""]
    lines += [f"- `{r['query']}` - {r['target']} ({r['reason']})" for r in e["needs_llm"]
              if r["target"]] or ["- none"]
    lines += [
        "",
        "## Held-out recall by category",
        "",
        "| Category | Recall | Precision | Support |",
        "|---|---|---|---|",
    ]
    for cat, m in sorted(h["per_class"].items(), key=lambda kv: kv[1]["recall"]):
        if m["support"]:
            lines.append(f"| {cat} | {m['recall']:.0%} | {m['precision']:.0%} | {m['support']} |")
    lines += ["", "## Held-out category errors", ""]
    lines += [f"- `{x['query']}` - gold **{x['gold']}**, predicted {x['pred']}"
              for x in h["errors"]] or ["- none"]
    return "\n".join(lines) + "\n"


def run() -> dict:
    router, registry = build_router()
    return {
        "heldout": heldout_eval(load_heldout(), router),
        "e2e": e2e_eval(load_e2e(), router, registry),
        "cross_validation": cross_validation(router),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    parser.add_argument("--json", type=Path, help="also write the full report as JSON")
    parser.add_argument("--markdown", type=Path, help="write the markdown report here")
    args = parser.parse_args()
    import logging

    logging.disable(logging.INFO)
    report = run()
    text = render(report)
    print(text)
    if args.markdown:
        args.markdown.parent.mkdir(parents=True, exist_ok=True)
        args.markdown.write_text(text, encoding="utf-8")
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
