from types import SimpleNamespace
from uuid import uuid4

import pytest

from backend.chat import service
from backend.chat.context_screening import MIN_COSINE, POLICY_VERSION, screen_context
from backend.chat.evidence import evidence_snapshot, validate_evidence_snapshot
from backend.config import Settings


def hit(cosine, text="合成正文"):
    return SimpleNamespace(vector_score=cosine, score=999, chunk_id=uuid4(), material_id=uuid4(),
                           content=text, material_title="测试讲义", heading_path=("测试章节",), kp_ids=())


@pytest.mark.parametrize("mode,count,applied", [("off", 2, False), ("shadow", 2, False), ("filter", 1, True)])
def test_modes_are_explicit_stable_and_use_raw_cosine(mode, count, applied):
    source = [hit(0.3), hit(MIN_COSINE)]
    result = screen_context(source, mode=mode)
    assert len(result.hits) == count and result.diagnostic["applied"] is applied
    assert len(source) == 2
    assert result.hits[-1] is source[-1]
    assert result.diagnostic["version"] == POLICY_VERSION
    assert "正文" not in str(result.diagnostic)
    assert str(source[0].chunk_id) not in str(result.diagnostic)


@pytest.mark.parametrize("raw", [None, float("nan"), float("inf"), "0.2", True])
def test_unknown_vector_score_is_protected_not_rank_score_fallback(raw):
    original = hit(raw)
    result = screen_context([original], mode="filter")
    assert result.hits == [original] and result.diagnostic["unknown_score_count"] == 1


@pytest.mark.parametrize("reason", ["file_scope", "document_request", "comprehensive", "degraded_retrieval", "reranked_unvalidated"])
def test_bypass_does_not_screen(reason):
    low = hit(0.1)
    result = screen_context([low], mode="filter", bypass_reason=reason)
    assert result.hits == [low] and not result.diagnostic["applied"]
    assert result.diagnostic["reason"] == reason


def test_all_low_scores_return_empty_not_a_fabricated_first_hit():
    assert screen_context([hit(0.49)], mode="filter").hits == []
    assert screen_context([], mode="filter").diagnostic["after_count"] == 0
    with pytest.raises(ValueError):
        screen_context([], mode="auto")


def test_configuration_defaults_off_and_rejects_unbounded_policy():
    settings = Settings(_env_file=None, database_url="postgresql://test:test@localhost/sample",
                        chat_context_screening="off")
    assert Settings.model_fields["chat_context_screening"].default == "off"
    assert settings.chat_context_screening == "off"
    with pytest.raises(ValueError):
        Settings(_env_file=None, database_url="postgresql://test:test@localhost/sample", chat_context_screening="0.70")


def prepare(monkeypatch, *, mode="filter", hits=None, scoped=False, diversified=False,
            degraded=False, reranked=False, overview=False, question="什么是连续？", chat_mode="builtin"):
    from backend import config
    monkeypatch.setattr(config, "get_settings", lambda: SimpleNamespace(chat_context_screening=mode))
    source = hits if hits is not None else [hit(0.2, "无关线程正文"), hit(0.8, "可导必连续")]
    monkeypatch.setattr(service, "_personal_file_scope_notice", lambda *_, **__: None)
    overview_result = SimpleNamespace(hits=source, direct_response=None, full_document=True) if overview else None
    monkeypatch.setattr(service, "_overview_hits", lambda *_, **__: overview_result)
    monkeypatch.setattr(service, "_detail_material_scope", lambda *_, **__: ((uuid4(),) if scoped else None, None))
    monkeypatch.setattr(service, "build_chat_retrieval_plan", lambda *_, **__: SimpleNamespace(
        intent="explain", classified_by="rules", top_k=12, candidate_k=36, diversify=diversified))
    monkeypatch.setattr(service, "search_chunks", lambda *_, **__: SimpleNamespace(
        hits=source, degraded=degraded, reranked=reranked))
    attribution_inputs = []
    def attribution(actual):
        attribution_inputs.append(list(actual))
        return None
    monkeypatch.setattr(service, "matched_kp_attribution", attribution)
    db = SimpleNamespace(scalars=lambda *_: SimpleNamespace(all=lambda: []))
    prepared = service._search_pending(db, session_id=uuid4(), assistant_id=uuid4(), question=question,
                                      mode=chat_mode, stack=SimpleNamespace(embedder=None, keyword_index=None,
                                      vector_store=None, reranker=None), history_token_budget=0)
    return prepared, source, attribution_inputs


