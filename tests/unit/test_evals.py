"""
Eval harness: scoring logic, dataset integrity, and a routing-quality floor.
"""

from __future__ import annotations

import pytest


def test_agent_judge_rules():
    from evals.agent_eval import Case, judge

    case = Case(task="t", expert="e", expect=["add_task"], args={"task_content|content": "milk"})
    assert judge(case, "add_task", {"content": "buy MILK"}) == (True, "ok")
    assert judge(case, "add_task", {"task_content": "eggs"})[0] is False
    assert judge(case, "add_task", {})[1] == "missing arg task_content|content"
    assert judge(case, "list_tasks", {"content": "milk"})[1] == "wrong tool list_tasks"
    assert judge(case, None, {})[0] is False


def test_agent_dataset_is_well_formed():
    from evals.agent_eval import load_cases

    cases = load_cases()
    assert len(cases) >= 20
    assert all(c.expect and c.task for c in cases)


def test_rag_scoring():
    from evals.rag_eval import score

    rankings = [["a.md", "b.md"], ["c.md", "a.md"], ["x.md"]]
    relevant = [{"a.md"}, {"a.md"}, {"a.md"}]
    m = score(rankings, relevant)
    assert m["recall@1"] == pytest.approx(1 / 3)
    assert m["recall@3"] == pytest.approx(2 / 3)
    assert m["mrr"] == pytest.approx((1 + 0.5 + 0) / 3)


def test_rag_dataset_points_at_real_pages():
    from pathlib import Path

    import yaml

    root = Path(__file__).resolve().parents[2]
    spec = yaml.safe_load((root / "evals/datasets/rag_queries.yaml").read_text())
    pages = {p.name for p in (root / spec["corpus"]).glob("*.md")}
    for q in spec["queries"]:
        assert set(q["relevant"]) <= pages, q


def test_routing_datasets_have_no_training_leak():
    from evals.routing_eval import load_e2e, load_heldout

    assert len(load_heldout()) >= 60  # raises on leak / unknown category
    assert len(load_e2e()) >= 60  # raises on leak


def test_routing_metrics():
    from evals.routing_eval import metrics

    m = metrics(
        ["weather", "news", "news"],
        ["weather", "news", "weather"],
        [["weather"], ["news"], ["weather", "news"]],
    )
    assert m["accuracy"] == pytest.approx(2 / 3)
    assert m["top2_accuracy"] == 1.0
    assert m["confusions"] == [("news -> weather", 1)]


# Floors for the LLM-free router on held-out data (evals/results/routing.md had
# 95.7% category accuracy, 94.7% end to end, 83.6% LLM-free when added). They
# fail CI if routing_data.py, the thresholds or the slot rules regress routing.
ROUTING_HELDOUT_FLOOR = 0.88
ROUTING_E2E_FLOOR = 0.88
ROUTING_LLM_FREE_FLOOR = 0.70
ROUTING_MAX_WRONG_DISPATCHES = 3


@pytest.fixture(scope="module")
def routing_report():
    from evals.routing_eval import build_router, e2e_eval, heldout_eval, load_e2e, load_heldout

    try:
        router, registry = build_router()
    except Exception as exc:  # no embedding backend in this environment
        pytest.skip(f"intent router unavailable: {exc}")
    return {
        "heldout": heldout_eval(load_heldout(), router),
        "e2e": e2e_eval(load_e2e(), router, registry),
    }


def test_routing_category_floor(routing_report):
    h = routing_report["heldout"]
    assert h["accuracy"] >= ROUTING_HELDOUT_FLOOR, h["errors"]


def test_routing_end_to_end_floor(routing_report):
    e = routing_report["e2e"]
    assert e["correct"] >= ROUTING_E2E_FLOOR, e["failures"]
    assert e["llm_free_rate"] >= ROUTING_LLM_FREE_FLOOR, e["needs_llm"]
    assert e["wrong_dispatches"] <= ROUTING_MAX_WRONG_DISPATCHES, e["failures"]
