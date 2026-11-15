"""IntentRouter: numpy training, decision rules and fallbacks (fake embedder)."""

from __future__ import annotations

import re

import numpy as np
import pytest

from src.app.services.intent_router import IntentRouter, RouteDecision, train_softmax
from src.app.services.tool_registry import ToolRegistry
from src.infra.tools.base import Tool, ToolCategory


class FakeEmbedder:
    """Deterministic hashed bag-of-words: shared words give similar vectors."""

    fingerprint = "fake-bow"
    dim = 256

    def encode(self, texts, normalize_embeddings=True, show_progress_bar=False):
        single = isinstance(texts, str)
        out = []
        for text in [texts] if single else texts:
            vec = np.zeros(self.dim, dtype=np.float32)
            for token in re.findall(r"[a-z0-9]+", text.lower()):
                vec[sum(ord(c) * (i + 7) for i, c in enumerate(token)) % self.dim] += 1.0
            norm = np.linalg.norm(vec)
            out.append(vec / norm if norm else vec)
        return out[0] if single else np.vstack(out)


def _tool(name: str, category: ToolCategory, description: str) -> Tool:
    return Tool(name=name, function=lambda **_: "ok", category=category, description=description)


@pytest.fixture
def router(tmp_path) -> IntentRouter:
    reg = ToolRegistry()
    reg.register(_tool("get_weather", ToolCategory.WEATHER, "Weather. Trigger: 'weather in Delhi'"))
    reg.register(_tool("start_pomodoro", ToolCategory.TASK_MANAGER, "Start a pomodoro."))
    reg.register(_tool("stop_pomodoro", ToolCategory.TASK_MANAGER, "Stop the pomodoro."))
    reg.register(_tool("fetch_webpage_content", ToolCategory.WEB_RESEARCH, "Fetch a URL."))
    r = IntentRouter(reg, model_dir=tmp_path, embedder=FakeEmbedder())
    r.build()
    assert r.is_ready
    return r


def test_train_softmax_separates_classes():
    x = np.array([[1, 0], [0.9, 0.1], [0, 1], [0.1, 0.9]], dtype=np.float32)
    classes, w, b = train_softmax(x, ["a", "a", "b", "b"])
    assert classes == ["a", "b"]
    pred = (x @ w.T + b).argmax(axis=1)
    assert pred.tolist() == [0, 0, 1, 1]
    # deterministic: same data, same weights
    assert np.array_equal(w, train_softmax(x, ["a", "a", "b", "b"])[1])


def test_url_is_a_hard_rule(router):
    d = router.route("have a look at https://example.com/page please")
    assert d.as_intent() == ("tool", "fetch_webpage_content") and d.reason == "url"


def test_direct_tool_route(router):
    d = router.route("weather in Delhi")
    assert d.kind == "tool" and d.target == "get_weather" and d.category == "weather"


def test_start_and_stop_are_told_apart(router):
    assert router.route("start a pomodoro").target == "start_pomodoro"
    assert router.route("stop the pomodoro").target == "stop_pomodoro"


def test_chat_goes_to_the_llm(router):
    assert router.route("hello").kind == "conversational"
    assert router.route("write a poem").kind in {"content_generation", "conversational"}


def test_multi_step_requests_are_not_dispatched_directly(router):
    d = router.route("weather in Delhi and then start a pomodoro")
    assert d.kind != "tool"


def test_low_tool_margin_defers_to_the_expert(tmp_path):
    reg = ToolRegistry()
    reg.register(_tool("start_pomodoro", ToolCategory.TASK_MANAGER, "Pomodoro."))
    reg.register(_tool("stop_pomodoro", ToolCategory.TASK_MANAGER, "Pomodoro."))
    r = IntentRouter(reg, model_dir=tmp_path, embedder=FakeEmbedder(), tool_margin=1.1)
    r.build()
    d = r.route("start a pomodoro")
    assert d.as_intent() == ("expert", "task_expert") and d.reason == "tool unsure"


def test_not_ready_is_conversational(tmp_path):
    r = IntentRouter(ToolRegistry(), model_dir=tmp_path, embedder=FakeEmbedder())
    assert r.route("weather in Delhi") == RouteDecision(
        "conversational", None, "conversational", 0.0, 0.0, 0.0, "not ready"
    )
    assert r.category_probabilities("x") == {}


def test_build_failure_never_raises(tmp_path):
    class Broken:
        def encode(self, *a, **k):
            raise RuntimeError("no model")

    r = IntentRouter(ToolRegistry(), model_dir=tmp_path, embedder=Broken())
    r.build()
    assert not r.is_ready


def test_embeddings_are_cached(router, tmp_path):
    assert (tmp_path / "intent_router.npz").exists()

    class Exploding(FakeEmbedder):
        def encode(self, texts, **kw):
            if not isinstance(texts, str) and len(texts) > 1:
                raise AssertionError("training phrases must come from the cache")
            return super().encode(texts, **kw)

    again = IntentRouter(router._registry, model_dir=tmp_path, embedder=Exploding())
    again.build()
    assert again.is_ready


def test_expert_for_query(router):
    assert router.expert_for_query("stop the pomodoro") == "task_expert"
    assert router.expert_for_query("hello") == "generalist"  # chat: generalist has every tool


def test_greeting_tool_is_never_routed(tmp_path):
    reg = ToolRegistry()
    reg.register(_tool("get_greeting", ToolCategory.DATETIME, "Greet. Trigger: 'hello', 'hi'"))
    reg.register(_tool("get_weather", ToolCategory.WEATHER, "Weather."))
    r = IntentRouter(reg, model_dir=tmp_path, embedder=FakeEmbedder())
    r.build()
    assert "get_greeting" not in r._tool_names
    assert r.route("hello").kind == "conversational"


def test_explicit_note_command_beats_the_classifier(tmp_path):
    reg = ToolRegistry()
    reg.register(_tool("create_note", ToolCategory.TASK_MANAGER, "Create a note."))
    reg.register(_tool("get_memory_usage", ToolCategory.MONITORING, "Memory usage."))
    r = IntentRouter(reg, model_dir=tmp_path, embedder=FakeEmbedder())
    r.build()
    for text in (
        "take a note saying memory was checked",
        "note: the wifi code is 7788",
        "Please jot down a note about memory usage",
    ):
        d = r.route(text)
        assert d.as_intent() == ("tool", "create_note") and d.reason == "explicit command", text
    assert r.expert_for_query("create a note saying memory was checked") == "task_expert"
    # a second action means the agent, not a direct dispatch
    assert r.route("take a note saying hi and then check memory").reason != "explicit command"
    assert r.route("show memory usage").target == "get_memory_usage"