@pytest.mark.parametrize("mode,count", [("off", 2), ("shadow", 2), ("filter", 1)])
def test_final_prompt_citations_snapshot_and_attribution_use_same_selected_hits(monkeypatch, mode, count):
    prepared, source, attribution_inputs = prepare(monkeypatch, mode=mode)
    assert attribution_inputs == [source if count == 2 else source[1:]]
    assert len(prepared.citation_map) == count
    assert list(prepared.citation_map) == [f"C{i}" for i in range(1, count + 1)]
    snapshot = evidence_snapshot(prepared)
    validate_evidence_snapshot(snapshot, str(prepared.assistant_id))
    assert len(snapshot["blocks"]) == count
    if mode == "filter":
        assert prepared.citation_map["C1"] == source[1].chunk_id
        assert "无关线程正文" not in str(prepared.prompt)
    assert snapshot["context_screening"]["after_count"] == count


@pytest.mark.parametrize("kwargs,reason", [
    ({"scoped": True}, "file_scope"), ({"diversified": True}, "comprehensive"),
    ({"degraded": True}, "degraded_retrieval"), ({"reranked": True}, "reranked_unvalidated"),
    ({"question": "比较两份文件共同要求"}, "document_request"),
])
def test_actual_service_bypasses_unvalidated_paths(monkeypatch, kwargs, reason):
    prepared, _, _ = prepare(monkeypatch, **kwargs)
    assert len(prepared.citation_map) == 2
    assert prepared.context_screening["reason"] == reason
    assert not prepared.context_screening["applied"]


def test_overview_never_enters_generic_screening(monkeypatch):
    prepared, _, attribution_inputs = prepare(monkeypatch, overview=True)
    assert len(prepared.citation_map) == 2 and prepared.context_screening is None
    assert attribution_inputs == []
    validate_evidence_snapshot(evidence_snapshot(prepared), str(prepared.assistant_id))


def test_empty_filtered_evidence_enters_labeled_general_reference_without_citations(monkeypatch):
    prepared, _, attribution_inputs = prepare(monkeypatch, hits=[hit(0.2)])
    assert prepared.retrieval_mode == "general"
    assert prepared.citation_map == {} and prepared.evidence_blocks == ()
    assert attribution_inputs == [[]]
    snapshot = evidence_snapshot(prepared)
    assert snapshot["contexts"] == [] and snapshot["citations"] == {}
    validate_evidence_snapshot(snapshot, str(prepared.assistant_id))


def test_user_mode_does_not_gain_knowledge_attribution_after_filter(monkeypatch):
    prepared, _, attribution_inputs = prepare(monkeypatch, chat_mode="user")
    assert len(prepared.citation_map) == 1
    assert prepared.matched_kp_id is None and attribution_inputs == []


def test_evaluation_manifest_records_policy_without_private_configuration(monkeypatch, tmp_path):
    from scripts import rag_baseline_manifest as manifest
    monkeypatch.setattr(manifest.subprocess, "check_output", lambda *_, **__: b"synthetic")
    dataset = tmp_path / "synthetic.jsonl"
    dataset.write_text("{}", encoding="utf-8")
    settings = SimpleNamespace(llm_model="synthetic", embedding_model="synthetic", reranker_model=None,
        llm_timeout_seconds=1, llm_max_output_tokens=10, llm_retry_max_output_tokens=20,
        llm_history_token_budget=100, llm_stream_include_usage=False, chat_context_screening="shadow",
        llm_api_key="DO_NOT_RECORD", database_url="DO_NOT_RECORD")
    result = manifest.build_manifest(settings, dataset, False)
    assert result["context_screening_configuration"] == {
        "mode": "shadow", "version": POLICY_VERSION, "min_cosine": MIN_COSINE}
    assert "DO_NOT_RECORD" not in str(result)
