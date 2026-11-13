"""WorkspaceIndexer end to end with a deterministic fake embedder.

The real embedder (ONNX MiniLM) is not in CI; a hashed bag-of-words embedder
exercises the real walking, chunking, incremental re-embedding, persistence,
BM25 and reciprocal-rank-fusion code paths.
"""

from __future__ import annotations

import os
import re
import time
from pathlib import Path

import numpy as np
import pytest

from src.infra.workspace_indexer import CHUNK_CHARS, SearchResult, WorkspaceIndexer


class FakeEmbedder:
    dim = 64

    def __init__(self) -> None:
        self.calls: list[int] = []  # number of texts per encode() of a list

    def _vec(self, text: str) -> np.ndarray:
        v = np.zeros(self.dim, dtype=np.float32)
        for tok in re.findall(r"[a-z0-9]+", text.lower()):
            v[hash(tok) % self.dim] += 1.0
        n = np.linalg.norm(v)
        return v / n if n else v

    def encode(self, sentences, **_):
        if isinstance(sentences, str):
            return self._vec(sentences)
        self.calls.append(len(sentences))
        return np.stack([self._vec(s) for s in sentences])


def _write(root, rel, text):
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


@pytest.fixture
def workspace(tmp_path):
    root = tmp_path / "ws"
    _write(
        root, "notes/kubernetes.md", "Kubernetes pods are scheduled onto nodes by the scheduler."
    )
    _write(
        root,
        "src/billing.py",
        "def compute_invoice_total(items):\n    return sum(i.price for i in items)\n",
    )
    _write(root, "recipes/pasta.txt", "Boil the pasta in salted water, then add tomato sauce.")
    _write(root, "node_modules/lib/index.js", "kubernetes kubernetes kubernetes")  # skipped dir
    _write(root, ".git/config", "kubernetes")  # hidden dir
    _write(root, "image.bin", "kubernetes")  # extension not indexed
    return root


def _indexer(root, tmp_path, embedder=None, **kw):
    idx = WorkspaceIndexer(root=root, index_dir=tmp_path / "index", **kw)
    idx._embed_model = embedder or FakeEmbedder()
    return idx


def test_build_search_and_skip_rules(workspace, tmp_path):
    idx = _indexer(workspace, tmp_path)
    idx.build()
    assert idx.is_ready and idx.chunk_count == 3
    files = {Path(m["file"]).name for m in idx._manifest}
    assert files == {"kubernetes.md", "billing.py", "pasta.txt"}

    hits = idx.search("how are kubernetes pods scheduled", top_k=2)
    assert hits and hits[0].file_path.endswith("kubernetes.md")
    assert hits[0].score > 0 and "kubernetes.md" in hits[0].format()
    assert idx.search("invoice total")[0].file_path.endswith("billing.py")


def test_incremental_rebuild_only_reembeds_changes(workspace, tmp_path):
    emb = FakeEmbedder()
    idx = _indexer(workspace, tmp_path, emb)
    idx.build()
    assert emb.calls == [3]

    idx.build()  # nothing changed
    assert emb.calls == [3]

    time.sleep(0.01)
    target = workspace / "recipes" / "pasta.txt"
    target.write_text("Risotto needs arborio rice and patience.", encoding="utf-8")
    os.utime(target, (time.time() + 5, time.time() + 5))
    (workspace / "src" / "billing.py").unlink()
    idx.build()
    assert emb.calls[-1] == 1  # only the edited file
    assert idx.chunk_count == 2
    assert idx.search("arborio risotto")[0].file_path.endswith("pasta.txt")

    idx.build(force=True)
    assert emb.calls[-1] == 2


def test_load_restores_persisted_index(workspace, tmp_path):
    _indexer(workspace, tmp_path).build()
    fresh = _indexer(workspace, tmp_path)
    assert fresh.load() is True and fresh.is_ready
    assert fresh.search("tomato sauce pasta")[0].file_path.endswith("pasta.txt")
    empty = _indexer(workspace, tmp_path / "nothing-here")
    assert empty.load() is False and empty.search("x") == []


def test_large_files_are_chunked_with_overlap(tmp_path):
    root = tmp_path / "ws"
    words = " ".join(f"word{i}" for i in range(1200))  # well over one chunk
    _write(root, "big.md", words)
    idx = _indexer(root, tmp_path)
    idx.build()
    assert idx.chunk_count >= len(words) // CHUNK_CHARS
    chunks = WorkspaceIndexer._chunk(words)
    first, second = chunks[0][0], chunks[1][0]
    assert first[-50:] in second  # overlap keeps context across boundaries


def test_max_chunks_cap(tmp_path):
    root = tmp_path / "ws"
    for i in range(6):
        _write(root, f"f{i}.txt", f"document number {i} about topic {i}")
    idx = _indexer(root, tmp_path, max_chunks=4)
    idx.build()
    assert idx.chunk_count == 4


def test_embedding_failure_leaves_index_unbuilt(workspace, tmp_path):
    class Broken(FakeEmbedder):
        def encode(self, sentences, **kw):
            if not isinstance(sentences, str):
                raise RuntimeError("model crashed")  # noqa: TRY004 - simulates a crash
            return super().encode(sentences, **kw)

    idx = _indexer(workspace, tmp_path, Broken())
    idx.build()
    assert not idx.is_ready and idx.search("kubernetes") == []


def test_search_result_format_shows_ranks():
    r = SearchResult("/a/b/notes.md", "  hello  ", 3, 0.0321, semantic_rank=0, bm25_rank=2)
    text = r.format()
    assert text.startswith("[notes.md : line 3] (rrf=0.0321 [sem_rank=0, bm25_rank=2])")
    assert text.endswith("hello") and "notes.md" in repr(r)
