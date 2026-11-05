"""Validation contract tests, not semantic quality measurements."""
import json
from types import SimpleNamespace

import pytest

from backend.retrieval.embedding import FakeEmbedder
from scripts import validate_context_relevance as validation
from scripts.probe_context_relevance import STRATEGIES


def test_new_validation_has_disjoint_case_ids_and_same_frozen_strategies():
    from scripts.probe_context_relevance import load_cases
    _, calibration = load_cases()
    data = json.loads(validation.DATASET.read_text(encoding="utf-8"))
    assert len(data["cases"]) == 18
    assert not {c["id"] for c in calibration} & {c["id"] for c in data["cases"]}
    assert validation.STRATEGIES == STRATEGIES
    assert len([c for c in data["cases"] if not c["required_headings"]]) == 2


def test_long_sections_really_span_multiple_canonical_chunks():
    records = validation.validation_records()
    data = json.loads(validation.DATASET.read_text(encoding="utf-8"))
    validation.validate_cases(data, records)
    for heading in ("乘积求导的条件与使用边界", "换元积分的界限与反向遍历"):
        chunks = [r for r in records if heading in r.heading_path]
        assert len(chunks) >= 2 and all(len(r.content) <= 700 for r in chunks)
    case = next(c for c in data["cases"] if c["id"] == "v-long-product")
    assert not any(all(f in r.content for f in case["required_fragments"]) for r in records)


def test_heading_present_does_not_mean_all_required_evidence_present():
    case = {"required_headings": ["条件"], "required_fragments": ["需要可导", "逆向反例"]}
    hit = SimpleNamespace(heading_path=("条件",), content="需要可导")
    result = validation.evidence_measure([hit], case)
    assert result["all_required_present"] is True
    assert result["all_required_evidence_present"] is False
    assert result["missing_fragments"] == ["逆向反例"]


def test_correct_fragment_from_unrelated_heading_cannot_fill_evidence_gap():
    case = {"required_headings": ["条件"], "required_fragments": ["需要可导", "逆向反例"]}
    hits = [SimpleNamespace(heading_path=("条件",), content="需要可导"),
            SimpleNamespace(heading_path=("无关",), content="逆向反例")]
    assert validation.evidence_measure(hits, case)["missing_fragments"] == ["逆向反例"]


def test_absent_topic_is_not_vacuously_counted_as_coverage_pass():
    result = validation.evidence_measure([], {"required_headings": []})
    assert result["all_required_present"] is None
    assert result["all_required_evidence_present"] is None
    assert result["absent_topic_false_evidence"] is False


@pytest.mark.parametrize("cases,error", [
    ([{"id": "dup", "required_headings": []}] * 2, "Duplicate"),
    ([{"id": "old", "required_headings": ["已删除"]}], "Stale heading"),
    ([{"id": "old", "required_headings": ["条件"], "required_fragments": ["没写的内容"]}], "Unlocatable fragment"),
])
def test_bad_labels_fail_explicitly(cases, error):
    records = [SimpleNamespace(heading_path=("条件",), content="需要可导")]
    with pytest.raises(ValueError, match=error):
        validation.validate_cases({"cases": cases}, records)


def test_validation_wiring_retains_all_cases_and_no_real_quality_claim():
    report = validation.run_validation(FakeEmbedder())
    assert len(report["cases"]) == 18
    assert not report["production_policy_changed"] and not report["database_access"]
    assert report["external_model_calls"] == 0
    assert report["ragas_metrics"] is None and report["observed_usage"] is None
    assert report["embedding_model"] == "fake-embedder-v1"
    assert report["summary"]["baseline"]["answerable_cases"] == 16
    assert "backend/ingestion/chunker.py" in report["source_sha256"]
    assert all(set(c["strategies"]) == set(STRATEGIES) for c in report["cases"])


def test_existing_validation_report_refuses_overwrite(tmp_path, monkeypatch):
    output = tmp_path / "existing.json"
    output.write_text("unchanged", encoding="utf-8")
    monkeypatch.setattr(validation.sys, "argv", ["validation", "--output", str(output)])
    with pytest.raises(SystemExit) as error:
        validation.main()
    assert error.value.code == 2 and output.read_text(encoding="utf-8") == "unchanged"
