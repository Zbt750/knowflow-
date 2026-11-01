"""Synthetic real-PG 18 -> 19 acceptance; no UI or real-exam claims."""
import json
import os
from pathlib import Path
from uuid import UUID
from sqlalchemy import select, func
from tests.integration.test_home_recommendation import (
    home, client, clock, session_factory, clean_database, post, ROOT,
    Question, KnowledgePoint, PracticeItem, DailyPlan, mark_isolated_question_trusted,
    freeze_graduation_question_set,
)


def test_eighteen_append_one_preserves_ids_versions_order_and_formal_readback(client, home, session_factory):
    with session_factory.begin() as db:
        for q in db.scalars(select(Question).where(Question.kp_id == UUID(home['linear']))):
            q.is_active = False
        selected = []
        for node_index in range(6):
            node = KnowledgePoint(code=f'synthetic.eighteen.{node_index}',
                name=f'合成推荐节点{node_index}（SYNTHETIC）', subject='考研数学',
                is_assessable=True, is_active=True)
            db.add(node); db.flush(); selected.append(str(node.id))
            ids = []
            for index in range(3):
                value = node_index + 2
                prompts = [f'SYNTHETIC: Calculate the derivative of f(x)={value}*x*x at x=1.',
                           f'SYNTHETIC: Evaluate the determinant of the diagonal matrix diag({value},1).',
                           f'SYNTHETIC: Solve the equation x+{value}={2*value} for x.']
                answer = 2*value if index == 0 else value
                q = Question(kp_id=node.id, question_type='single_choice',
                    stem=prompts[index],
                    options={'A':str(answer),'B':str(answer+1)}, correct_answer='A', explanation=str(answer),
                    estimated_minutes=5, grading_mode='auto',
                    grading_config={'verified':True,'method':'single_choice'}, is_active=True)
                mark_isolated_question_trusted(q, db=db)
                ids.append(q.id)
            db.flush()
            freeze_graduation_question_set(db, kp_id=node.id, question_ids=ids,
                reason='SYNTHETIC controlled real-PG eighteen acceptance')
    initial = post(client, home, action='default', selected_kp_ids=selected, budget_minutes=90)
    prepared_initial_count = len(initial['draft']['questions'])
    # Prepare the requested 18-question BASE through ordinary append APIs.
    # The canonical selector may initially include fewer than all fixture questions.
    for node_index, node_id in enumerate(selected):
        assigned = sum(q['kp_id'] == node_id for q in initial['draft']['questions'])
        missing = 3-assigned
        if missing > 0:
            initial = post(client, home, f'帮我加入{missing}道合成推荐节点{node_index}（SYNTHETIC）的题目', expected_version=initial['draft_version'])
            if initial['context'].get('workload_pending'):
                initial = post(client, home, action='accept_workload', target_task_id=initial['task_id'], expected_version=initial['draft_version'])
    original = initial['draft']['questions']
    assert len(original) == 18
    adjusted = post(client, home, '帮我加入一道洛必达法则的题目', expected_version=initial['draft_version'])
    candidate = adjusted.get('workload_candidate') or adjusted
    draft = candidate['draft']
    assert len(draft['questions']) == 19
    assert draft['questions'][:18] == original
    assert draft['questions'][-1]['kp_id'] == home['lh']
    assert len({q['question_id'] for q in draft['questions']}) == 19
    assert draft['total_minutes'] == sum(q['minutes'] for q in draft['questions'])
    if candidate['context'].get('workload_pending'):
        accepted = post(client, home, action='accept_workload', target_task_id=candidate['task_id'], expected_version=candidate['draft_version'])
        assert accepted['draft'] == draft
        candidate = accepted
    recovered = client.get(ROOT, params={'session_id':home['session_id']})
    assert recovered.status_code == 200 and recovered.json()['draft'] == draft
    body = {'session_id':home['session_id'], 'draft_version':candidate['draft_version']}
    confirmed = client.post(f"{ROOT}/{candidate['task_id']}/confirm", json=body)
    assert confirmed.status_code == 200, confirmed.text
    replay = client.post(f"{ROOT}/{candidate['task_id']}/confirm", json=body)
    assert replay.status_code == 200 and replay.json()['receipt'] == confirmed.json()['receipt']
    formal = client.get('/api/plans/today')
    assert formal.status_code == 200
    with session_factory() as db:
        items = list(db.scalars(select(PracticeItem).order_by(PracticeItem.ordinal)))
        actual = [(str(i.question_id), str(i.question_version_id)) for i in items]
        assert actual == [(q['question_id'], q['question_version_id']) for q in draft['questions']]
        assert db.scalar(select(func.count()).select_from(DailyPlan)) == 1
        for ref in draft['questions']:
            assert str(db.get(Question, UUID(ref['question_id'])).current_version_id) == ref['question_version_id']
    if os.environ.get('PHASE45I_CLOSE_OUTPUT'):
        evidence = dict(prepared_initial_count=prepared_initial_count, base_preparation='ordinary append APIs; not initial recommendation count', initial=original, appended=draft['questions'][18:], final=draft,
            recovered=recovered.json(), confirmed=confirmed.json(), replay=replay.json(),
            formal_api=formal.json(), database_items=actual)
        (Path(os.environ['PHASE45I_CLOSE_OUTPUT'])/'eighteen-append-evidence.json').write_text(
            json.dumps(evidence, ensure_ascii=False, indent=2), encoding='utf-8')
