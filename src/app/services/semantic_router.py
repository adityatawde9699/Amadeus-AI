"""
Semantic Tool Router for Amadeus AI.

Replaces the TF-IDF + LinearSVC classifier with a zero-training,
purely mathematical vector router.

Architecture:
- At startup, every registered tool's description is embedded into a
  768-dimensional NumPy vector using sentence-transformers/all-mpnet-base-v2.
- Tool embeddings are persisted to disk (Model/semantic_tool_embeddings.npz)
  and reloaded on subsequent starts. The cache is invalidated automatically
  when the set of tool names changes.
- At query time, the user's command is embedded and cosine similarity is
  computed against every tool vector using pure NumPy.
- If the best match exceeds the threshold, that tool name is returned.
  Otherwise None is returned and the LLM fallback takes over.

Benefits:
- Zero retraining: new tools are picked up automatically on the next startup.
- No ML label engineering required.
- Runs entirely on CPU via the C++ sentence-transformers backend.
"""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any


if TYPE_CHECKING:
    from src.app.services.tool_registry import ToolRegistry


logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_EMBED_MODEL_NAME = "sentence-transformers/all-mpnet-base-v2"
_CACHE_FILENAME = "semantic_tool_embeddings.npz"
_DEFAULT_THRESHOLD = 0.50


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _tool_text(name: str, description: str, category: str = "") -> str:
    """Produce a rich embedding-ready text representation for a tool."""
    parts = [f"Tool: {name}", f"Description: {description}"]
    if category:
        parts.append(f"Category: {category}")
    return "\n".join(parts)


def _registry_fingerprint(tool_names: list[str]) -> str:
    """Stable hash of the sorted tool names — used to detect registry changes."""
    key = "|".join(sorted(tool_names))
    return hashlib.md5(key.encode()).hexdigest()  # noqa: S324 — non-security hash


# ---------------------------------------------------------------------------
# SemanticToolRouter
# ---------------------------------------------------------------------------


