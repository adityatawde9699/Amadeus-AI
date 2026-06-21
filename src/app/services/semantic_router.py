"""
Semantic Router for Amadeus AI — Agentic MoE Architecture.

Routes user queries to specialized AgentProfiles (sub-agents) rather than
individual tools. This is the "Gating Network" of the Mixture-of-Experts
architecture.

Architecture:
- At startup, every AgentProfile's description + anchor_phrases are embedded
  into dense vectors using a quantized ONNX all-MiniLM-L6-v2 model
  (onnxruntime — no torch/sentence-transformers in the daemon, CLAUDE.md §3).
  Falls back to sentence-transformers only if the ONNX export is missing.
- At query time, cosine similarity determines which Expert to activate.
- Stage 1 (SVM) narrows the candidate pool, Stage 2 (embeddings) selects.

Benefits over per-tool routing:
- Fewer embedding vectors (5 experts vs 70+ tools) → faster routing.
- Each expert gets a constrained tool menu → better zero-shot accuracy.
- Parallel expert activation for multi-intent queries.
"""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from src.core.domain.agent_profiles import (
    AGENT_PROFILES,
    AgentProfile,
    get_profile_by_name,
)


if TYPE_CHECKING:
    from src.app.services.tool_registry import ToolRegistry

from src.app.services.category_classifier import CategoryClassifier
from src.core.domain.agent_profiles import get_profile_for_category


logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_EMBED_MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"
_ONNX_EMBED_SUBDIR = Path("embed") / "all-MiniLM-L6-v2-onnx"
_CACHE_FILENAME = "unified_semantic_cache.npz"
# Bump when the embedded-text format changes (anchors, prefixes, etc.) so
# stale caches with the old format are invalidated.
_INDEX_FORMAT_VERSION = "2"
_DEFAULT_THRESHOLD = 0.30
_NARROW_THRESHOLD = 0.42
_SVM_CONFIDENCE_CUTOFF = 0.35

