"""Seven actual HTTP scheduling dates backed by committed PostgreSQL learning events.

Question content and scripted responses are isolated test fixtures. This verifies
service wiring and persistence, not real learner efficacy.
"""
import json
from datetime import timedelta
from pathlib import Path
import os
from uuid import UUID

import pytest
from sqlalchemy import select

from tests.integration.test_student_uiv2_repairs import session_factory
from tests.integration.test_learning_loop import client, clock
from backend.models.learning import KnowledgePoint, Question, QuestionAttempt, LearningEvent
from backend.services.adaptive_schedule_projection import read_projection


def test_seven_daily_http_recommendation_generate_answer_and_restart_projection(
    session_factory, client, clock
):
    # The shared integration seed materializes the fixture date; use a fresh
    # synthetic week so each HTTP recommendation observes a new study date.
    clock.now+=timedelta(days=30)
    initial=client.get('/api/plans/today')
    assert initial.status_code==200,initial.text
    initial_setup=initial.json()
    assert initial_setup['status']=='setup' and initial_setup['recommendations']
    # Anchor the synthetic workload to a knowledge point actually selected by
    # the live HTTP recommender; do not assume a new UUID sorts into its top six.
    node_id=UUID(initial_setup['recommendations'][0]['kp_id'])
    with session_factory.begin() as db:
        node=db.get(KnowledgePoint,node_id)
        assert node is not None
        questions=[]
        from tests.integration.test_learning_loop import mark_isolated_question_trusted
        from backend.mastery.storage import policy_for_node
        policy=policy_for_node(db,node.id)
        type_counts=dict(policy.required_question_types or {})
        # Keep the scheduler workload capable of returning multiple days of
        # questions while also satisfying this selected node's live type quota.
        type_counts['single_choice']=max(24,type_counts.get('single_choice',0))
        ordinal=0
        for question_type,count in type_counts.items():
            for _ in range(count):
                index=ordinal;ordinal+=1
                if question_type=='single_choice':
                    options={'A':f'Correct fixture answer {index}','B':f'Wrong fixture answer {index}'}
                    answer='A';grading={'verified':True,'method':'single_choice'}
                elif question_type in {'fill_blank','calculation'}:
                    options=None;answer='1';grading={'verified':True,'method':'numeric_final'}
                else:
                    options=None;answer='synthetic response';grading={'verified':False,'practice_method':None}
                question=Question(kp_id=node.id,question_type=question_type,
                    stem=f'Synthetic seven-day scheduler item {index}: provide the fixture answer.',
                    options=options,correct_answer=answer,explanation='Synthetic isolated scheduler fixture.',
                    grading_mode='auto',grading_config=grading,
                    estimated_minutes=5,skill_tags=['synthetic-scheduler'],
                    question_provenance='trusted_practice',source_status='not_applicable')
                db.add(question);db.flush();mark_isolated_question_trusted(question,db=db)
                question.question_provenance='trusted_practice';question.source_status='not_applicable'
                questions.append(question)
        correct_by_question={q.id:q.correct_answer for q in questions}
    days=[];all_skip_ids=[];deliberate_wrong_submitted=False
    for day_index in range(7):
        recommendation_response=client.get('/api/plans/today')
        assert recommendation_response.status_code==200,recommendation_response.text
        setup=recommendation_response.json()
        assert setup['status']=='setup'
        chosen=next((r for r in setup['recommendations'] if r['kp_id']==str(node_id)),None)
        assert chosen is not None,setup['recommendations']
        before_projection=read_projection_for_test(session_factory,clock.now,node_id)
        before_review_due=sum(card.due<=clock.now for card in before_projection.cards.values())
        with session_factory() as db:
            node_attempts=list(db.scalars(select(QuestionAttempt).where(QuestionAttempt.kp_id==node_id)))
            node_questions=list(db.scalars(select(Question).where(Question.kp_id==node_id)))
            from backend.services.question_eligibility import question_eligibility
            question_status=[(str(q.id),str(q.current_version_id),
                question_eligibility(q,db.get(KnowledgePoint,node_id)).practice_eligible) for q in node_questions]
            eligible_count=sum(row[2] for row in question_status)
        generated=client.post('/api/plans/today/generate',json={
            'selected_kp_ids':[str(node_id)],'budget':'light'})
        assert generated.status_code==201,generated.text
        active=generated.json()
        items=active['items']
        assert items and len({i['question_id'] for i in items})==len(items),json.dumps({
            'active':active,'recommendation':chosen,'projection_card_count':len(before_projection.cards),
            'attempts':[(str(a.question_id),str(a.question_version_id),a.objective_result) for a in node_attempts],
            'questions':question_status,
            'eligible_count':eligible_count},ensure_ascii=False)
        estimated=sum(int(i['estimated_minutes']) for i in items)
        assert estimated<=45
        review_count=sum(
            (item['question_id'],item['question_version_id']) in before_projection.cards
            and before_projection.cards[(item['question_id'],item['question_version_id'])].due<=clock.now
            for item in items)
        outcomes=[];skip_ids=[];attempt_ids=[]
        for index,item in enumerate(items):
            if day_index==0 and index==len(items)-1:
                activity=client.post(f"/api/practice-items/{item['id']}/activity",json={
                    'kind':'skipped','idempotency_key':f'r37-seven-day-skip-{day_index}-{index}'})
                assert activity.status_code==200,activity.text
                skip_ids.append(item['id']);all_skip_ids.append(item['id']);outcomes.append('skipped');continue
            with session_factory() as db:
                question=db.get(Question,item['question_id'])
                answer=correct_by_question.get(question.id,question.correct_answer)
                options=list((question.options or {}).keys())
                wrong=next((option for option in options if option!=answer),None)
            if question.question_type=='single_choice':
                inject_wrong=day_index==0 and not deliberate_wrong_submitted and bool(wrong)
                selected=wrong if inject_wrong else answer
                deliberate_wrong_submitted=deliberate_wrong_submitted or inject_wrong
                answer_body={'selected_option':selected}
            else:
                inject_wrong=(day_index==0 and not deliberate_wrong_submitted
                    and question.question_type in {'fill_blank','calculation'})
                answer_body={'raw_answer':'2' if inject_wrong else answer}
                deliberate_wrong_submitted=deliberate_wrong_submitted or inject_wrong
            submitted=client.post(f"/api/practice-items/{item['id']}/answer-submissions",json={
                **answer_body,'confidence':'certain',
                'idempotency_key':f'r37-seven-day-answer-{day_index}-{index}'})
            assert submitted.status_code==200,submitted.text
            body=submitted.json();outcomes.append(body['result']);attempt_ids.append(body['attempt_id'])
        with session_factory() as db:
            projection=read_projection(db,clock.now+timedelta(minutes=2),[node_id])
            for attempt_id in attempt_ids:assert db.get(QuestionAttempt,attempt_id) is not None
            skip_events=list(db.scalars(select(LearningEvent).where(
                LearningEvent.event_type=='scheduler_activity',LearningEvent.kp_id==node_id)))
            persisted_skips=[e for e in skip_events if (e.payload or {}).get('kind')=='skipped'
                and (e.idempotency_key or '').startswith('activity:r37-seven-day-skip-')]
            assert len(persisted_skips)==len(all_skip_ids)
        assert projection.skills[str(node_id)].skipped==len(all_skip_ids)
        days.append({
            'day':day_index+1,'study_date':setup['study_date'],'recommendation_reason':chosen['reason'],
            'recommended_kp_id':chosen['kp_id'],'new_count':len(items)-review_count,'review_count':review_count,
            'planned_question_count':len(items),'estimated_minutes':estimated,'budget_minutes':45,
            'due_before_count':before_review_due,
            'due_after_count':sum(card.due<=clock.now+timedelta(minutes=2) for card in projection.cards.values()),
            'question_ids':[i['question_id'] for i in items],'outcomes':outcomes,
            'skip_count':len(skip_ids),'persisted_attempt_ids':attempt_ids,
            'fsrs_cards':{f'{qid}:{version}':{'due':card.due.isoformat(),'stability':card.stability,
                'difficulty':card.difficulty} for (qid,version),card in projection.cards.items()},
            'bkt':{'probability':projection.skills[str(node_id)].probability,
                'right':projection.skills[str(node_id)].right,'wrong':projection.skills[str(node_id)].wrong,
                'skipped':projection.skills[str(node_id)].skipped},
        })
        if day_index<6:clock.now+=timedelta(days=1)

    assert any('wrong' in day['outcomes'] for day in days)
    assert days[1]['recommendation_reason'] in {'due_review','objective_review'}
    assert days[0]['skip_count']==1
    output=Path(os.environ['PHASE45I_CLOSE_OUTPUT'])/'seven-day-real-http.json'
    output.write_text(json.dumps({'status':'PASS','evidence_kind':'REAL_HTTP_AND_POSTGRES',
        'synthetic_question_content':True,'scripted_outcomes':True,'real_user_efficacy_validated':False,
        'recommendation_http_each_day':True,'projection_reloaded_from_fresh_db_session':True,
        'days':days},ensure_ascii=False,indent=2),encoding='utf-8')


def read_projection_for_test(factory, now, node_id):
    with factory() as db:return read_projection(db,now,[node_id])
