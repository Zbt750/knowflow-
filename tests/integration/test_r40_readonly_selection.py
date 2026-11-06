"""Explicit bank browsing stays separate from daily-plan materialization."""
import json
import pytest
from uuid import UUID
from sqlalchemy import select
from backend.models.chat import ChatMessage
from backend.models.learning import KnowledgePoint, QuestionVersion
from tests.integration.test_complex_intent_current import (
    session_factory, clean_database, clean_tasks, extra_lhopital_questions,
    qa_session, ask, protected_rows,
)


@pytest.mark.parametrize('name,message', [
    ('洛必达法则', '先选一道洛必达法则题，让我看看。'),
    ('隔离等比级数', '先选一道隔离等比级数题，让我看看。'),
    ('洛必达法则', '先选一道洛必达法则题让我看看，不要加入。'),
])
def test_select_one_for_inspection_never_creates_a_task_or_paper(session_factory, extra_lhopital_questions, name, message):
    with session_factory.begin() as db:
        db.get(KnowledgePoint, extra_lhopital_questions).name = name
    sid = qa_session(session_factory)
    before = protected_rows(session_factory)
    frames = ask(session_factory, sid, message)
    route = next(data for event, data in frames if event == 'route')
    assert route['capability'] == 'data_query' and route['intent'] == 'find'
    assert not any(event in {'planner', 'practice_request', 'personal_generation'} for event, _ in frames)
    assert protected_rows(session_factory) == before
    assert any(event == 'done' for event, _ in frames)
    with session_factory() as db:
        reply = db.scalar(select(ChatMessage).where(ChatMessage.session_id == sid,
            ChatMessage.role == 'assistant').order_by(ChatMessage.seq.desc()))
        evidence = reply.metadata_['read_only_data_query']
        assert evidence['query_type'] == 'find' and evidence['writes'] is False
        refs = evidence['preview_questions']
        assert len(refs) == 1
        version = db.get(QuestionVersion, UUID(refs[0]['question_version']))
        assert str(version.question_id) == refs[0]['question_id']
        assert version.kp_id == extra_lhopital_questions
        assert version.stem in next(data['answer'] for event, data in frames if event == 'done')
