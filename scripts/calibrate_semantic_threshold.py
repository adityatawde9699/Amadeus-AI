"""
Offline calibration utility for UnifiedSemanticRouter threshold tuning.

Run:
    python scripts/calibrate_semantic_threshold.py
    python scripts/calibrate_semantic_threshold.py --dataset data/semantic_router_labels.jsonl
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.append(str(PROJECT_ROOT))

from src.app.services.semantic_router import UnifiedSemanticRouter
from src.app.services.tool_registry import ToolRegistry

DEFAULT_DATASET_PATH = Path("data") / "semantic_router_labels.jsonl"


@dataclass(frozen=True)
class LabeledQuery:
    text: str
    expected_intent: str  # "tool", "conversational", or "cloud_escalation"
    expected_tool: str | None = None

    @property
    def key(self) -> str:
        if self.expected_intent == "tool":
            return f"tool:{self.expected_tool}"
        return self.expected_intent


def _default_labeled_queries() -> list[LabeledQuery]:
    return [
        LabeledQuery("check my cpu usage", "tool", "get_cpu_usage"),
        LabeledQuery("what's the weather in mumbai", "tool", "get_weather"),
        LabeledQuery("news headlines today", "tool", "get_news"),
        LabeledQuery("search wikipedia for alan turing", "tool", "wikipedia_search"),
        LabeledQuery("hello there", "conversational"),
        LabeledQuery("thank you", "conversational"),
        LabeledQuery("how are you doing", "conversational"),
        LabeledQuery("debug my fastapi startup stacktrace", "cloud_escalation"),
        LabeledQuery("design a distributed architecture with failover", "cloud_escalation"),
        LabeledQuery("perform threat modeling for my api", "cloud_escalation"),
    ]


def _load_dataset(path: Path) -> list[LabeledQuery]:
    if not path.exists():
        return _default_labeled_queries()

    samples: list[LabeledQuery] = []
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        payload = json.loads(line)
        samples.append(
            LabeledQuery(
                text=str(payload["text"]).strip(),
                expected_intent=str(payload["expected_intent"]).strip(),
                expected_tool=payload.get("expected_tool"),
            )
        )

    if not samples:
        raise ValueError(f"Dataset is empty: {path}")
    return samples


def _validate_samples(samples: list[LabeledQuery]) -> None:
    allowed_intents = {"tool", "conversational", "cloud_escalation"}
    for idx, sample in enumerate(samples, start=1):
        if sample.expected_intent not in allowed_intents:
            raise ValueError(
                f"Invalid expected_intent '{sample.expected_intent}' at sample #{idx}. "
                f"Allowed: {sorted(allowed_intents)}"
            )
        if sample.expected_intent == "tool" and not sample.expected_tool:
            raise ValueError(f"Missing expected_tool for tool sample at #{idx}")


def _prediction_key(predicted_intent: str, predicted_tool: str | None) -> str:
    if predicted_intent == "tool":
        return f"tool:{predicted_tool}"
    return predicted_intent


def evaluate_threshold(
    registry: ToolRegistry, samples: list[LabeledQuery], threshold: float
) -> tuple[float, float, float, int]:
    router = UnifiedSemanticRouter(registry=registry, threshold=threshold)
    router.build_index()
    if not router.is_ready:
        raise RuntimeError("Router could not be initialized. Verify embedding dependencies.")

    correct = 0
    for sample in samples:
        predicted_intent, predicted_tool = router.route(sample.text)
        if _prediction_key(predicted_intent, predicted_tool) == sample.key:
            correct += 1

    total = len(samples)
    accuracy = correct / total
    # For single-label multiclass classification, micro-precision/recall/F1 = accuracy.
    micro_precision = accuracy
    micro_recall = accuracy
    micro_f1 = accuracy
    return micro_f1, micro_precision, micro_recall, correct


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Calibrate semantic router threshold.")
    parser.add_argument(
        "--dataset",
        type=Path,
        default=DEFAULT_DATASET_PATH,
        help="JSONL dataset with fields: text, expected_intent, expected_tool(optional)",
    )
    parser.add_argument("--start", type=float, default=0.05, help="Scan range start (inclusive)")
    parser.add_argument("--stop", type=float, default=0.95, help="Scan range stop (inclusive)")
    parser.add_argument("--step", type=float, default=0.01, help="Scan step size")
    parser.add_argument("--top-k", type=int, default=5, help="Show top K threshold candidates")
    return parser


def _build_registry_for_calibration() -> ToolRegistry:
    registry = ToolRegistry()
    # Keep this import path lightweight so the script runs even when
    # optional API/server deps are not installed.
    from src.infra.tools.info_tools import get_info_tools
    from src.infra.tools.monitor_tools import get_monitor_tools
    from src.infra.tools.productivity_tools import get_productivity_tools
    from src.infra.tools.system_tools import get_system_tools

    for tool in get_info_tools():
        registry.register(tool)
    for tool in get_system_tools():
        registry.register(tool)
    for tool in get_monitor_tools():
        registry.register(tool)
    for tool in get_productivity_tools():
        registry.register(tool)
    return registry


def main() -> None:
    args = _build_parser().parse_args()
    if args.step <= 0:
        raise ValueError("--step must be > 0")
    if args.start > args.stop:
        raise ValueError("--start must be <= --stop")

    samples = _load_dataset(args.dataset)
    _validate_samples(samples)
    registry = _build_registry_for_calibration()

    print("Loaded %d labeled samples from %s" % (len(samples), args.dataset))

    results: list[tuple[float, float, float, float, int]] = []
    threshold = args.start
    while threshold <= args.stop + 1e-9:
        f1, precision, recall, correct = evaluate_threshold(
            registry=registry,
            samples=samples,
            threshold=threshold,
        )
        results.append((threshold, f1, precision, recall, correct))
        threshold += args.step

    results.sort(key=lambda row: (row[1], row[4], -row[0]), reverse=True)
    best_threshold, best_f1, best_precision, best_recall, best_correct = results[0]

    total = len(samples)
    print(
        "Best threshold=%.2f | micro-F1=%.3f | precision=%.3f | recall=%.3f | accuracy=%d/%d"
        % (best_threshold, best_f1, best_precision, best_recall, best_correct, total)
    )
    print("Top candidates:")
    for cand_threshold, cand_f1, _, _, cand_correct in results[: args.top_k]:
        print(
            "  threshold=%.2f | micro-F1=%.3f | accuracy=%d/%d"
            % (cand_threshold, cand_f1, cand_correct, total)
        )

    print("\nRecommended env override:")
    print("  SEMANTIC_ROUTER_THRESHOLD=%.2f" % best_threshold)


if __name__ == "__main__":
    main()
