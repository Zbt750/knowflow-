from types import SimpleNamespace
from uuid import uuid4

import pytest

from backend.chat import service
from backend.chat.file_scope import ambiguous_mentions, filename_suggestion, matching_materials


def doc(title, filename=None):
    return SimpleNamespace(id=uuid4(), title=title, original_filename=filename)


def test_spaced_citation_aliases_are_validated_and_code_is_untouched():
    chunk = uuid4()
    text, normalized, unknown = service._normalize_known_citation_aliases(
        "依据[ C1 ]和[C 1]。伪编号[ C99 ]。`[ C1 ]`", {"C1": chunk}
    )
    assert text == "依据[C1]和[C1]。伪编号。`[ C1 ]`"
    assert normalized == ["C1"]
    assert unknown == ["C99"]


@pytest.mark.parametrize("base,model,expected", [
    ("https://api.deepseek.com", "deepseek-flash", {"reasoning_effort": "low"}),
    ("https://api.deepseek.com/v1", "deepseek-v4-pro", {"reasoning_effort": "low"}),
    ("https://other.example", "deepseek-flash", {}),
    ("https://api.deepseek.com", "other-model", {}),
])
def test_provider_options_only_apply_to_documented_official_models(base, model, expected):
    provider = service.Provider(api_key="test", base_url=base, model=model, timeout=5, max_tokens=1000)
    assert provider._request_options() == expected
    assert provider._request_options(classifier=True) == ({"thinking": {"type": "disabled"}} if expected else {})


@pytest.mark.parametrize("question", [
    "对比极限与导数讲义和积分专题讲义，各举一个文件里的例子。",
    "比较《积分专题讲义》和《极限与导数讲义》，两份讲什么？",
    "我上传的极限导数讲义与积分讲义有什么不同？",
])
def test_independent_mentions_keep_short_title_and_abbreviation(question):
    a, b = doc("极限与导数讲义"), doc("积分专题讲义")
    assert {d.id for d in matching_materials([a, b], question)} == {a.id, b.id}
    assert not ambiguous_mentions([a, b], question)


def test_contained_prefix_is_not_another_file_but_independent_short_mention_is():
    a, b = doc("验收"), doc("阶段A验收笔记")
    assert matching_materials([a, b], "阶段A验收笔记讲什么？") == [b]
    assert {d.id for d in matching_materials([a, b], "对比《验收》和《阶段A验收笔记》")} == {a.id, b.id}


def test_duplicates_still_require_confirmation():
    a, b = doc("验收笔记"), doc("验收笔记")
    assert ambiguous_mentions([a, b], "验收笔记讲什么？")


def test_literal_document_shorthand_requires_explicit_file_and_keeps_ambiguity():
    a = doc("合成项目阶段说明")
    assert matching_materials([a], "阶段说明这份文件讲了哪些阶段？") == [a]
    assert matching_materials([a], "解释阶段说明") == []
    assert matching_materials([a], "说明这份文件") == []
    b = doc("另一个项目阶段说明")
    assert ambiguous_mentions([a, b], "阶段说明这份文件讲什么？")
    assert matching_materials([a, b], "合成项目阶段说明这份文件讲什么？") == [a]
    assert matching_materials([a], "不要读取阶段说明这份文件") == []


def test_prompt_keeps_cross_file_classification_and_current_followup_scope():
    hits = [SimpleNamespace(chunk_id=uuid4(), material_title=name, heading_path=("F",), content="持久化") for name in ("阶段说明", "部署补充")]
    prompt, _ = service._prompt("共同与独有内容是什么", hits, [], mode="user", full_document=True)
    assert "只列为共同点" in prompt[0]["content"]
    assert "负环可达该目标" in prompt[0]["content"]
    assert "历史用于解析指代，不扩大当前任务" in prompt[0]["content"]
    assert "还能从该负环到达的目标" in service.GENERAL_SYSTEM_PROMPT
    assert "事实分类输出" in prompt[0]["content"]
    assert "每份文件的支持引用" in prompt[0]["content"]
    assert "紧凑比较格式" in prompt[0]["content"]
    assert "全文覆盖清单" not in prompt[0]["content"]
    assert "分类完即可结束" in prompt[0]["content"]


def test_comparison_does_not_remove_chapter_coverage_from_other_overviews():
    hits = [SimpleNamespace(chunk_id=uuid4(), material_title=name, heading_path=(name, "章节"), content="内容") for name in ("阶段说明", "部署补充")]
    prompt, _ = service._prompt("两份资料各讲什么？", hits, [], mode="user", full_document=True)
    assert "全文覆盖清单" in prompt[0]["content"]
    assert "事实分类输出" not in prompt[0]["content"]


