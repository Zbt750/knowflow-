"""Seven simulated dates with real PostgreSQL submissions; not real learner efficacy."""
import json
import os
from pathlib import Path
from datetime import timedelta
from sqlalchemy import select
from tests.integration.test_policy_origin_semantics import session_factory, clean_database, make_origin_slice, DAY
from backend.models.learning import DailyPlan, PracticeItem, QuestionAttempt
from backend.services.adaptive_schedule_projection import read_projection
from backend.services.adaptive_scheduler import Candidate, allocate
from backend.services.answer_submission_service import submit_answer
from backend.services.practice_activity_service import record_activity


def test_seven_dates_replay_real_committed_answers_and_skip(session_factory):
    with session_factory.begin() as db:
        node,_policy,questions=make_origin_slice(db)
        node_id=node.id
        candidates=[Candidate(str(q.id),str(q.current_version_id),str(node.id),q.estimated_minutes) for q in questions]
        references={str(q.id):q.id for q in questions}
    days=[];saved_attempts=[]
    for day in range(7):
        now=DAY+timedelta(days=day)
        with session_factory() as db:projection=read_projection(db,now,[node_id])
        arrangement=allocate(candidates,projection,now,10)
        assert arrangement['minutes']<=10
        assert len({c.question_id for c,_ in arrangement['items']})==len(arrangement['items'])
        kinds=[kind for _,kind in arrangement['items']]
        with session_factory.begin() as db:
            if arrangement['items']:
                paper=DailyPlan(study_date=now.date().isoformat(),status='active');db.add(paper);db.flush()
            for index,(candidate,kind) in enumerate(arrangement['items']):
                item=PracticeItem(plan_id=paper.id,question_id=references[candidate.question_id],kp_id=node_id,ordinal=index+1)
                db.add(item);db.flush()
                if day==0 and index==0:
                    record_activity(db,item_id=item.id,kind='skipped',idempotency_key=f'r36-day{day}-skip{index}',now=now)
                else:
                    answer=submit_answer(db,item_id=item.id,raw_answer=None,selected_option='B' if day%3==0 else 'A',
                        idempotency_key=f'r36-day{day}-answer{index}',now=now)
                    saved_attempts.append(answer.attempt_id)
            db.flush()
        with session_factory() as reopened:
            recovered=read_projection(reopened,now+timedelta(hours=1),[node_id])
            for attempt_id in saved_attempts:
                assert reopened.get(QuestionAttempt,attempt_id) is not None
            assert recovered.skills[str(node_id)].skipped==1
        days.append({'day':day+1,'minutes':arrangement['minutes'],'new':kinds.count('new'),
            'review':kinds.count('review'),'due_total':arrangement['due_total'],
            'due_remaining':arrangement['due_remaining'],'persisted_attempts':len(saved_attempts)})
    output=Path(os.environ['PHASE45I_CLOSE_OUTPUT'])/'seven-day-database.json'
    output.write_text(json.dumps({'scope':'Real PostgreSQL service submissions and projection replay over seven simulated dates',
        'synthetic_content':True,'simulated_outcomes':True,'real_user_efficacy':False,
        'http_recommendation_journey':False,'days':days},indent=2),encoding='utf-8')
