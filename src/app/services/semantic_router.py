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

from src.app.services.category_classifier import CategoryClassifier


logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants & Intents
# ---------------------------------------------------------------------------

_EMBED_MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"
_CACHE_FILENAME = "unified_semantic_cache.npz"
_DEFAULT_THRESHOLD = 0.30        # base threshold for full-pool search
_NARROW_THRESHOLD = 0.42         # raised threshold when candidate pool is narrowed
_SVM_CONFIDENCE_CUTOFF = 0.35    # minimum LinearSVC score to trust SVM category

# Anchor phrases for global intents to guide the vector space
_GLOBAL_INTENTS = {
    "conversational": [
        "hello", "hi there", "how are you?", "good morning", "thanks", "thank you",
        "who are you?", "what's up?", "hey Amadeus", "tell me a joke", "chat with me",
        "you're helpful", "bye", "goodbye", "see ya"
    ],
    "cloud_escalation": [
        "debug my fastapi startup error and stack trace",
        "analyze this production crash log and identify root cause",
        "help me design a distributed system with failover and replication",
        "write a complex python script for quantum simulation",
        "optimize this sql query and explain query plan bottlenecks",
        "explain the mathematical proof of fermat's last theorem",
        "solve this advanced calculus problem with derivation steps",
        "architect a microservices platform for high availability",
        "perform a security review and threat model for this api",
        "design a scalable event-driven architecture with kafka",
        "reason about algorithmic complexity and trade-offs",
        "prepare a comprehensive technical research report",
        "refactor this codebase with phased migration strategy",
        "debug race condition in asynchronous worker queue",
        "compare machine learning models and justify selection",
        "build an end-to-end data pipeline with validation",
        "troubleshoot docker deployment and runtime networking failures",
        "create a robust test strategy for integration and load tests",
        "investigate memory leak symptoms in a long-running service",
        "evaluate cloud architecture cost, latency, and resiliency",
        "review observability gaps and propose sre runbooks",
        "design database sharding strategy for write-heavy workload",
        "perform incident postmortem and preventive action planning",
        "explain advanced concurrency patterns with real examples"
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
        registry: ToolRegistry,
        model_dir: Path | str = Path("Model"),
        threshold: float = _DEFAULT_THRESHOLD,
    ) -> None:
        self._registry = registry
        self._model_dir = Path(model_dir)
        self._threshold = threshold

        # Populated by build_index()
        self._labels: list[str] = []  # Names of tools or intents
        self._types: list[str] = []   # 'tool' or 'intent'
        self._matrix: Any = None      # np.ndarray shape (N, D)
        self._embed_model: Any = None  # SentenceTransformer instance
        self._ready = False

        # Stage-1 SVM pre-filter
        self._category_clf = CategoryClassifier(model_dir=self._model_dir)
        # Build a fast lookup: label (tool name) → category string
        self._tool_category_map: dict[str, str] = {}

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

        # 1. Tools — store category for SVM cross-reference
        for t in all_tools:
            texts.append(_tool_text(t.name, t.description, t.category.value))
            labels.append(t.name)
            types.append("tool")
            self._tool_category_map[t.name] = t.category.value

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

            # Stage-1: train/load category classifier
            if not self._category_clf.load():
                logger.info("UnifiedSemanticRouter: training category classifier...")
                self._category_clf.train()
        except Exception as exc:
            logger.error("UnifiedSemanticRouter: index build failed: %s", exc)

    def route(self, query: str) -> tuple[str, str | None]:
        """
        Two-stage route: query → (intent_type, tool_name_or_none).

        Stage 1 — SVM category pre-filter:
            Predicts the tool category in ~1ms and narrows the candidate
            pool from N tools to the K tools in that category.

        Stage 2 — Sentence Transformer cosine similarity:
            Runs only against the narrowed candidate pool, giving higher
            precision than searching across all tools.

        Returns one of:
            ('tool', tool_name)          — a specific tool was matched
            ('conversational', None)     — no confident match; use LLM
            ('cloud_escalation', None)   — complex query; use cloud LLM
        """
        if not self._ready or self._matrix is None:
            return "conversational", None

        try:
            import numpy as np

            q_vec = self._embed_model.encode(
                query, normalize_embeddings=True, show_progress_bar=False
            )

            # ----------------------------------------------------------
            # Stage 1: SVM category pre-filter
            # ----------------------------------------------------------
            candidate_indices: list[int] | None = None
            svm_used = False

            if self._category_clf.is_ready:
                top2_categories = self._category_clf.predict_top2(query)
                primary_cat, confidence = self._category_clf.predict(query)

                if confidence >= _SVM_CONFIDENCE_CUTOFF and top2_categories:
                    # Build a set of allowed categories (top-2 for safety)
                    allowed_cats = set(top2_categories)

                    # Also always keep intent rows (no category = always included)
                    candidate_indices = [
                        i for i, (lbl, typ) in enumerate(zip(self._labels, self._types))
                        if typ == "intent"
                        or self._tool_category_map.get(lbl, "") in allowed_cats
                    ]

                    if len(candidate_indices) >= 2:
                        svm_used = True
                        logger.debug(
                            "UnifiedRouter SVM: '%s' → cats=%s (conf=%.2f), %d candidates",
                            query[:40], top2_categories, confidence, len(candidate_indices),
                        )
                    else:
                        # Too few candidates — fall back to full search
                        candidate_indices = None

            # ----------------------------------------------------------
            # Stage 2: Sentence Transformer cosine similarity
            # ----------------------------------------------------------
            if candidate_indices is not None:
                sub_matrix = self._matrix[candidate_indices]
                scores = sub_matrix @ q_vec
                best_local = int(np.argmax(scores))
                best_idx = candidate_indices[best_local]
                score = float(scores[best_local])
                effective_threshold = _NARROW_THRESHOLD  # tighter — smaller pool
            else:
                scores = self._matrix @ q_vec
                best_idx = int(np.argmax(scores))
                score = float(scores[best_idx])
                effective_threshold = self._threshold

            label = self._labels[best_idx]
            kind = self._types[best_idx]

            logger.debug(
                "UnifiedRouter: '%s' → %s:%s (score=%.4f, threshold=%.2f, svm=%s)",
                query[:40], kind, label, score, effective_threshold, svm_used,
            )

            if score < effective_threshold:
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