def test_detailed_comparison_keeps_detail_instead_of_forcing_compact_table():
    hits = [SimpleNamespace(chunk_id=uuid4(), material_title=name, heading_path=("F",), content="持久化") for name in ("阶段说明", "部署补充")]
    prompt, _ = service._prompt("详细解释共同与独有内容", hits, [], mode="user", full_document=True)
    assert "每份文件的支持引用" in prompt[0]["content"]
    assert "紧凑比较格式" not in prompt[0]["content"]


@pytest.mark.parametrize("profile,first,retry,expected", [
    ("multi_file_comparison", 4000, 8000, 6000),
    ("multi_file_comparison", 2000, 4000, 4000),
    ("multi_file_comparison", 8000, 16000, 8000),
    ("normal", 4000, 8000, 4000),
])
def test_comparison_budget_is_request_local_and_bounded(profile, first, retry, expected):
    provider = service.Provider(api_key="test", base_url="https://example.invalid", model="test", timeout=30, max_tokens=first, retry_max_tokens=retry)
    prepared = service.PreparedAnswer(uuid4(), [], {}, None, "hybrid", generation_profile=profile)
    scoped = service._provider_for_answer(provider, prepared)
    assert scoped._token_budget(1) == expected
    assert scoped._token_budget(2) == retry
    assert provider.max_tokens == first


def test_comparison_budget_preserves_protocol_test_double():
    provider = SimpleNamespace()
    prepared = service.PreparedAnswer(uuid4(), [], {}, None, "hybrid", generation_profile="multi_file_comparison")
    assert service._provider_for_answer(provider, prepared) is provider


def test_equal_length_distinct_titles_are_not_ambiguous():
    a, b = doc("蓝杉学习计划-2024旧版"), doc("蓝杉学习计划-2026新版")
    assert not ambiguous_mentions([a, b], "概述《蓝杉学习计划-2024旧版》和《蓝杉学习计划-2026新版》")
    assert len(matching_materials([a, b], "概述《蓝杉学习计划-2024旧版》和《蓝杉学习计划-2026新版》")) == 2


def test_explicit_do_not_read_is_respected():
    a, b = doc("积分专题讲义"), doc("极限与导数讲义")
    assert matching_materials([a, b], "只使用《积分专题讲义》，不要读取《极限与导数讲义》") == [a]


def test_typo_is_suggested_not_silently_selected():
    a = doc("积分专题讲义")
    q = "我上传的《积分专题讲议》讲什么？"
    assert matching_materials([a], q) == []
    assert "《积分专题讲义》" in filename_suggestion([a], q)
    assert "确认" in filename_suggestion([a], q)
    assert filename_suggestion([a], "《完全不存在的资料》讲什么？") is None


def test_detail_accepts_two_explicit_files_but_not_duplicate_names(monkeypatch):
    a, b = doc("极限与导数讲义"), doc("积分专题讲义")
    monkeypatch.setattr(service, "_ready_materials", lambda *_: [a, b])
    ids, notice = service._detail_material_scope(None, session_id=uuid4(), question="比较极限与导数讲义和积分专题讲义", mode="user")
    assert set(ids) == {a.id, b.id} and notice is None


def test_plural_followup_keeps_both_named_files(monkeypatch):
    a, b = doc("极限与导数讲义"), doc("积分专题讲义")
    monkeypatch.setattr(service, "_ready_materials", lambda *_: [a, b])
    monkeypatch.setattr(service, "_recent_user_context", lambda *_, **__: ["比较极限与导数讲义和积分专题讲义"])
    ids, notice = service._detail_material_scope(None, session_id=uuid4(), question="这两份文件分别举一个例子", mode="user")
    assert set(ids) == {a.id, b.id} and notice is None


@pytest.mark.parametrize("question", ["它后半部分的E、F、G具体要求什么？", "它的后半部分讲什么？", "这份的第七章有什么？"])
def test_structured_pronoun_followup_inherits_shorthand_file_only(monkeypatch, question):
    a, b = doc("合成项目阶段说明"), doc("合成部署边界补充")
    monkeypatch.setattr(service, "_ready_materials", lambda *_: [a, b])
    monkeypatch.setattr(service, "_recent_user_context", lambda *_, **__: ["阶段说明这份文件讲了哪些阶段？"])
    ids, notice = service._detail_material_scope(None, session_id=uuid4(), question=question, mode="user")
    assert ids == (a.id,) and notice is None


def test_structured_file_followup_does_not_borrow_ambiguous_or_math_context(monkeypatch):
    a, b = doc("合成项目阶段说明"), doc("另一项目阶段说明")
    monkeypatch.setattr(service, "_ready_materials", lambda *_: [a, b])
    monkeypatch.setattr(service, "_recent_user_context", lambda *_, **__: ["阶段说明这份文件讲什么？"])
    ids, notice = service._detail_material_scope(None, session_id=uuid4(), question="它后半部分讲什么？", mode="user")
    assert ids is None and "确认" in notice
    assert not service._is_file_reference_question("刚才那个反例左右导数各是多少？")


