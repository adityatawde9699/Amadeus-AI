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


def test_routing_heldout_has_no_training_leak():
    from evals.routing_eval import load_heldout

    assert len(load_heldout()) >= 60  # raises on leak / unknown category


def test_routing_metrics():
    from evals.routing_eval import metrics

    m = metrics(["weather", "news", "news"], ["weather", "news", "weather"],
                [["weather"], ["news"], ["weather", "news"]])
    assert m["accuracy"] == pytest.approx(2 / 3)
    assert m["top2_accuracy"] == 1.0
    assert m["confusions"] == [("news -> weather", 1)]


# Floor for the Stage-1 classifier on held-out data (baseline 88.7% when added,
# evals/results/routing.md). Fails CI if TRAINING_DATA edits regress routing.
ROUTING_HELDOUT_FLOOR = 0.80


def test_routing_quality_floor():
    pytest.importorskip("sklearn")
    from evals.routing_eval import heldout_eval, load_heldout

    result = heldout_eval(load_heldout())
    assert result["accuracy"] >= ROUTING_HELDOUT_FLOOR, result["errors"]
