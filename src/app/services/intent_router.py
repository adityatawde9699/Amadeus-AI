"""
Intent router: decides how a request is handled without calling an LLM.

Two small softmax classifiers over MiniLM sentence embeddings:

* the **category head** picks one of the tool categories or a chat intent
  (``conversational``, ``content_generation``, ``cloud_escalation``);
* the **tool head** picks the tool inside the winning categories.

Both are trained in numpy at startup from the phrases in
``routing_data.py`` plus each registered tool's name and ``Trigger:`` phrases.
Training takes well under a second; the phrase embeddings are cached in
``Model/intent_router.npz``. There is no build-time artifact and no
scikit-learn dependency. Routing one query costs one embedding (~1-3 ms).

``route()`` returns a :class:`RouteDecision`:

* ``tool``    - category and tool are both confident: dispatch directly.
* ``expert``  - a tool category, but not confident enough about the tool: hand
  the request to that category's expert agent (LLM tool selection).
* ``conversational`` / ``content_generation`` / ``cloud_escalation`` - the
  LLM answers directly.

The only hard rule is a URL, which always goes to ``fetch_webpage_content``.
"""

from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from src.app.services.routing_data import (
    CHAT_INTENTS,
    GLOBAL_INTENTS,
    TOOL_EXAMPLES,
    TRAINING_DATA,
)
from src.core.domain.agent_profiles import get_profile_for_category
from src.infra.tools.base import ToolCategory


if TYPE_CHECKING:
    from src.app.services.tool_registry import ToolRegistry


logger = logging.getLogger(__name__)

_EMBED_MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"
_ONNX_EMBED_SUBDIR = Path("embed") / "all-MiniLM-L6-v2-onnx"
_CACHE_FILENAME = "intent_router.npz"
_FORMAT_VERSION = "1"

# Route straight to the top category when it leads the runner-up by this much.
CATEGORY_GAP = 0.15
# Dispatch a tool directly only when it leads the next tool by this much...
TOOL_MARGIN = 0.20
# ...and the category itself is at least this probable.
TOOL_MIN_CATEGORY_PROB = 0.25
# The runner-up category joins the tool ranking when it is this close to the top.
RUNNER_UP_RATIO = 0.4

_URL_RE = re.compile(r"https?://\S+", re.IGNORECASE)
_TRIGGER_RE = re.compile(r"'([^']{3,60})'")
# Requests that chain actions need the agent, not a single tool.
_MULTI_STEP_RE = re.compile(r"\b(and then|then|after that|afterwards|as well as)\b", re.IGNORECASE)


@dataclass(frozen=True)
class RouteDecision:
    """Outcome of routing one query."""

    kind: str  # tool | expert | conversational | content_generation | cloud_escalation
    target: str | None  # tool name or expert profile name
    category: str  # winning category / intent
    confidence: float  # probability of the winning category
    gap: float  # lead over the second category
    tool_margin: float = 0.0  # lead of the best tool over the next one
    reason: str = ""

    def as_intent(self) -> tuple[str, str | None]:
        return self.kind, self.target


def _category_value(category: Any) -> str:
    return str(getattr(category, "value", category))


def train_softmax(
    x: Any, labels: list[str], *, l2: float = 1e-4, epochs: int = 500, lr: float = 0.5
) -> tuple[list[str], Any, Any]:
    """Class-balanced multinomial logistic regression, full-batch Adam, in numpy.

    Deterministic (zero initialisation). Returns ``(classes, weights, bias)``.
    """
    import numpy as np

    classes = sorted(set(labels))
    index = {c: i for i, c in enumerate(classes)}
    y = np.array([index[label] for label in labels])
    n, d = x.shape
    k = len(classes)
    counts = np.bincount(y, minlength=k).astype(np.float64)
    sample_w = (n / (k * counts))[y]
    sample_w /= sample_w.sum()
    onehot = np.zeros((n, k))
    onehot[np.arange(n), y] = 1.0

    w = np.zeros((k, d))
    b = np.zeros(k)
    m_w, v_w = np.zeros_like(w), np.zeros_like(w)
    m_b, v_b = np.zeros_like(b), np.zeros_like(b)
    beta1, beta2, eps = 0.9, 0.999, 1e-8
    x64 = x.astype(np.float64)
    for step in range(1, epochs + 1):
        logits = x64 @ w.T + b
        logits -= logits.max(axis=1, keepdims=True)
        probs = np.exp(logits)
        probs /= probs.sum(axis=1, keepdims=True)
        delta = (probs - onehot) * sample_w[:, None]
        g_w = delta.T @ x64 + l2 * w
        g_b = delta.sum(axis=0)
        m_w = beta1 * m_w + (1 - beta1) * g_w
        v_w = beta2 * v_w + (1 - beta2) * g_w * g_w
        m_b = beta1 * m_b + (1 - beta1) * g_b
        v_b = beta2 * v_b + (1 - beta2) * g_b * g_b
        scale = lr * np.sqrt(1 - beta2**step) / (1 - beta1**step)
        w -= scale * m_w / (np.sqrt(v_w) + eps)
        b -= scale * m_b / (np.sqrt(v_b) + eps)
    return classes, w.astype(np.float32), b.astype(np.float32)