@pytest.mark.parametrize("question", ["它后半部分有什么条件？", "它前半部分与后半部分有何不同？"])
def test_singular_followup_after_two_distinct_files_asks_in_both_paths(monkeypatch, question):
    a, b = doc("极限与导数讲义"), doc("积分专题讲义")
    previous = "比较极限与导数讲义和积分专题讲义"
    monkeypatch.setattr(service, "_ready_materials", lambda *_: [a, b])
    monkeypatch.setattr(service, "_recent_user_context", lambda *_, **__: [previous])
    ids, notice = service._detail_material_scope(None, session_id=uuid4(), question=question, mode="user")
    assert ids is None and "确认" in notice
    overview = service._overview_hits(None, question="这份文件主要讲什么？", mode="user", reference_context=[previous])
    assert overview.hits == [] and "确认" in overview.direct_response


def test_followup_scope_reaches_retrieval_filters_and_actual_prompt(monkeypatch):
    a, b = doc("合成项目阶段说明"), doc("合成部署边界补充")
    monkeypatch.setattr(service, "_ready_materials", lambda *_: [a, b])
    monkeypatch.setattr(service, "_recent_user_context", lambda *_, **__: ["阶段说明这份文件讲了哪些阶段？"])
    requests = []
    hit = SimpleNamespace(chunk_id=uuid4(), material_title=a.title, heading_path=("阶段E",), content="窄屏一致")
    def search(db, *, request, **kwargs):
        requests.append(request)
        assert request.filters.material_ids == (a.id,)
        assert request.filters.source_types == ("user",)
        return SimpleNamespace(hits=[hit])
    monkeypatch.setattr(service, "search_chunks", search)
    class Classifier:
        def classify_retrieval_intent(self, question):
            raise AssertionError("Resolved file must not add a model classifier call")
    db = SimpleNamespace(scalars=lambda *_: SimpleNamespace(all=lambda: []))
    prepared = service._search_pending(db, session_id=uuid4(), assistant_id=uuid4(), question="它后半部分具体要求什么？", mode="user",
                                      stack=SimpleNamespace(embedder=None, vector_store=None, keyword_index=None, reranker=None), provider=Classifier(), history_token_budget=0)
    assert len(requests) == 1
    assert prepared.prompt[-2]["content"].endswith("窄屏一致")
    assert b.title not in prepared.prompt[-2]["content"]


def test_prompt_keeps_units_conditions_and_both_file_targets():
    hits = [SimpleNamespace(chunk_id=uuid4(), material_title=name, heading_path=(name, "例题"), content="样本数20；可导内点极值的导数为0。") for name in ("极限与导数讲义", "积分专题讲义")]
    prompt, _ = service._prompt("对比这两份文件各举一个例子", hits, [], mode="user", full_document=True)
    system = prompt[0]["content"]
    assert "极限与导数讲义、积分专题讲义" in system
    assert "样本数不能擅自改成人数" in system
    assert "可导的内点极值" in system


def test_known_plus_unknown_explicit_file_is_not_silently_replaced(monkeypatch):
    a = doc("积分专题讲义")
    monkeypatch.setattr(service, "_ready_materials", lambda *_: [a])
    result = service._overview_hits(None, question="比较《积分专题讲义》和《不存在的文件》", mode="user")
    assert result.hits == [] and "不存在的文件" in result.direct_response


def test_resolved_named_file_does_not_pay_for_model_intent_classifier(monkeypatch):
    a = doc("验收笔记")
    monkeypatch.setattr(service, "_ready_materials", lambda *_: [a])
    monkeypatch.setattr(service, "_personal_file_scope_notice", lambda *_, **__: None)
    monkeypatch.setattr(service, "_overview_hits", lambda *_, **__: None)
    monkeypatch.setattr(service, "search_chunks", lambda *_, **__: SimpleNamespace(hits=[]))
    class Classifier:
        def classify_retrieval_intent(self, question):
            raise AssertionError("Named scope must not make an extra model call")
    db = SimpleNamespace(scalars=lambda *_: SimpleNamespace(all=lambda: []))
    prepared = service._search_pending(db, session_id=uuid4(), assistant_id=uuid4(), question="验收笔记里的勾股与圆的联系", mode="user", stack=SimpleNamespace(embedder=None, vector_store=None, keyword_index=None, reranker=None), provider=Classifier(), history_token_budget=0)
    assert prepared.preparation_duration_ms >= 0