class SemanticToolRouter:
    """
    Zero-training semantic router that maps a user query to a registered tool
    via cosine similarity over sentence-transformer embeddings.

    Parameters
    ----------
    registry:
        The live ToolRegistry to route against.
    model_dir:
        Directory where the embedding cache (.npz) is persisted.
    threshold:
        Minimum cosine similarity score to accept a tool match.
        Queries scoring below this value return None (→ LLM fallback).
    """

    def __init__(
        self,
        registry: "ToolRegistry",
        model_dir: Path | str = Path("Model"),
        threshold: float = _DEFAULT_THRESHOLD,
    ) -> None:
        self._registry = registry
        self._model_dir = Path(model_dir)
        self._threshold = threshold

        # Populated by _build_index()
        self._tool_names: list[str] = []
        self._tool_matrix: Any = None  # np.ndarray shape (N, 768)
        self._embed_model: Any = None  # SentenceTransformer instance
        self._ready = False

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def build_index(self) -> None:
        """
        Load the embedding model and build (or restore) the tool embedding matrix.
        Call this once after all tools have been registered.
        """
        try:
            import numpy as np
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:
            logger.error(
                "SemanticToolRouter requires sentence-transformers and numpy. "
                "Install with: pip install sentence-transformers numpy. Error: %s",
                exc,
            )
            return

        # --- Load embedding model ---
        try:
            self._embed_model = SentenceTransformer(_EMBED_MODEL_NAME)
            logger.info("SemanticToolRouter: loaded embedding model '%s'", _EMBED_MODEL_NAME)
        except Exception as exc:
            logger.error("SemanticToolRouter: failed to load embedding model: %s", exc)
            return

        # --- Collect current tool metadata ---
        all_tools = self._registry.list_all()
        if not all_tools:
            logger.warning("SemanticToolRouter: registry is empty — index not built.")
            return

        current_names = [t.name for t in all_tools]
        current_fp = _registry_fingerprint(current_names)

        # --- Try to restore from cache ---
        cache_path = self._model_dir / _CACHE_FILENAME
        if self._try_load_cache(cache_path, current_fp, np):
            logger.info(
                "SemanticToolRouter: restored embedding cache for %d tools.", len(self._tool_names)
            )
            self._ready = True
            return

        # --- Build fresh embeddings ---
        logger.info(
            "SemanticToolRouter: building embeddings for %d tools (this may take a moment)...",
            len(all_tools),
        )
        texts = [_tool_text(t.name, t.description, t.category.value) for t in all_tools]

        try:
            matrix = self._embed_model.encode(
                texts,
                show_progress_bar=False,
                normalize_embeddings=True,  # L2-normalise → dot product == cosine similarity
                batch_size=32,
            )
            self._tool_names = current_names
            self._tool_matrix = matrix  # shape (N, 768), float32

            # Persist to disk
            self._model_dir.mkdir(parents=True, exist_ok=True)
            np.savez(
                cache_path,
                matrix=matrix,
                names=np.array(current_names),
                fingerprint=np.array([current_fp]),
            )
            logger.info(
                "SemanticToolRouter: embeddings built and cached to '%s'.", cache_path
            )
            self._ready = True
        except Exception as exc:
            logger.error("SemanticToolRouter: embedding build failed: %s", exc)

    def route(self, query: str) -> str | None:
        """
        Route a user query to the best-matching tool name.

        Returns the tool name string if cosine similarity ≥ threshold,
        or None if no tool reaches the threshold (triggers LLM fallback).
        """
        if not self._ready or self._embed_model is None or self._tool_matrix is None:
            return None

        try:
            import numpy as np

            # Embed query (normalised so dot == cosine similarity)
            q_vec = self._embed_model.encode(
                query,
                show_progress_bar=False,
                normalize_embeddings=True,
            )  # shape (768,)

            # Cosine similarity = dot product (both vectors are L2-normalised)
            scores: Any = self._tool_matrix @ q_vec  # shape (N,)

            best_idx = int(np.argmax(scores))
            best_score = float(scores[best_idx])
            best_tool = self._tool_names[best_idx]

            logger.debug(
                "SemanticRouter: query='%.40s...' → tool='%s' (score=%.4f, threshold=%.2f)",
                query,
                best_tool,
                best_score,
                self._threshold,
            )

            if best_score >= self._threshold:
                # Validate the winning tool is still in the live registry
                if best_tool in self._registry:
                    logger.info(
                        "SemanticRouter: routed → [%s] (score=%.4f)", best_tool, best_score
                    )
                    return best_tool
                logger.warning(
                    "SemanticRouter: top match '%s' not in live registry — skipping.", best_tool
                )

            return None

        except Exception as exc:
            logger.error("SemanticRouter: routing error: %s", exc)
            return None

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def is_ready(self) -> bool:
        """True when the router has a valid embedding index."""
        return self._ready

    @property
    def tool_count(self) -> int:
        """Number of tools in the current index."""
        return len(self._tool_names)

    # ------------------------------------------------------------------
    # Cache helpers
    # ------------------------------------------------------------------

    def _try_load_cache(self, cache_path: Path, expected_fp: str, np: Any) -> bool:
        """
        Attempt to load a previously saved embedding matrix.
        Returns True on success, False if the cache is missing or stale.
        """
        if not cache_path.exists():
            return False

        try:
            data = np.load(cache_path, allow_pickle=False)
            cached_fp = str(data["fingerprint"][0])

            if cached_fp != expected_fp:
                logger.info(
                    "SemanticToolRouter: registry changed (fingerprint mismatch) — "
                    "rebuilding embedding cache."
                )
                return False

            self._tool_matrix = data["matrix"]
            self._tool_names = list(data["names"])
            return True

        except Exception as exc:
            logger.warning("SemanticToolRouter: cache load failed (%s) — rebuilding.", exc)
            return False