def _softmax(logits: Any) -> Any:
    import numpy as np

    z = logits - logits.max()
    e = np.exp(z)
    return e / e.sum()


def load_embedder(model_dir: Path) -> Any:
    """ONNX MiniLM (default install) or sentence-transformers (fresh checkout)."""
    try:
        from src.infra.embeddings.onnx_embedder import OnnxEmbedder

        return OnnxEmbedder(model_dir / _ONNX_EMBED_SUBDIR)
    except FileNotFoundError:
        logger.warning(
            "IntentRouter: ONNX embed model missing - run "
            "`python scripts/export_embedding_onnx.py`. Falling back to sentence-transformers."
        )
    except ImportError as exc:
        logger.warning("IntentRouter: onnxruntime/tokenizers unavailable (%s).", exc)

    from sentence_transformers import SentenceTransformer

    return SentenceTransformer(_EMBED_MODEL_NAME)


class IntentRouter:
    """LLM-free router over tool categories, chat intents and tools."""

    def __init__(
        self,
        registry: ToolRegistry,
        model_dir: Path | str = Path("Model"),
        embedder: Any = None,
        category_gap: float = CATEGORY_GAP,
        tool_margin: float = TOOL_MARGIN,
    ) -> None:
        self._registry = registry
        self._model_dir = Path(model_dir)
        self._embedder = embedder
        self._category_gap = category_gap
        self._tool_margin = tool_margin

        self._cat_classes: list[str] = []
        self._cat_w: Any = None
        self._cat_b: Any = None
        self._tool_names: list[str] = []
        self._tool_w: Any = None
        self._tool_b: Any = None
        self._tool_category: dict[str, str] = {}
        self._ready = False

    # ------------------------------------------------------------------
    # Build
    # ------------------------------------------------------------------

    @property
    def is_ready(self) -> bool:
        return self._ready

    def _training_sets(self) -> tuple[list[str], list[str], list[str], list[str]]:
        """(category texts, category labels, tool texts, tool labels)."""
        tools = self._registry.list_all()
        self._tool_category = {t.name: _category_value(t.category) for t in tools}

        tool_texts: list[str] = []
        tool_labels: list[str] = []
        for tool in tools:
            phrases = [tool.name.replace("_", " ")]
            phrases += _TRIGGER_RE.findall(tool.description.partition("Trigger:")[2])
            phrases += TOOL_EXAMPLES.get(tool.name, [])
            for phrase in dict.fromkeys(p.strip().lower() for p in phrases if p.strip()):
                tool_texts.append(phrase)
                tool_labels.append(tool.name)

        cat_texts: list[str] = []
        cat_labels: list[str] = []
        for table in (TRAINING_DATA, GLOBAL_INTENTS):
            for label, phrases in table.items():
                cat_texts += phrases
                cat_labels += [label] * len(phrases)
        # Tool phrases also teach the category head, so the two heads agree
        # about where a tool lives on this installation.
        known = set(cat_labels)
        for phrase, tool_name in zip(tool_texts, tool_labels, strict=True):
            category = self._tool_category[tool_name]
            if category in known:
                cat_texts.append(phrase)
                cat_labels.append(category)
        return cat_texts, cat_labels, tool_texts, tool_labels

    def _embed_all(self, texts: list[str]) -> Any:
        import numpy as np

        vectors = self._embedder.encode(texts, normalize_embeddings=True, show_progress_bar=False)
        return np.asarray(vectors, dtype=np.float32)

    def _embed_cached(self, texts: list[str]) -> Any:
        import numpy as np

        backend = getattr(self._embedder, "fingerprint", type(self._embedder).__name__)
        key = hashlib.md5(  # cache fingerprint, not security
            "\x1f".join([_FORMAT_VERSION, str(backend), *texts]).encode(), usedforsecurity=False
        ).hexdigest()
        cache_path = self._model_dir / _CACHE_FILENAME
        try:
            if cache_path.exists():
                data = np.load(cache_path, allow_pickle=False)
                if str(data["key"]) == key:
                    return data["vectors"]
        except Exception as exc:
            logger.debug("IntentRouter: cache unreadable (%s); rebuilding.", exc)

        vectors = self._embed_all(texts)
        try:
            self._model_dir.mkdir(parents=True, exist_ok=True)
            np.savez(cache_path, key=np.array(key), vectors=vectors)
        except OSError as exc:
            logger.debug("IntentRouter: could not write cache: %s", exc)
        return vectors

    def build(self) -> None:
        """Load the embedder and train both heads. Never raises."""
        try:
            if self._embedder is None:
                self._embedder = load_embedder(self._model_dir)
            cat_texts, cat_labels, tool_texts, tool_labels = self._training_sets()
            vectors = self._embed_cached(cat_texts + tool_texts)
            cat_x, tool_x = vectors[: len(cat_texts)], vectors[len(cat_texts) :]

            self._cat_classes, self._cat_w, self._cat_b = train_softmax(cat_x, cat_labels)
            if tool_labels:
                self._tool_names, self._tool_w, self._tool_b = train_softmax(tool_x, tool_labels)
            self._ready = True
            logger.info(
                "IntentRouter ready: %d categories (%d phrases), %d tools (%d phrases).",
                len(self._cat_classes),
                len(cat_texts),
                len(self._tool_names),
                len(tool_texts),
            )
        except Exception as exc:
            logger.exception("IntentRouter: build failed: %s", exc)
            self._ready = False

    # ------------------------------------------------------------------
    # Inference
    # ------------------------------------------------------------------

    def category_probabilities(self, query: str) -> dict[str, float]:
        """Probability per category / chat intent (empty when not ready)."""
        if not self._ready:
            return {}
        vec = self._embed_all([query])[0]
        probs = _softmax(self._cat_w @ vec + self._cat_b)
        return {c: float(p) for c, p in zip(self._cat_classes, probs, strict=True)}

    def _rank_tools(self, vec: Any, categories: set[str]) -> list[tuple[str, float]]:
        """Tools in *categories*, most probable first, renormalised over that set."""
        import numpy as np

        if self._tool_w is None:
            return []
        idx = [i for i, n in enumerate(self._tool_names) if self._tool_category[n] in categories]
        if not idx:
            return []
        probs = _softmax((self._tool_w @ vec + self._tool_b)[idx])
        order = np.argsort(-probs)
        return [(self._tool_names[idx[i]], float(probs[i])) for i in order]

    def expert_for(self, category: str) -> str | None:
        try:
            profile = get_profile_for_category(ToolCategory(category))
        except ValueError:
            return None
        return None if profile.name == "generalist" else profile.name

    def route(self, query: str) -> RouteDecision:
        """Route *query*. Falls back to ``conversational`` when not ready."""
        text = query.strip()
        if _URL_RE.search(text) and self._registry.get("fetch_webpage_content"):
            return RouteDecision(
                "tool", "fetch_webpage_content", "web_research", 1.0, 1.0, 1.0, "url"
            )
        if not self._ready or not text:
            return RouteDecision(
                "conversational", None, "conversational", 0.0, 0.0, 0.0, "not ready"
            )

        try:
            import numpy as np

            vec = self._embed_all([text])[0]
            probs = _softmax(self._cat_w @ vec + self._cat_b)
            order = np.argsort(-probs)
            top, second = self._cat_classes[order[0]], self._cat_classes[order[1]]
            p_top = float(probs[order[0]])
            gap = p_top - float(probs[order[1]])

            if top in CHAT_INTENTS:
                return RouteDecision(top, None, top, p_top, gap, 0.0, "chat intent")

            confident = gap >= self._category_gap
            # Neighbouring categories overlap (tasks vs goals, apps vs OS), so
            # the tool head also sees the runner-up when it is a real contender
            # and the winning tool decides which category the request is in.
            p_second = float(probs[order[1]])
            categories = {top}
            if second not in CHAT_INTENTS and (
                not confident or p_second >= RUNNER_UP_RATIO * p_top
            ):
                categories.add(second)
            ranked = self._rank_tools(vec, categories)
            margin = 0.0
            if ranked:
                margin = ranked[0][1] - (ranked[1][1] if len(ranked) > 1 else 0.0)
                if margin >= self._tool_margin:
                    top = self._tool_category[ranked[0][0]]
            expert = self.expert_for(top)
            p_cat = float(probs[self._cat_classes.index(top)])

            direct_ok = (
                bool(ranked)
                and margin >= self._tool_margin
                and p_cat >= TOOL_MIN_CATEGORY_PROB
                and not _MULTI_STEP_RE.search(text)
            )
            if direct_ok:
                return RouteDecision("tool", ranked[0][0], top, p_cat, gap, margin, "direct")
            if expert is not None:
                if _MULTI_STEP_RE.search(text):
                    reason = "multi-step"
                elif not confident:
                    reason = "category unsure"
                else:
                    reason = "tool unsure"
                return RouteDecision("expert", expert, top, p_cat, gap, margin, reason)
            if ranked:
                # No expert owns this category: the best tool is the only route.
                return RouteDecision("tool", ranked[0][0], top, p_cat, gap, margin, "no expert")
            return RouteDecision("conversational", None, top, p_cat, gap, 0.0, "no route")
        except Exception as exc:
            logger.exception("IntentRouter: routing error: %s", exc)
            return RouteDecision("conversational", None, "conversational", 0.0, 0.0, 0.0, "error")
