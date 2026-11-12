"""
Routing eval: Stage-1 category classifier on held-out data.

Two numbers, kept separate on purpose:

* **held-out** — the classifier trained on all of TRAINING_DATA, scored on
  ``datasets/routing_heldout.yaml`` (phrasings never seen in training). This is
  the number that predicts real behaviour.
* **cross-validation** — stratified k-fold over TRAINING_DATA itself, with the
  same hyper-parameters as ``CategoryClassifier.train``. In-distribution; it
  mostly measures how templated the training phrases are.

Reports accuracy, macro-F1, top-2 accuracy (the semantic router narrows to the
top-2 categories), *profile* accuracy (a category mistake that lands in the same
expert profile is harmless) and a confusion matrix. Needs scikit-learn (dev).

    uv run python -m evals.routing_eval [--json evals/results/routing.json]
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any

import yaml


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.app.services.category_classifier import TRAINING_DATA, CategoryClassifier
from src.core.domain.agent_profiles import get_profile_for_category
from src.infra.tools.base import ToolCategory


DATASET = Path(__file__).parent / "datasets" / "routing_heldout.yaml"


def load_heldout(path: Path = DATASET) -> list[tuple[str, str]]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    pairs = [(q, cat) for cat, queries in data.items() for q in queries]
    training = {p.lower().strip() for phrases in TRAINING_DATA.values() for p in phrases}
    leaked = [q for q, _ in pairs if q.lower().strip() in training]
    if leaked:
        raise ValueError(f"held-out queries also in TRAINING_DATA: {leaked}")
    unknown = {c for _, c in pairs} - set(TRAINING_DATA)
    if unknown:
        raise ValueError(f"unknown categories in dataset: {sorted(unknown)}")
    return pairs


def _profile(category: str) -> str:
    try:
        return get_profile_for_category(ToolCategory(category)).name
    except ValueError:
        return "generalist"


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


def heldout_eval(pairs: list[tuple[str, str]]) -> dict:
    with tempfile.TemporaryDirectory() as tmp:
        clf = CategoryClassifier(model_dir=tmp)
        clf.train()
        if not clf.load():
            raise RuntimeError("classifier did not train (is scikit-learn installed?)")
        gold = [c for _, c in pairs]
        pred = [clf.predict(q)[0] for q, _ in pairs]
        top2 = [clf.predict_top2(q) for q, _ in pairs]
    result = metrics(gold, pred, top2)
    result["errors"] = [
        {"query": q, "gold": g, "pred": p}
        for (q, g), p in zip(pairs, pred, strict=True) if g != p
    ]
    return result


def cross_validation(folds: int = 5, seed: int = 0) -> dict:
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.model_selection import StratifiedKFold
    from sklearn.svm import LinearSVC

    texts = [p for phrases in TRAINING_DATA.values() for p in phrases]
    labels = [c for c, phrases in TRAINING_DATA.items() for _ in phrases]
    gold: list[str] = []
    pred: list[str] = []
    splitter = StratifiedKFold(n_splits=folds, shuffle=True, random_state=seed)
    for train_idx, test_idx in splitter.split(texts, labels):
        # Mirrors CategoryClassifier.train hyper-parameters.
        vec = TfidfVectorizer(analyzer="word", ngram_range=(1, 2), sublinear_tf=True, min_df=1)
        x_train = vec.fit_transform([texts[i] for i in train_idx])
        svm = LinearSVC(C=1.0, max_iter=2000, class_weight="balanced")
        svm.fit(x_train, [labels[i] for i in train_idx])
        pred.extend(svm.predict(vec.transform([texts[i] for i in test_idx])))
        gold.extend(labels[i] for i in test_idx)
    result = metrics(gold, [str(p) for p in pred])
    result["folds"] = folds
    return result


def render(report: dict) -> str:
    h, cv = report["heldout"], report["cross_validation"]
    lines = [
        "# Routing eval — Stage-1 category classifier",
        "",
        "| Split | n | Accuracy | Macro-F1 | Top-2 acc | Profile acc |",
        "|---|---|---|---|---|---|",
        f"| Held-out | {h['n']} | {h['accuracy']:.1%} | {h['macro_f1']:.3f} | "
        f"{h['top2_accuracy']:.1%} | {h['profile_accuracy']:.1%} |",
        f"| {cv['folds']}-fold CV (train set) | {cv['n']} | {cv['accuracy']:.1%} | "
        f"{cv['macro_f1']:.3f} | – | {cv['profile_accuracy']:.1%} |",
        "",
        "## Held-out recall by category",
        "",
        "| Category | Recall | Precision | Support |",
        "|---|---|---|---|",
    ]
    for cat, m in sorted(h["per_class"].items(), key=lambda kv: kv[1]["recall"]):
        if m["support"]:
            lines.append(f"| {cat} | {m['recall']:.0%} | {m['precision']:.0%} | {m['support']} |")
    lines += ["", "## Held-out errors", ""]
    lines += [f"- `{e['query']}` — gold **{e['gold']}**, predicted {e['pred']}"
              for e in h["errors"]] or ["- none"]
    return "\n".join(lines) + "\n"


def run() -> dict:
    return {"heldout": heldout_eval(load_heldout()), "cross_validation": cross_validation()}


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
