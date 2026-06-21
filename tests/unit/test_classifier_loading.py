"""
Tests for SemanticRouter initialization and routing behaviour.

Replaces the stale test_classifier_loading.py which tested the old
joblib/SVM-based classifier that no longer exists in the codebase.

These tests are skipped automatically when sentence-transformers or sklearn
cannot be imported (e.g. package name conflicts on the dev machine).
"""

import importlib.util

import pytest

from src.app.services.tool_registry import ToolRegistry


# ---------------------------------------------------------------------------
# Skip guard — check whether the router's hard deps are importable
# ---------------------------------------------------------------------------

_router_available = importlib.util.find_spec("sentence_transformers") is not None
_sklearn_ok = True
try:
    from sklearn.metrics.pairwise import cosine_similarity  # noqa: F401
except Exception:
    _sklearn_ok = False

pytestmark = pytest.mark.skipif(
    not (_router_available and _sklearn_ok),
    reason="sentence-transformers or sklearn not importable in this environment",
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_mock_registry() -> ToolRegistry:
    """Return a ToolRegistry pre-loaded with two mock tools."""
    from unittest.mock import MagicMock

    registry = ToolRegistry()
    for name, desc in (
        ("get_weather", "Get current weather for a city"),
        ("get_cpu_usage", "Check CPU usage and system performance"),
    ):
        tool = MagicMock()
        tool.name = name
        tool.description = desc
        tool.examples = []
        registry.register(tool)
    return registry


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestUnifiedSemanticRouterInit:
    def test_router_initialises_without_error(self, tmp_path):
        from src.app.services.semantic_router import UnifiedSemanticRouter

        router = UnifiedSemanticRouter(
            registry=_make_mock_registry(),
            model_dir=tmp_path / "Model",
            threshold=0.38,
        )
        router.build_index()
        assert router.is_ready is True

    def test_router_routes_tool_query(self, tmp_path):
        from src.app.services.semantic_router import UnifiedSemanticRouter

        router = UnifiedSemanticRouter(
            registry=_make_mock_registry(),
            model_dir=tmp_path / "Model",
            threshold=0.20,
        )
        router.build_index()
        intent, detail = router.route("check my cpu usage")
        # MoE-first routing: either the owning expert or the tool itself is
        # acceptable — both resolve to the same expert via route_to_profile().
        assert (intent, detail) in (
            ("expert", "monitor_expert"),
            ("tool", "get_cpu_usage"),
        )
        assert router.route_to_profile("check my cpu usage").name == "monitor_expert"

    def test_router_routes_conversational_query(self, tmp_path):
        from src.app.services.semantic_router import UnifiedSemanticRouter

        router = UnifiedSemanticRouter(
            registry=_make_mock_registry(),
            model_dir=tmp_path / "Model",
            threshold=0.38,
        )
        router.build_index()
        intent, detail = router.route("hello how are you")
        assert intent == "conversational"
        assert detail is None

    def test_router_is_not_ready_before_build(self, tmp_path):
        from src.app.services.semantic_router import UnifiedSemanticRouter

        router = UnifiedSemanticRouter(
            registry=_make_mock_registry(),
            model_dir=tmp_path / "Model",
            threshold=0.38,
        )
        # Do NOT call build_index()
        assert router.is_ready is False
