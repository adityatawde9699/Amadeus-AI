from __future__ import annotations

import numpy as np

from src.app.services.semantic_router import UnifiedSemanticRouter


class _DummyClassifier:
    is_ready = False


class _DummyEmbedModel:
    def __init__(self, vectors: dict[str, np.ndarray]):
        self._vectors = vectors

    def encode(self, text: str, normalize_embeddings: bool = True, show_progress_bar: bool = False):
        vector = self._vectors[text]
        if normalize_embeddings:
            norm = np.linalg.norm(vector)
            if norm:
                return vector / norm
        return vector


def _router_for(vectors: dict[str, np.ndarray], threshold: float = 0.5) -> UnifiedSemanticRouter:
    router = UnifiedSemanticRouter(registry=object(), threshold=threshold)  # type: ignore[arg-type]
    router._ready = True
    router._embed_model = _DummyEmbedModel(vectors)
    router._category_clf = _DummyClassifier()
    router._labels = ["get_weather", "conversational", "cloud_escalation"]
    router._types = ["tool", "intent", "intent"]
    router._tool_category_map = {"get_weather": "info"}
    router._matrix = np.array(
        [
            [1.0, 0.0, 0.0],
            [0.0, 1.0, 0.0],
            [0.0, 0.0, 1.0],
        ]
    )
    return router


def test_routes_to_best_matching_tool_above_threshold():
    router = _router_for({"weather please": np.array([0.95, 0.05, 0.0])})

    assert router.route("weather please") == ("tool", "get_weather")


def test_falls_back_to_conversational_below_threshold():
    router = _router_for({"unclear": np.array([0.4, 0.3, 0.3])}, threshold=0.9)

    assert router.route("unclear") == ("conversational", None)


def test_routes_global_cloud_escalation_intent():
    router = _router_for({"debug production crash": np.array([0.0, 0.05, 0.95])})

    assert router.route("debug production crash") == ("cloud_escalation", None)
