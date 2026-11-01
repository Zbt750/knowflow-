"""Explicit bank-source requests must never silently invoke question generation."""
import pytest

from backend.schemas.learning_assistant import StudyContext
from backend.services.assistant_router import CapabilityRoute, route_message
from backend.services.learning_assistant_service import _may_continue_generation
from backend.services.personal_generation_intent import explicitly_generate


@pytest.mark.parametrize('message', [
    '给我从我的题库来一道这样类似的题加到我今日卷里',
    '从我的题库里出一道相似题，不要新编。',
    '从已有题目找一道类似的题，加入今日卷。',
    '从我的题库找一道类似的题。',
])
def test_existing_bank_source_blocks_generation_even_with_pending_generation(message):
    route = route_message(message, StudyContext())
    assert not explicitly_generate(message)
    assert route.reason in {'explicit_bank_selection', 'explicit_read_only_bank_selection'}
    if route.reason == 'explicit_read_only_bank_selection':
        assert (route.capability, route.intent) == ('data_query', 'find')
    else:
        assert (route.capability, route.intent) == ('planner', 'plan')
    assert not _may_continue_generation(route, mode='builtin', qa_action='auto',
        generation_requested=False, generation_continuation=True)


@pytest.mark.parametrize('message', [
    '根据这个知识点新编一道题，不用查我的题库。',
    '题库里没有合适的题，你直接生成一道新的。',
    '不用查题库，直接出题。',
])
def test_explicit_new_generation_is_not_blocked_by_unrelated_bank_mention(message):
    assert explicitly_generate(message)


def test_readonly_bank_selection_cannot_resume_pending_generation():
    route = CapabilityRoute('data_query', 'find', 1, 'read_only_question_preview')
    assert not _may_continue_generation(route, mode='builtin', qa_action='auto',
        generation_requested=False, generation_continuation=True)

@pytest.mark.parametrize('message',['不要新编一道题','不自动新编题','今天先复习，不要自动生成新题。'])
def test_negated_generation_is_not_authorized(message):
    assert not explicitly_generate(message)

@pytest.mark.parametrize('message',['请解释新编题是什么意思','奶蛙能否介绍新编题功能'])
def test_explaining_generation_is_not_a_generation_request(message):
    assert not explicitly_generate(message)
