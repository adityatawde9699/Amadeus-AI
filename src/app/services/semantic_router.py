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
# Constants & Intents
# ---------------------------------------------------------------------------

_EMBED_MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"
_CACHE_FILENAME = "unified_semantic_cache.npz"
_DEFAULT_THRESHOLD = 0.30  # Tuned for MiniLM-L6-v2

# Anchor phrases for global intents to guide the vector space
_GLOBAL_INTENTS = {
    "conversational": [
        "hello", "hi there", "how are you?", "good morning", "thanks", "thank you",
        "who are you?", "what's up?", "hey Amadeus", "tell me a joke", "chat with me",
        "you're helpful", "bye", "goodbye", "see ya"
    ],
    "cloud_escalation": [
        "write a complex python script for quantum simulation",
        "explain the mathematical proof of fermat's last theorem",
        "solve this advanced calculus problem",
        "architect a distributed system for high availability",
        "deep dive into the philosophy of mind and consciousness",
        "write a comprehensive technical research paper"
    ]
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _tool_text(name: str, description: str, category: str = "") -> str:
    """Produce a rich embedding-ready text representation for a tool."""
    parts = [
        description,
        f"Tool name: {name}",
        f"Use this tool to: {description}",
    ]
    if category:
        parts.append(f"Category: {category}")
    return "\n".join(parts)


def _registry_fingerprint(tool_names: list[str], tool_descs: list[str] | None = None) -> str:
    """Stable hash of the tool names, descriptions, and intents — used to detect changes."""
    all_keys = sorted(tool_names) + sorted(_GLOBAL_INTENTS.keys())
    if tool_descs:
        all_keys += sorted(tool_descs)
    key = "|".join(all_keys)
    return hashlib.md5(key.encode()).hexdigest()  # noqa: S324 — non-security hash


# ---------------------------------------------------------------------------
# UnifiedSemanticRouter
# ---------------------------------------------------------------------------


class UnifiedSemanticRouter:
    """
    Zero-training unified router that maps user queries to either a specific
    tool or a global intent (conversational, escalation) via cosine similarity.

    Uses sentence-transformers/all-mpnet-base-v2 for high-quality embeddings.
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

        # Populated by build_index()
        self._labels: list[str] = []  # Names of tools or intents
        self._types: list[str] = []   # 'tool' or 'intent'
        self._matrix: Any = None      # np.ndarray shape (N, 768)
        self._embed_model: Any = None  # SentenceTransformer instance
        self._ready = False

    def build_index(self) -> None:
        """Load the model and build the unified embedding matrix."""
        try:
            import numpy as np
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:
            logger.error("UnifiedSemanticRouter requires sentence-transformers and numpy: %s", exc)
            return

        try:
            self._embed_model = SentenceTransformer(_EMBED_MODEL_NAME)
        except Exception as exc:
            logger.error("UnifiedSemanticRouter: failed to load embedding model: %s", exc)
            return

        all_tools = self._registry.list_all()
        tool_names = [t.name for t in all_tools]
        tool_descs = [t.description for t in all_tools]
        current_fp = _registry_fingerprint(tool_names, tool_descs)

        cache_path = self._model_dir / _CACHE_FILENAME
        if self._try_load_cache(cache_path, current_fp, np):
            logger.info("UnifiedSemanticRouter: restored cache for %d items.", len(self._labels))
            self._ready = True
            return

        # Build fresh embeddings
        logger.info("UnifiedSemanticRouter: indexing tools and intents...")
        
        texts = []
        labels = []
        types = []

        # 1. Tools
        for t in all_tools:
            texts.append(_tool_text(t.name, t.description, t.category.value))
            labels.append(t.name)
            types.append("tool")

        # 2. Intents
        for intent, anchors in _GLOBAL_INTENTS.items():
            for phrase in anchors:
                texts.append(f"Intent: {intent}\nExample: {phrase}")
                labels.append(intent)
                types.append("intent")

        try:
            matrix = self._embed_model.encode(
                texts,
                normalize_embeddings=True,
                show_progress_bar=False
            )
            self._labels = labels
            self._types = types
            self._matrix = matrix

            # Cache
            self._model_dir.mkdir(parents=True, exist_ok=True)
            np.savez(
                cache_path,
                matrix=matrix,
                labels=np.array(labels),
                types=np.array(types),
                fingerprint=np.array([current_fp]),
            )
            self._ready = True
            logger.info("UnifiedSemanticRouter: index built with %d vectors.", len(labels))
        except Exception as exc:
            logger.error("UnifiedSemanticRouter: index build failed: %s", exc)

    def route(self, query: str) -> tuple[str, str | None]:
        """
        Route query to (intent_type, tool_name_or_none).
        
        Types: 'tool', 'conversational', 'cloud_escalation'.
        """
        if not self._ready or self._matrix is None:
            return "conversational", None

        try:
            import numpy as np
            q_vec = self._embed_model.encode(query, normalize_embeddings=True, show_progress_bar=False)
            scores = self._matrix @ q_vec
            
            best_idx = int(np.argmax(scores))
            score = float(scores[best_idx])
            label = self._labels[best_idx]
            kind = self._types[best_idx]

            logger.debug("UnifiedRouter: '%s' -> %s:%s (score=%.4f)", query[:40], kind, label, score)

            if score < self._threshold:
                return "conversational", None

            if kind == "tool":
                return "tool", label
            
            return label, None  # 'conversational' or 'cloud_escalation'

        except Exception as exc:
            logger.error("UnifiedRouter: routing error: %s", exc)
            return "conversational", None

    def _try_load_cache(self, cache_path: Path, expected_fp: str, np: Any) -> bool:
        if not cache_path.exists():
            return False
        try:
            data = np.load(cache_path, allow_pickle=False)
            if str(data["fingerprint"][0]) != expected_fp:
                return False
            self._matrix = data["matrix"]
            self._labels = list(data["labels"])
            self._types = list(data["types"])
            return True
        except Exception:
            return False

    @property
    def is_ready(self) -> bool:
        return self._ready

