"""
Omni-Workspace Indexer for Amadeus AI — Hybrid BM25 + Semantic Search.

Dual-retrieval architecture:
  1. Dense semantic search  — sentence-transformers/all-mpnet-base-v2 (768-dim)
                              Excellent at conceptual / meaning-based queries.
  2. Lexical BM25 search    — rank_bm25.BM25Okapi
                              Excellent at exact variable names, API keys,
                              error codes, UUIDs, specific identifiers.

Both ranked lists are fused into a single result using Reciprocal Rank
Fusion (RRF):
    rrf_score = 1/(k + rank_semantic) + 1/(k + rank_bm25)   [k=60]

This eliminates the core weakness of pure dense search: it will now find
AUTH_UUID_7392, DockerCompose port 8080, or a specific stack trace token
even when the embedding vector has no idea what those literals mean.

Index layout (data/workspace_index/):
    embeddings.npz   - float32 matrix (N_chunks x 768)
    manifest.json    — chunk metadata: file path, line, mtime, snippet, hash
    chunks.json      — full chunk texts (used to rebuild BM25 in-memory on load)

Supported file types:
    .py, .md, .txt, .toml, .yaml, .yml, .env, .json, .cfg, .ini, .rst, .pdf

Trade-offs:
    + Finds exact tokens (variable names, keys, error codes) that dense
      search misses.
    + BM25 index is pure RAM; no disk writes needed (cheap to rebuild from
      chunks.json in ~1s for most workspaces).
        - chunks.json adds storage: ~1 char per char indexed. A 10 MB codebase
            -> ~10 MB chunks.json. Negligible for personal workspaces.
        - RAM cost: ~1 byte/char of tokenised corpus. Typically 20-80 MB.
    - rank_bm25 must be installed (pip install rank-bm25). Graceful fallback
      to pure semantic search if missing.

Usage:
    indexer = WorkspaceIndexer(root="C:/Users/ASUS")
    indexer.build()                          # full build / incremental update
    results = indexer.search("what port does amadeus expose?", top_k=5)
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
from pathlib import Path
from typing import Any


logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

INCLUDE_EXTENSIONS: frozenset[str] = frozenset(
    {".py", ".md", ".txt", ".toml", ".yaml", ".yml", ".env",
     ".json", ".cfg", ".ini", ".rst", ".pdf"}
)

# Directories never worth indexing
SKIP_DIRS: frozenset[str] = frozenset(
    {
        ".git", ".svn", ".hg",
        ".venv", "venv", "env", "amadeus_venv",
        "__pycache__", ".mypy_cache", ".ruff_cache", ".pytest_cache",
        "node_modules", ".npm",
        "dist", "build", "_build", "buck-out",
        ".idea", ".vscode",
        "site-packages",
        "migrations",
    }
)

MAX_FILE_BYTES = 512_000   # 512 KB — skip huge auto-generated files
CHUNK_CHARS = 1_500        # characters per chunk
CHUNK_OVERLAP = 200        # character overlap between adjacent chunks

_EMBED_MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"
_DEFAULT_INDEX_DIR = Path("data") / "workspace_index"

# RRF constant (60 is the standard; higher → semantic/lexical ranks matter less)
_RRF_K = 60


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _bm25_tokenize(text: str) -> list[str]:
    """
    Fast, code-aware BM25 tokeniser.

    Keeps underscores within tokens so identifiers like AUTH_UUID_7392 or
    MEMORY_PERSIST_DIR survive as a single token rather than being split
    into meaningless fragments. Case-folded for recall.
    """
    return re.findall(r"[a-z0-9_]+", text.lower())


def _rrf_score(rank: int, k: int = _RRF_K) -> float:
    """Reciprocal Rank Fusion contribution for a single ranked list."""
    return 1.0 / (k + rank + 1)


# ---------------------------------------------------------------------------
# SearchResult
# ---------------------------------------------------------------------------


class SearchResult:
    """A single hybrid search hit."""

    __slots__ = ("bm25_rank", "file_path", "score", "semantic_rank", "snippet", "start_line")

    def __init__(
        self,
        file_path: str,
        snippet: str,
        start_line: int,
        score: float,
        semantic_rank: int = -1,
        bm25_rank: int = -1,
    ) -> None:
        self.file_path = file_path
        self.snippet = snippet
        self.start_line = start_line
        self.score = score           # final RRF score
        self.semantic_rank = semantic_rank
        self.bm25_rank = bm25_rank

    def __repr__(self) -> str:
        return (
            f"<SearchResult rrf={self.score:.4f} "
            f"sem={self.semantic_rank} bm25={self.bm25_rank} "
            f"file={Path(self.file_path).name!r} line={self.start_line}>"
        )

    def format(self) -> str:
        """Human-readable format for LLM context injection."""
        rel = Path(self.file_path).name
        rank_info = []
        if self.semantic_rank >= 0:
            rank_info.append(f"sem_rank={self.semantic_rank}")
        if self.bm25_rank >= 0:
            rank_info.append(f"bm25_rank={self.bm25_rank}")
        rank_str = f" [{', '.join(rank_info)}]" if rank_info else ""
        return (
            f"[{rel} : line {self.start_line}] (rrf={self.score:.4f}{rank_str})\n"
            f"{self.snippet.strip()}"
        )


# ---------------------------------------------------------------------------
# WorkspaceIndexer
# ---------------------------------------------------------------------------


class WorkspaceIndexer:
    """
    Builds and queries a persistent hybrid semantic + lexical index over a
    local file tree using Reciprocal Rank Fusion.

    Parameters
    ----------
    root:
        Root directory to index recursively.
    index_dir:
        Directory to store index files (embeddings.npz, manifest.json, chunks.json).
    """

    def __init__(
        self,
        root: str | Path = r"C:\Users\ASUS",
        index_dir: str | Path = _DEFAULT_INDEX_DIR,
        max_chunks: int = 15_000,
    ) -> None:
        self._root = Path(root)
        self._index_dir = Path(index_dir)
        self._npz_path = self._index_dir / "embeddings.npz"
        self._manifest_path = self._index_dir / "manifest.json"
        self._chunks_path = self._index_dir / "chunks.json"
        # Cap: keeps embedding matrix <= ~46 MB (15k x 768 x 4 bytes)
        # and BM25 corpus <= ~20 MB on 4 GB RAM systems.
        # Set to 0 to disable the cap.
        self._max_chunks = max_chunks

        # Populated after build() / load()
        self._matrix: Any = None           # np.ndarray (N, 768) — dense embeddings
        self._manifest: list[dict] = []    # parallel metadata list
        self._bm25: Any = None             # BM25Okapi instance (in-memory)
        self._embed_model: Any = None      # SentenceTransformer
        self._ready = False

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def build(self, force: bool = False) -> None:
        """
        Build or incrementally update the hybrid workspace index.

        On first run: embeds all files, saves embeddings.npz + manifest.json
        + chunks.json, then builds the in-memory BM25 index.
        On subsequent runs: only re-embeds files whose mtime or content hash
        has changed. BM25 is always rebuilt in-memory from chunks.json.
        """
        import numpy as np

        self._ensure_model()
        if self._embed_model is None:
            return

        self._index_dir.mkdir(parents=True, exist_ok=True)

        # ── Load existing index for incremental diffing ──────────────────
        existing_matrix: Any = None
        existing_manifest: list[dict] = []
        existing_chunks: list[str] = []

        if not force and self._npz_path.exists() and self._manifest_path.exists():
            try:
                data = np.load(self._npz_path, allow_pickle=False)
                existing_matrix = data["matrix"]
                with self._manifest_path.open("r", encoding="utf-8") as fh:
                    existing_manifest = json.load(fh)
                if self._chunks_path.exists():
                    with self._chunks_path.open("r", encoding="utf-8") as fh:
                        existing_chunks = json.load(fh)
                logger.info(
                    "WorkspaceIndexer: loaded existing index (%d chunks).",
                    len(existing_manifest),
                )
            except Exception as exc:
                logger.warning("WorkspaceIndexer: failed to load existing index: %s", exc)
                existing_matrix = None
                existing_manifest = []
                existing_chunks = []

        # ── Build lookup: chunk_key → (embedding_row, chunk_text) ───────
        existing_lookup: dict[str, tuple[Any, str]] = {}
        if (
            existing_matrix is not None
            and len(existing_manifest) == len(existing_matrix)
            and len(existing_chunks) == len(existing_manifest)
        ):
            for i, meta in enumerate(existing_manifest):
                key = self._chunk_key(meta)
                existing_lookup[key] = (existing_matrix[i], existing_chunks[i])

        # ── Filesystem walk ──────────────────────────────────────────────
        logger.info("WorkspaceIndexer: scanning '%s' ...", self._root)
        # 5-tuple: (file_path, context_header, chunk_text, start_line, mtime)
        new_chunks: list[tuple[str, str, str, int, float]] = []

        for filepath in self._walk():
            try:
                mtime = filepath.stat().st_mtime
            except OSError:
                continue
            text = self._read_file(filepath)
            if not text:
                continue
            # Build file-level context header once per file (cheap regex, no AST)
            header = self._extract_file_context(filepath, text)
            for chunk_text, start_line in self._chunk(text):
                new_chunks.append((str(filepath), header, chunk_text, start_line, mtime))

        logger.info("WorkspaceIndexer: %d total chunks found.", len(new_chunks))

        # ── RAM guard: cap chunks before allocating the embedding matrix ─
        if self._max_chunks > 0 and len(new_chunks) > self._max_chunks:
            logger.warning(
                "WorkspaceIndexer: %d chunks exceed max_chunks=%d cap — "
                "truncating to oldest files first. "
                "Narrow the root directory or raise max_chunks to index more.",
                len(new_chunks),
                self._max_chunks,
            )
            new_chunks = new_chunks[: self._max_chunks]

        # ── Partition: cached vs. needs embedding ────────────────────────
        rows: list[Any] = []
        manifest: list[dict] = []
        all_chunk_texts: list[str] = []
        to_embed_texts: list[str] = []
        to_embed_indices: list[int] = []

        for file_path, header, chunk_text, start_line, mtime in new_chunks:
            meta = {
                "file": file_path,
                "start_line": start_line,
                "mtime": mtime,
                "snippet": chunk_text[:300],   # raw text — clean for display
                "text_hash": hashlib.md5(chunk_text.encode()).hexdigest(),  # noqa: S324
            }
            key = self._chunk_key(meta)

            if key in existing_lookup:
                # Reuse cached embedding (already has header baked in)
                rows.append(existing_lookup[key][0])
                all_chunk_texts.append(existing_lookup[key][1])
            else:
                # Enrich with file-level header before embedding
                # chunks.json stores RAW text (for BM25 + clean display)
                # to_embed_texts uses ENRICHED text (for richer semantic vectors)
                enriched = self._enrich_for_embedding(header, chunk_text)
                to_embed_indices.append(len(rows))
                rows.append(None)
                all_chunk_texts.append(chunk_text)   # raw → BM25 / display
                to_embed_texts.append(enriched)       # enriched → encoder

            manifest.append(meta)

        # ── Embed new/changed chunks ─────────────────────────────────────
        if to_embed_texts:
            logger.info(
                "WorkspaceIndexer: embedding %d new/changed chunks ...", len(to_embed_texts)
            )
            try:
                new_embeddings = self._embed_model.encode(
                    to_embed_texts,
                    show_progress_bar=True,
                    normalize_embeddings=True,
                    batch_size=32,
                )
                for idx, emb in zip(to_embed_indices, new_embeddings, strict=False):
                    rows[idx] = emb
            except Exception as exc:
                logger.exception("WorkspaceIndexer: embedding batch failed: %s", exc)
                return
        else:
            logger.info("WorkspaceIndexer: all chunks up-to-date — nothing to re-embed.")

        if not rows:
            logger.warning("WorkspaceIndexer: no chunks to index.")
            return

        matrix = np.stack(rows, axis=0).astype(np.float32)

        # ── Persist all three index files ────────────────────────────────
        np.savez(self._npz_path, matrix=matrix)
        with self._manifest_path.open("w", encoding="utf-8") as fh:
            json.dump(manifest, fh, ensure_ascii=False)
        with self._chunks_path.open("w", encoding="utf-8") as fh:
            json.dump(all_chunk_texts, fh, ensure_ascii=False)

        self._matrix = matrix
        self._manifest = manifest

        # ── Build in-memory BM25 index ───────────────────────────────────
        self._build_bm25(all_chunk_texts)

        self._ready = True
        logger.info(
            "WorkspaceIndexer: hybrid index built — %d chunks, matrix %s.",
            len(manifest),
            matrix.shape,
        )

    def load(self) -> bool:
        """
        Load an existing index from disk without re-scanning the filesystem.
        Also rebuilds the BM25 index in-memory from chunks.json.
        """
        import numpy as np

        self._ensure_model()
        if self._embed_model is None:
            return False

        if not self._npz_path.exists() or not self._manifest_path.exists():
            logger.warning(
                "WorkspaceIndexer: no index found at '%s'. Run build() first.", self._index_dir
            )
            return False

        try:
            # mmap_mode='r': the OS memory-maps the file from disk.
            # Only the pages accessed by the matrix multiply stay in RAM —
            # critical for 4 GB machines where the NPZ could be 46+ MB.
            data = np.load(self._npz_path, allow_pickle=False, mmap_mode="r")
            self._matrix = data["matrix"]

            with self._manifest_path.open("r", encoding="utf-8") as fh:
                self._manifest = json.load(fh)

            # Load full chunk texts for BM25
            chunk_texts: list[str] = []
            if self._chunks_path.exists():
                with self._chunks_path.open("r", encoding="utf-8") as fh:
                    chunk_texts = json.load(fh)
            else:
                # Fallback: use snippet (degraded BM25 quality, but won't crash)
                logger.warning(
                    "WorkspaceIndexer: chunks.json missing — "
                    "BM25 will use snippet text only. Rebuild index for full quality."
                )
                chunk_texts = [m.get("snippet", "") for m in self._manifest]

            self._build_bm25(chunk_texts)
            self._ready = True

            logger.info(
                "WorkspaceIndexer: loaded hybrid index — %d chunks, BM25=%s.",
                len(self._manifest),
                "ready" if self._bm25 is not None else "unavailable",
            )
            return True

        except Exception as exc:
            logger.exception("WorkspaceIndexer: failed to load index: %s", exc)
            return False

    def search(self, query: str, top_k: int = 5) -> list[SearchResult]:
        """
        Hybrid search: Semantic (dense) + BM25 (lexical), fused via RRF.

        Falls back to pure semantic search if BM25 is unavailable.
        Returns up to `top_k` SearchResult objects, max 2 hits per file.
        """
        if not self._ready or self._matrix is None:
            logger.warning("WorkspaceIndexer: index not ready. Call build() or load() first.")
            return []

        try:
            import numpy as np

            # ── Stage 1: Dense semantic retrieval ────────────────────────
            q_vec = self._embed_model.encode(
                query, show_progress_bar=False, normalize_embeddings=True
            )
            semantic_scores: Any = self._matrix @ q_vec  # (N,)

            # Rank all chunks by semantic score (descending)
            n_chunks = len(self._manifest)
            candidate_pool = min(top_k * 5, n_chunks)
            sem_ranked = np.argsort(semantic_scores)[::-1][:candidate_pool].tolist()

            # Map chunk_index → semantic_rank (0-based)
            sem_rank_of: dict[int, int] = {
                chunk_idx: rank for rank, chunk_idx in enumerate(sem_ranked)
            }

            # ── Stage 2: BM25 lexical retrieval ──────────────────────────
            bm25_rank_of: dict[int, int] = {}
            if self._bm25 is not None:
                try:
                    q_tokens = _bm25_tokenize(query)
                    bm25_scores: Any = self._bm25.get_scores(q_tokens)
                    bm25_ranked = np.argsort(bm25_scores)[::-1][:candidate_pool].tolist()
                    bm25_rank_of = {
                        chunk_idx: rank for rank, chunk_idx in enumerate(bm25_ranked)
                    }
                except Exception as exc:
                    logger.warning("WorkspaceIndexer: BM25 scoring failed: %s", exc)

            # ── Stage 3: Reciprocal Rank Fusion ──────────────────────────
            # Union of all candidate indices from both ranked lists
            candidate_indices = set(sem_ranked) | set(bm25_rank_of.keys())

            rrf_scores: dict[int, float] = {}
            for idx in candidate_indices:
                score = 0.0
                if idx in sem_rank_of:
                    score += _rrf_score(sem_rank_of[idx])
                if idx in bm25_rank_of:
                    score += _rrf_score(bm25_rank_of[idx])
                rrf_scores[idx] = score

            # Sort by RRF score descending
            sorted_candidates = sorted(rrf_scores, key=lambda i: rrf_scores[i], reverse=True)

            # ── Stage 4: Deduplicate & build final result list ────────────
            results: list[SearchResult] = []
            for idx in sorted_candidates:
                if len(results) >= top_k:
                    break

                # Skip very low RRF scores (both lists ranked it near the bottom)
                if rrf_scores[idx] < _rrf_score(candidate_pool - 1) * 1.5:
                    continue

                meta = self._manifest[idx]
                file_path = meta["file"]

                # At most 2 chunks per file
                if sum(1 for r in results if r.file_path == file_path) >= 2:
                    continue

                results.append(
                    SearchResult(
                        file_path=file_path,
                        snippet=meta.get("snippet", ""),
                        start_line=meta.get("start_line", 0),
                        score=rrf_scores[idx],
                        semantic_rank=sem_rank_of.get(idx, -1),
                        bm25_rank=bm25_rank_of.get(idx, -1),
                    )
                )

            logger.debug(
                "WorkspaceIndexer: query='%.40s' → %d results "
                "(semantic+bm25 pool=%d, bm25=%s).",
                query, len(results), len(candidate_indices),
                "on" if self._bm25 else "off",
            )
            return results

        except Exception as exc:
            logger.exception("WorkspaceIndexer: search error: %s", exc)
            return []

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def is_ready(self) -> bool:
        return self._ready

    @property
    def chunk_count(self) -> int:
        return len(self._manifest)

    @property
    def bm25_enabled(self) -> bool:
        return self._bm25 is not None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_bm25(self, chunk_texts: list[str]) -> None:
        """
        Build the in-memory BM25Okapi index from chunk texts.
        Gracefully skips if rank_bm25 is not installed.
        """
        try:
            from rank_bm25 import BM25Okapi  # type: ignore[import-untyped]

            corpus = [_bm25_tokenize(t) for t in chunk_texts]
            self._bm25 = BM25Okapi(corpus)
            logger.info(
                "WorkspaceIndexer: BM25 index built (%d docs).", len(corpus)
            )
        except ImportError:
            logger.warning(
                "WorkspaceIndexer: rank_bm25 not installed — "
                "falling back to pure semantic search. "
                "Install with: pip install rank-bm25"
            )
            self._bm25 = None
        except Exception as exc:
            logger.warning("WorkspaceIndexer: BM25 build failed: %s", exc)
            self._bm25 = None

    def _ensure_model(self) -> None:
        """Load the sentence-transformer embedding model (once)."""
        if self._embed_model is not None:
            return
        try:
            from sentence_transformers import SentenceTransformer

            self._embed_model = SentenceTransformer(_EMBED_MODEL_NAME)
            logger.info("WorkspaceIndexer: embedding model loaded (%s).", _EMBED_MODEL_NAME)
        except ImportError:
            logger.exception(
                "WorkspaceIndexer: sentence-transformers not installed. "
                "Run: pip install sentence-transformers"
            )
        except Exception as exc:
            logger.exception("WorkspaceIndexer: failed to load embedding model: %s", exc)

    def _walk(self) -> list[Path]:
        """Return file paths to index, pruning noisy directories."""
        results: list[Path] = []
        try:
            for dirpath, dirnames, filenames in os.walk(self._root, topdown=True):
                dirnames[:] = [
                    d for d in dirnames
                    if d not in SKIP_DIRS and not d.startswith(".")
                ]
                for filename in filenames:
                    fp = Path(dirpath) / filename
                    if fp.suffix.lower() in INCLUDE_EXTENSIONS:
                        results.append(fp)
        except PermissionError as exc:
            logger.debug(
                "WorkspaceIndexer: permission denied walking '%s': %s", self._root, exc
            )
        return results

    def _read_file(self, path: Path) -> str:
        """Read a file's text, handling encoding and binary gracefully."""
        try:
            size = path.stat().st_size
            if size > MAX_FILE_BYTES:
                logger.debug(
                    "WorkspaceIndexer: skipping large file '%s' (%d bytes).", path, size
                )
                return ""

            if path.suffix.lower() == ".pdf":
                return self._read_pdf(path)

            try:
                return path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                return path.read_text(encoding="latin-1")
        except Exception as exc:
            logger.debug("WorkspaceIndexer: could not read '%s': %s", path, exc)
            return ""

    @staticmethod
    def _read_pdf(path: Path) -> str:
        """Extract text from a PDF (requires pdfminer.six — optional)."""
        try:
            from pdfminer.high_level import extract_text  # type: ignore[import-untyped]

            return extract_text(str(path))
        except ImportError:
            logger.debug(
                "WorkspaceIndexer: pdfminer not installed — skipping PDF '%s'. "
                "Install with: pip install pdfminer.six",
                path,
            )
            return ""
        except Exception as exc:
            logger.debug("WorkspaceIndexer: PDF extraction failed for '%s': %s", path, exc)
            return ""

    @staticmethod
    def _chunk(text: str) -> list[tuple[str, int]]:
        """
        Split text into overlapping chunks: (chunk_text, approx_start_line).
        """
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        text = re.sub(r"\n{3,}", "\n\n", text)  # collapse 3+ blank lines

        chunks: list[tuple[str, int]] = []
        start = 0
        total = len(text)

        while start < total:
            end = min(start + CHUNK_CHARS, total)
            chunk = text[start:end]
            if chunk.strip():
                start_line = text[:start].count("\n") + 1
                chunks.append((chunk, start_line))
            start += CHUNK_CHARS - CHUNK_OVERLAP

        return chunks

    @staticmethod
    def _chunk_key(meta: dict) -> str:
        """Cache key — changes whenever file content or mtime changes."""
        return f"{meta['file']}::{meta['mtime']}::{meta['text_hash']}"

    @staticmethod
    def _extract_file_context(path: Path, text: str) -> str:
        """
        Build a compact metadata header for a file using cheap regex — no AST,
        no external dependencies, works for all indexed file types.

        The header is prepended to every chunk *before* it reaches the
        sentence-transformer, so the embedding captures file-level context
        (imports, headings, variable names) that would otherwise be lost.

        The header is NOT stored in the display snippet or chunks.json,
        so search results remain clean.

        Examples:
            [File: amadeus_service.py | Type: Python | Imports: asyncio, logging, genai]
            [File: docker-compose.yml | Type: YAML config]
            [File: README.md | Title: Amadeus AI — Architecture Overview]
            [File: .env | Type: Environment variables]
        """
        ext = path.suffix.lower()
        parts = [f"File: {path.name}"]

        if ext == ".py":
            parts.append("Type: Python")
            # Extract top-level import names (up to 8, preserving order)
            raw_imports = re.findall(
                r"^(?:import|from)\s+([a-zA-Z0-9_]+)", text, re.MULTILINE
            )
            seen: dict[str, None] = {}
            for imp in raw_imports:
                seen[imp] = None
            unique_imports = list(seen)[:8]
            if unique_imports:
                parts.append(f"Imports: {', '.join(unique_imports)}")
            # Capture module-level globals (ALL_CAPS convention) — first 4
            globals_found = re.findall(
                r"^([A-Z][A-Z0-9_]{2,})\s*=", text, re.MULTILINE
            )
            if globals_found:
                parts.append(f"Globals: {', '.join(globals_found[:4])}")

        elif ext == ".md":
            parts.append("Type: Markdown")
            match = re.search(r"^#+\s+(.+)", text, re.MULTILINE)
            if match:
                parts.append(f"Title: {match.group(1).strip()[:80]}")

        elif ext in {".yaml", ".yml"}:
            parts.append("Type: YAML config")

        elif ext == ".toml":
            parts.append("Type: TOML config")
            # Capture top-level [sections]
            sections = re.findall(r"^\[([^\]]+)\]", text, re.MULTILINE)
            if sections:
                parts.append(f"Sections: {', '.join(sections[:5])}")

        elif ext == ".env":
            parts.append("Type: Environment variables")
            # Surface key names (not values — security)
            keys = re.findall(r"^([A-Z][A-Z0-9_]+)\s*=", text, re.MULTILINE)
            if keys:
                parts.append(f"Keys: {', '.join(keys[:6])}")

        elif ext == ".json":
            parts.append("Type: JSON")

        elif ext in {".cfg", ".ini"}:
            parts.append("Type: INI config")

        elif ext == ".rst":
            parts.append("Type: reStructuredText")

        return "[" + " | ".join(parts) + "]"

    @staticmethod
    def _enrich_for_embedding(header: str, chunk_text: str) -> str:
        """
        Prepend the file context header to a chunk for the embedding encoder.

        The header grounds the semantic vector with file-level knowledge
        (imports, globals, section names) that character-based chunking
        would otherwise discard.

        Only the enriched text reaches the sentence-transformer.
        chunks.json and display snippets always use the raw chunk_text.
        """
        return f"{header}\n{chunk_text}"
