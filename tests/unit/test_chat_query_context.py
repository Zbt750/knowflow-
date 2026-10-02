import json
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from backend.chat import service
from backend.chat.evidence import evidence_snapshot
from backend.chat.query_context import contextualize_retrieval_query, is_knowledge_followup


BASE = "解释可导与连续的关系以及|x|的反例。"
FOLLOWUP = "刚才那个反例左右导数各是多少？它证明了哪个方向不能反过来？"


def test_original_baseline_followup_uses_previous_user_not_assistant():
    case = next(json.loads(s) for s in Path("eval/dataset/chat_baseline_v3_1.jsonl").read_text(encoding="utf-8").splitlines()
                if json.loads(s)["id"] == "math-followup")
    result = contextualize_retrieval_query(case["question"], case["setup_questions"])
    assert result.query == BASE + "\n" + FOLLOWUP
    assert result.previous_user_turns == 1
    assert BASE not in str(result.diagnostic())


@pytest.mark.parametrize("question", [
    "什么是TCP可靠传输？", "洛必达法则有哪些条件？", "为什么BFS不适合一般带权图？",
    "刚才那个反例不谈了，另外解释TCP", "刚才那个反例换个新问题", "这份文件怎么部署？",
    "刚才的《积分讲义》讲什么？", "刚才那个反例" + "x" * 181,
])
def test_new_topic_file_or_long_question_does_not_inherit(question):
    assert not is_knowledge_followup(question)
    assert contextualize_retrieval_query(question, [BASE]).query == question


@pytest.mark.parametrize("previous", [
    "", "你好", "继续", "为什么", "刚才那个反例呢？", "解释《数学讲义》的反例",
    "看看我的资料", "x" * 241, "另外解释可导", FOLLOWUP, None,
])
def test_does_not_scan_back_past_ambiguous_or_invalid_previous_turn(previous):
    result = contextualize_retrieval_query(FOLLOWUP, [previous, BASE])
    assert result.query == FOLLOWUP and result.previous_user_turns == 0


@pytest.mark.parametrize("budget,expected", [(0, False), (1000, True)])
def test_query_reaches_search_but_current_prompt_and_mode_stay_original(monkeypatch, budget, expected):
    monkeypatch.setattr(service, "_personal_file_scope_notice", lambda *_, **__: None)
    monkeypatch.setattr(service, "_overview_hits", lambda *_, **__: None)
    monkeypatch.setattr(service, "_detail_material_scope", lambda *_, **__: (None, None))
    previous_calls = []
    def previous(*_, **kwargs):
        previous_calls.append(kwargs)
        return [BASE]
    monkeypatch.setattr(service, "_recent_user_context", previous)
    hit = SimpleNamespace(chunk_id=uuid4(), material_title="合成数学条件讲义",
                          heading_path=("极限与连续",), content="可导必连续；|x|左右导数为-1、1。", kp_ids=(), score=0.03)
    def search(*_, request, **kwargs):
        assert request.query == (BASE + "\n" + FOLLOWUP if expected else FOLLOWUP)
        assert request.filters.source_types == ("user",)
        return SimpleNamespace(hits=[hit])
    monkeypatch.setattr(service, "search_chunks", search)
    db = SimpleNamespace(scalars=lambda *_: SimpleNamespace(all=lambda: []))
    class NoExtraModel:
        def classify_retrieval_intent(self, question):
            raise AssertionError("Explicit follow-up must not introduce a model rewrite/classifier")
    prepared = service._search_pending(db, session_id=uuid4(), assistant_id=uuid4(), question=FOLLOWUP,
                                      mode="user", stack=SimpleNamespace(embedder=None, keyword_index=None, vector_store=None, reranker=None),
                                      provider=NoExtraModel() if expected else None, history_token_budget=budget)
    assert prepared.prompt[-1]["content"] == FOLLOWUP
    assert bool(previous_calls) is expected
    assert prepared.matched_kp_id is None
    assert evidence_snapshot(prepared)["retrieval_query_context"]["previous_user_turns"] == int(expected)
