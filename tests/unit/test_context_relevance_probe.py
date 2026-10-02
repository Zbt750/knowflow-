"""Probe mechanics only: fake vectors do not establish semantic retrieval quality."""
from types import SimpleNamespace

import pytest

from backend.retrieval.embedding import FakeEmbedder
from scripts import probe_context_relevance as probe


def hit(score, *headings):
    return SimpleNamespace(vector_score=score, heading_path=headings)


def test_baseline_preserves_order_and_identity_without_mutating():
    hits = [hit(0.4), hit(0.8)]
    selected = probe.select_experiment(hits, "baseline")
    assert selected == hits and selected is not hits
    assert hits[0].vector_score == 0.4


@pytest.mark.parametrize("strategy,expected", [
    ("cosine_0.50", [0.5, 0.7]), ("cosine_0.60", [0.7]),
    ("cosine_0.70", [0.7]), ("relative_0.85", [0.7]),
])
def test_absolute_and_relative_cuts_are_stable_and_include_boundary(strategy, expected):
    hits = [hit(0.4), hit(0.5), hit(0.7)]
    assert [h.vector_score for h in probe.select_experiment(hits, strategy)] == expected
    assert len(hits) == 3


def test_unknown_and_nonfinite_scores_are_not_silently_discarded():
    unknown, nan = hit(None), hit(float("nan"))
    assert probe.select_experiment([hit(0.8), unknown, nan, hit(0.2)], "cosine_0.70")[1:] == [unknown, nan]
    assert probe.select_experiment([unknown], "relative_0.85") == [unknown]
    assert probe.select_experiment([], "relative_0.85") == []


def test_rrf_score_is_not_used_as_cosine():
    high_rrf_low_cosine = hit(0.2)
    high_rrf_low_cosine.score = 100
    assert probe.select_experiment([high_rrf_low_cosine], "cosine_0.50") == []


def test_unknown_strategy_rejected():
    with pytest.raises(ValueError, match="Unknown strategy"):
        probe.select_experiment([], "production_default")


def test_coverage_counts_distinct_required_sections_not_duplicate_chunks():
    result = probe.measure([hit(0.8, "条件"), hit(0.7, "条件"), hit(0.6, "无关")], ["条件", "反例"])
    assert result["useful_count"] == 2
    assert result["required_heading_recall"] == 0.5
    assert result["missing_headings"] == ["反例"]
    assert not result["all_required_present"]


def test_no_evidence_precision_is_na_not_perfect():
    result = probe.measure([], ["条件"])
    assert result["relevant_fraction"] is None and result["required_heading_recall"] == 0
    absent = probe.measure([], [])
    assert absent["required_heading_recall"] is None
    assert absent["absent_topic_false_evidence"] is False
    assert probe.measure([hit(0.5, "条件")], [])["absent_topic_false_evidence"] is True


def test_all_fixed_cases_have_explicit_labels_and_keep_absent_case():
    _, cases = probe.load_cases()
    assert len(cases) == 16 and len({c["id"] for c in cases}) == 16
    assert next(c for c in cases if c["id"] == "absent-topic")["required_headings"] == []
    assert len(next(c for c in cases if c["id"] == "multi-408")["required_headings"]) == 3


def test_probe_wiring_keeps_all_failures_and_states_boundaries_with_fake_model():
    report = probe.run_probe(FakeEmbedder())
    assert len(report["cases"]) == 16
    assert report["external_model_calls"] == 0 and not report["database_access"]
    assert not report["production_policy_changed"]
    assert report["ragas_metrics"] is None and report["observed_generation_usage"] is None
    assert report["embedding_model"] == "fake-embedder-v1"
    assert "not_independent" in report["label_review_status"]
    assert all(set(c["strategies"]) == set(probe.STRATEGIES) for c in report["cases"])
    # Labels must only score retrieval; they are not passed into the selector.
    assert "required_headings" not in probe.select_experiment.__code__.co_varnames


def test_stale_required_heading_fails_instead_of_silently_lowering_recall(monkeypatch):
    monkeypatch.setattr(probe, "load_cases", lambda: ({}, [{"id": "stale", "required_headings": ["不存在章节"]}]))
    with pytest.raises(ValueError, match="Stale label"):
        probe.run_probe(FakeEmbedder())


def test_existing_report_is_not_overwritten_or_model_loaded(tmp_path, monkeypatch):
    output = tmp_path / "existing.json"
    output.write_text("frozen", encoding="utf-8")
    monkeypatch.setattr(probe.sys, "argv", ["probe", "--output", str(output)])
    with pytest.raises(SystemExit) as error:
        probe.main()
    assert error.value.code == 2 and output.read_text(encoding="utf-8") == "frozen"