# Global intents that are NOT routed to an expert
_GLOBAL_INTENTS = {
    "conversational": [
        "hello", "hi there", "how are you?", "good morning", "thanks", "thank you",
        "who are you?", "what's up?", "hey Amadeus", "tell me a joke", "chat with me",
        "you're helpful", "bye", "goodbye", "see ya",
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
        "explain advanced concurrency patterns with real examples",
    ],
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _profile_text(profile: AgentProfile) -> str:
    """Build a rich text representation of an AgentProfile for embedding."""
    parts = [
        profile.description,
        f"Expert name: {profile.display_name}",
        f"Specialization: {profile.description}",
    ]
    if profile.categories:
        parts.append(f"Categories: {', '.join(c.value for c in profile.categories)}")
    return "\n".join(parts)


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


def _registry_fingerprint(
    tool_names: list[str],
    tool_descs: list[str] | None = None,
    profile_names: list[str] | None = None,
    backend: str = "",
) -> str:
    """Stable hash for cache invalidation.

    Includes the embedding backend name: vectors from the int8 ONNX model and
    the fp32 torch model are NOT interchangeable, so switching backends must
    rebuild the index.
    """
    all_keys = sorted(tool_names) + sorted(_GLOBAL_INTENTS.keys())
    if tool_descs:
        all_keys += sorted(tool_descs)
    if profile_names:
        all_keys += sorted(profile_names)
    if backend:
        all_keys.append(f"backend:{backend}")
    all_keys.append(f"format:{_INDEX_FORMAT_VERSION}")
    key = "|".join(all_keys)
    return hashlib.md5(key.encode()).hexdigest()  # noqa: S324 — non-security hash


# ---------------------------------------------------------------------------
# UnifiedSemanticRouter — MoE Edition
# ---------------------------------------------------------------------------


class UnifiedSemanticRouter:
    """
    Zero-training router that maps user queries to AgentProfiles (experts)
    or global intents via cosine similarity.

    Two-stage architecture:
        Stage 1: SVM category pre-filter (sub-ms, narrows candidate pool)
        Stage 2: Sentence Transformer cosine similarity (selects expert)
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
        self._labels: list[str] = []   # Names: expert names or intent names
        self._types: list[str] = []    # 'expert', 'tool', or 'intent'
        self._matrix: Any = None       # np.ndarray shape (N, D)
        self._embed_model: Any = None  # SentenceTransformer instance
        self._ready = False

        # Stage-1 SVM pre-filter
        self._category_clf = CategoryClassifier(model_dir=self._model_dir)
        # Fast lookup: label (tool/expert name) → category string
        self._tool_category_map: dict[str, str] = {}

    def _load_embed_model(self) -> Any:
        """Load the embedding backend: ONNX first (mandated), torch fallback.

        The ONNX backend (onnxruntime + tokenizers) keeps daemon RSS low.
        The sentence-transformers fallback exists only so a fresh checkout
        still works before `scripts/export_embedding_onnx.py` has been run.
        """
        try:
            from src.infra.embeddings.onnx_embedder import OnnxEmbedder

            return OnnxEmbedder(self._model_dir / _ONNX_EMBED_SUBDIR)
        except FileNotFoundError:
            logger.warning(
                "UnifiedSemanticRouter: ONNX embed model missing — run "
                "`python scripts/export_embedding_onnx.py` to avoid the "
                "~500MB PyTorch fallback. Falling back to sentence-transformers."
            )
        except ImportError as exc:
            logger.warning(
                "UnifiedSemanticRouter: onnxruntime/tokenizers unavailable (%s) — "
                "falling back to sentence-transformers.", exc,
            )

        from sentence_transformers import SentenceTransformer

        return SentenceTransformer(_EMBED_MODEL_NAME)

    def build_index(self) -> None:
        """Load the model and build the unified embedding matrix."""
        try:
            import numpy as np
        except ImportError as exc:
            logger.exception("UnifiedSemanticRouter requires numpy: %s", exc)
            return

        try:
            self._embed_model = self._load_embed_model()
        except Exception as exc:
            logger.exception("UnifiedSemanticRouter: failed to load embedding model: %s", exc)
            return

        all_tools = self._registry.list_all()
        tool_names = [t.name for t in all_tools]
        tool_descs = [t.description for t in all_tools]
        # Include anchors + descriptions, not just names — editing a profile's
        # anchor phrases must invalidate the cached embedding matrix.
        profile_names = [
            f"{p.name}:{p.description}:{'|'.join(p.anchor_phrases)}"
            for p in AGENT_PROFILES
        ]
        current_fp = _registry_fingerprint(
            tool_names, tool_descs, profile_names,
            backend=getattr(
                self._embed_model, "fingerprint", type(self._embed_model).__name__
            ),
        )

        # Populate tool→category map and the Stage-1 classifier regardless of
        # whether the embedding matrix comes from cache or a fresh build —
        # both are required by route() at query time.
        self._tool_category_map = {t.name: t.category.value for t in all_tools}
        if not self._category_clf.load():
            logger.info("UnifiedSemanticRouter: training category classifier...")
            self._category_clf.train()

        cache_path = self._model_dir / _CACHE_FILENAME
        if self._try_load_cache(cache_path, current_fp, np):
            logger.info("UnifiedSemanticRouter: restored cache for %d items.", len(self._labels))
            self._ready = True
            return

        # Build fresh embeddings
        logger.info("UnifiedSemanticRouter: indexing experts, tools, and intents...")

        texts = []
        labels = []
        types = []

        # 1. Expert profiles — embed each profile + its anchor phrases
        for profile in AGENT_PROFILES:
            # Embed the profile description itself
            texts.append(_profile_text(profile))
            labels.append(profile.name)
            types.append("expert")

            # Embed each anchor phrase RAW — prefixing with the expert name
            # dilutes cosine similarity against short user queries (~0.49 for
            # an exact phrase match instead of 1.0).
            for phrase in profile.anchor_phrases:
                texts.append(phrase)
                labels.append(profile.name)
                types.append("expert")

        # 2. Individual tools — for fine-grained routing within experts
        for t in all_tools:
            texts.append(_tool_text(t.name, t.description, t.category.value))
            labels.append(t.name)
            types.append("tool")
            self._tool_category_map[t.name] = t.category.value

        # 3. Global intents — also embedded raw (see anchor note above)
        for intent, anchors in _GLOBAL_INTENTS.items():
            for phrase in anchors:
                texts.append(phrase)
                labels.append(intent)
                types.append("intent")

        try:
            matrix = self._embed_model.encode(
                texts,
                normalize_embeddings=True,
                show_progress_bar=False,
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
            logger.exception("UnifiedSemanticRouter: index build failed: %s", exc)

    def route(self, query: str) -> tuple[str, str | None]:
        """
        Route a user query to either an expert profile or a global intent.

        Returns one of:
            ('expert', expert_name)        — a specific expert was matched
            ('tool', tool_name)            — a specific tool was matched directly
            ('conversational', None)       — no confident match; use LLM chitchat
            ('cloud_escalation', None)     — complex query; use cloud LLM
        """
        if not self._ready or self._matrix is None:
            return "conversational", None

        try:
            import numpy as np

            q_vec = self._embed_model.encode(
                query, normalize_embeddings=True, show_progress_bar=False,
            )

            # ----------------------------------------------------------
            # Stage 1: SVM category pre-filter
            # ----------------------------------------------------------
            candidate_indices: list[int] | None = None
            svm_used = False

            if self._category_clf.is_ready:
                top2_categories = self._category_clf.predict_top2(query)
                _primary_cat, confidence = self._category_clf.predict(query)

                if confidence >= _SVM_CONFIDENCE_CUTOFF and top2_categories:
                    allowed_cats = set(top2_categories)

                    # Keep expert rows, intent rows, and tool rows whose category matches
                    candidate_indices = [
                        i for i, (lbl, typ) in enumerate(zip(self._labels, self._types, strict=True))
                        if typ in ("intent", "expert")
                        or self._tool_category_map.get(lbl, "") in allowed_cats
                    ]

                    if len(candidate_indices) >= 2:
                        svm_used = True
                        logger.debug(
                            "UnifiedRouter SVM: '%s' → cats=%s (conf=%.2f), %d candidates",
                            query[:40], top2_categories, confidence, len(candidate_indices),
                        )
                    else:
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
                effective_threshold = _NARROW_THRESHOLD
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

            if kind == "expert":
                # The generalist has no tool categories — it IS the
                # conversational path, so report it as such for the cheaper
                # direct-chat handling in AmadeusService.
                if label == "generalist":
                    return "conversational", None
                return "expert", label

            if kind == "tool":
                return "tool", label

            # 'intent' → 'conversational' or 'cloud_escalation'
            return label, None

        except Exception as exc:
            logger.exception("UnifiedRouter: routing error: %s", exc)
            return "conversational", None

    def route_to_profile(self, query: str) -> AgentProfile:
        """Convenience: route and resolve directly to an AgentProfile.

        Returns the generalist profile if no confident match is found.
        """
        kind, name = self.route(query)

        if kind == "expert" and name:
            profile = get_profile_by_name(name)
            if profile:
                return profile

        if kind == "tool" and name:
            # Map the tool's category to its owning expert
            tool = self._registry.get(name)
            if tool:
                return get_profile_for_category(tool.category)

        # Fallback: generalist
        return AGENT_PROFILES[-1]

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
