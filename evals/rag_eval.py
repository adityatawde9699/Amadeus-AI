"""
Workspace-RAG eval: recall@k and MRR for ``WorkspaceIndexer`` over ``wiki/``.

Builds a throwaway index of the corpus named in ``datasets/rag_queries.yaml``
and ranks *files* (best chunk per file) three ways:

* ``hybrid`` — ``WorkspaceIndexer.search`` (BM25 + dense, RRF k=60) as shipped;
* ``bm25``   — lexical scores only;
* ``dense``  — embedding cosine only.

If hybrid does not beat both single retrievers, the fusion is not earning its
cost. Needs the ONNX embedder (``scripts/export_embedding_onnx.py``) or
sentence-transformers.

    uv run python -m evals.rag_eval [--model-dir Model]
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path
from typing import Any

import yaml


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DATASET = Path(__file__).parent / "datasets" / "rag_queries.yaml"
KS = (1, 3, 5)
MODES = ("hybrid", "bm25", "dense")


def _dedupe_files(paths: list[str]) -> list[str]:
    seen: list[str] = []
    for p in paths:
        name = Path(p).name
        if name not in seen:
            seen.append(name)
    return seen


def _rank_files(indexer: Any, query: str, mode: str) -> list[str]:
    import numpy as np

    from src.infra.workspace_indexer import _bm25_tokenize

    if mode == "hybrid":
        return _dedupe_files([r.file_path for r in indexer.search(query, top_k=50)])
    if mode == "bm25":
        scores = np.asarray(indexer._bm25.get_scores(_bm25_tokenize(query)))
    else:
        q = indexer._embed_model.encode(query, normalize_embeddings=True)
        scores = np.asarray(indexer._matrix @ q)
    order = np.argsort(scores)[::-1]
    return _dedupe_files([indexer._manifest[i]["file"] for i in order])


def score(rankings: list[list[str]], relevant: list[set[str]]) -> dict[str, float]:
    out: dict[str, float] = {}
    n = len(rankings)
    for k in KS:
        out[f"recall@{k}"] = sum(bool(set(r[:k]) & rel) for r, rel in zip(rankings, relevant, strict=True)) / n
    rr = []
    for r, rel in zip(rankings, relevant, strict=True):
        rank = next((i + 1 for i, f in enumerate(r) if f in rel), None)
        rr.append(1 / rank if rank else 0.0)
    out["mrr"] = sum(rr) / n
    return out


def build_indexer(corpus: Path, index_dir: Path, model_dir: Path | None) -> Any:
    from src.infra.workspace_indexer import WorkspaceIndexer

    indexer = WorkspaceIndexer(root=corpus, index_dir=index_dir, max_chunks=0)
    if model_dir is not None:
        from src.infra.embeddings.onnx_embedder import OnnxEmbedder

        indexer._embed_model = OnnxEmbedder(model_dir / "embed" / "all-MiniLM-L6-v2-onnx")
    indexer.build(force=True)
    if not indexer.is_ready:
        raise RuntimeError("index did not build — no embedding model available?")
    return indexer


def run(model_dir: Path | None = None, dataset: Path = DATASET) -> dict:
    spec = yaml.safe_load(dataset.read_text(encoding="utf-8"))
    corpus = ROOT / spec["corpus"]
    queries = spec["queries"]
    with tempfile.TemporaryDirectory() as tmp:
        indexer = build_indexer(corpus, Path(tmp), model_dir)
        relevant = [set(q["relevant"]) for q in queries]
        report: dict[str, Any] = {"n": len(queries), "chunks": indexer.chunk_count, "modes": {}}
        misses: list[dict] = []
        for mode in MODES:
            rankings = [_rank_files(indexer, q["q"], mode) for q in queries]
            report["modes"][mode] = score(rankings, relevant)
            if mode == "hybrid":
                misses = [
                    {"query": q["q"], "relevant": q["relevant"], "top3": r[:3]}
                    for q, r, rel in zip(queries, rankings, relevant, strict=True)
                    if not set(r[:3]) & rel
                ]
        report["hybrid_misses_at_3"] = misses
    return report


def render(report: dict) -> str:
    lines = [
        "# Workspace RAG eval — wiki corpus",
        "",
        f"{report['n']} queries, {report['chunks']} chunks. File-level ranking.",
        "",
        "| Retriever | Recall@1 | Recall@3 | Recall@5 | MRR |",
        "|---|---|---|---|---|",
    ]
    for mode, m in report["modes"].items():
        lines.append(f"| {mode} | {m['recall@1']:.0%} | {m['recall@3']:.0%} | "
                     f"{m['recall@5']:.0%} | {m['mrr']:.3f} |")
    lines += ["", "## Hybrid misses (not in top 3)", ""]
    lines += [f"- `{m['query']}` — wanted {', '.join(m['relevant'])}; got {', '.join(m['top3'])}"
              for m in report["hybrid_misses_at_3"]] or ["- none"]
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    parser.add_argument("--model-dir", type=Path, help="dir containing embed/all-MiniLM-L6-v2-onnx")
    parser.add_argument("--json", type=Path)
    parser.add_argument("--markdown", type=Path)
    args = parser.parse_args()
    import logging

    logging.disable(logging.WARNING)
    report = run(args.model_dir)
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
