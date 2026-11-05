"""Actual HTTP application with frozen responses, available only in owned tests."""
import os
from datetime import datetime,timezone
from zoneinfo import ZoneInfo
from sqlalchemy import select,func,text


def create_app():
    from scripts.phase45i_offline_guard import install,BLOCKED
    install()
    from sqlalchemy.engine import make_url
    from backend.config import get_settings
    url=make_url(os.environ.get('TEST_DATABASE_URL',''))
    if os.environ.get('PHASE45I_CLOSE_OFFLINE')!='1' or os.environ.get('APP_ENV')!='test' or url.port!=59227 or not url.database.endswith('_test'):
        raise RuntimeError('Owned isolated browser environment required')
    from scripts.e2e_backend import create_e2e_app
    from tests.integration.test_phase45i_agent_close import FrozenProvider
    from scripts.replay_phase45i_agent_close import frozen_rows
    from backend.db import create_db_engine,create_session_factory
    from backend.models.learning import (KnowledgePoint,KpState,Question,QuestionVersion,DailyPlan,
        PracticeItem,QuestionAttempt,LearningEvent)
    from backend.models.personal_generation import PersonalGenerationBatch
    from tests.integration.test_learning_loop import mark_isolated_question_trusted
    import backend.app as app_module
    app_module._try_build_retrieval_stack=lambda app,settings:False
    app=create_e2e_app();calls,_=frozen_rows()
    provider=FrozenProvider([calls[i-1] for i in (1,1,2,18,1)])
    app.state.personal_generation_provider=provider
    engine=create_db_engine(str(url));factory=create_session_factory(engine)
    try:
        with factory.begin() as db:
            if db.scalar(select(func.count()).select_from(KnowledgePoint))!=0:raise RuntimeError('Fresh browser database required')
            node=KnowledgePoint(code='math.exam.de439863790e',name='导数与微分的计算',subject='考研数学',
                is_active=True,is_assessable=True,is_reference_only=False)
            db.add(node);db.flush();db.add(KpState(kp_id=node.id))
            q=Question(kp_id=node.id,question_type='single_choice',stem="TEST_FIXTURE 起始练习：f(x)=x²，求f'(1)。",
                options={'A':'2','B':'3','C':'4','D':'5'},correct_answer='A',explanation='TEST_FIXTURE: 导数为2x，代入1得2。',
                grading_config={'verified':True,'method':'single_choice'})
            db.add(q);db.flush();mark_isolated_question_trusted(q,db=db)
            plan=DailyPlan(study_date=datetime.now(timezone.utc).astimezone(ZoneInfo('Asia/Shanghai')).date().isoformat(),status='active')
            db.add(plan);db.flush();db.add(PracticeItem(plan_id=plan.id,kp_id=node.id,question_id=q.id,ordinal=1))
    finally:engine.dispose()

    @app.get('/_phase45i/stats',include_in_schema=False)
    def test_stats():
        with app.state.session_factory() as db:
            qs=list(db.scalars(select(Question)));attempts=list(db.scalars(select(QuestionAttempt)));state=db.scalar(select(KpState))
            personal=[q for q in qs if q.bank_scope=='personal']
            personal_ids=[q.id for q in personal]
            personal_versions=(list(db.scalars(select(QuestionVersion).where(
                QuestionVersion.question_id.in_(personal_ids)))) if personal_ids else [])
            versions={version.id:version for version in personal_versions}
            personal_items=list(db.scalars(select(PracticeItem).where(PracticeItem.question_id.in_(personal_ids)))) if personal_ids else []
            personal_attempts=list(db.scalars(select(QuestionAttempt).where(QuestionAttempt.question_id.in_(personal_ids)))) if personal_ids else []
            personal_events=list(db.scalars(select(LearningEvent).where(LearningEvent.question_version_id.in_(list(versions))))) if versions else []
            from backend.services.question_eligibility import question_eligibility
            return {'paid_calls':0,'blocked_network_attempts':len(BLOCKED),'frozen_provider_calls':provider.calls,'personal_count':sum(q.bank_scope=='personal' for q in qs),
                'public_count':sum(q.bank_scope=='public' for q in qs),
                'practice_items':db.scalar(select(func.count()).select_from(PracticeItem)),
                'attempt_count':len(attempts),'learning_event_count':db.scalar(select(func.count()).select_from(LearningEvent)),
                'personal_questions':[{'question_id':str(q.id),'kp_id':str(q.kp_id),'current_version_id':str(q.current_version_id) if q.current_version_id else None,
                    'version_number':versions[q.current_version_id].version_number if q.current_version_id in versions else None,
                    'content_hash':versions[q.current_version_id].content_hash if q.current_version_id in versions else None,
                    'version_stem':versions[q.current_version_id].stem if q.current_version_id in versions else None,
                    'evidence_capability':question_eligibility(q,db.get(KnowledgePoint,q.kp_id)).evidence_capability}
                    for q in personal],
                'personal_question_versions':[{'question_id':str(v.question_id),'question_version_id':str(v.id),
                    'version_number':v.version_number,'content_hash':v.content_hash}
                    for v in personal_versions],
                'personal_practice_bindings':[{'practice_item_id':str(i.id),'question_id':str(i.question_id),
                    'question_version_id':str(i.question_version_id),'kp_id':str(i.kp_id)} for i in personal_items],
                'personal_attempt_bindings':[{'attempt_id':str(a.id),'question_id':str(a.question_id),
                    'question_version_id':str(a.question_version_id),'objective_result':a.objective_result}
                    for a in personal_attempts],
                'personal_learning_event_bindings':[{'event_id':str(e.id),'question_version_id':str(e.question_version_id),
                    'event_type':e.event_type,'evidence_level':e.evidence_level} for e in personal_events],
                'state':state.state,'mastered_at':state.mastered_at,'strict_evidence_count':len(state.evidence_window or []),
                'reserved_calls':db.scalar(select(func.coalesce(func.sum(PersonalGenerationBatch.reserved_calls),0))),
                'database':db.scalar(text('SELECT current_database()'))}
    return app
