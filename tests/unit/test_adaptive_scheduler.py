from datetime import datetime, timedelta, timezone
from backend.services.adaptive_scheduler import Observation, Candidate, replay, allocate

NOW = datetime(2026,11,1,8,tzinfo=timezone.utc)


def obs(i, result='right', at=NOW, q=None, **kwargs):
    return Observation(str(i),q or str(i),'v1','lhopital',at,result,**kwargs)


def test_three_wrong_cards_due_but_other_topic_gets_new_questions():
    events=[obs(i,'wrong' if i<3 else 'right') for i in range(5)]
    p=replay(events,NOW+timedelta(days=1))
    assert len(p.cards)==5
    assert all(p.cards[(str(i),'v1')].due<NOW+timedelta(days=1) for i in range(3))
    candidates=[Candidate(str(i),'v1','lhopital',5) for i in range(10)]
    candidates += [Candidate('implicit'+str(i),'v1','implicit',5) for i in range(10)]
    plan=allocate(candidates,p,NOW+timedelta(days=1),30)
    assert {c.question_id for c,k in plan['items'] if k=='review'} >= {'0','1','2'}
    assert any(c.kp_id=='implicit' and k=='new' for c,k in plan['items'])
    assert plan['minutes']<=30


def test_duplicate_receipt_and_assisted_unknown_are_not_mastery():
    e=obs(1)
    p=replay([e,e,obs(2,assisted=True),obs(3,reliable=False),obs(4,'unknown')],NOW)
    assert len(p.cards)==1
    assert p.skills['lhopital'].right==1
    assert p.skills['lhopital'].unknown==3
    assert p.skills['lhopital'].stage=='learning'


def test_versions_variants_and_same_day_answer_memory_are_independent():
    p=replay([obs(1,q='same'),obs(2,q='same'),
        Observation('3','same','v2','lhopital',NOW,'right')],NOW)
    assert len(p.cards)==2
    assert p.skills['lhopital'].right==1


def test_long_term_correct_answers_extend_interval_without_graduation():
    events=[]
    t=NOW
    intervals=[]
    for i in range(10):
        events.append(obs(i,at=t,q='same'))
        p=replay(events,t)
        due=p.cards[('same','v1')].due
        intervals.append((due-t).total_seconds())
        t=due
    assert intervals[-1]>intervals[0]
    assert p.skills['lhopital'].stage!='stable'  # one memorized question is insufficient


def test_unknown_does_not_mean_skip_and_errors_not_inferred():
    p=replay([obs(1,'unknown'),obs(2,'skipped'),obs(3,'wrong',error_kind='calculation')],NOW)
    s=p.skills['lhopital']
    assert (s.unknown,s.skipped,s.wrong)==(1,1,1)
    assert p.errors=={'calculation':1}


def test_error_categories_are_attributed_only_from_explicit_self_report():
    p=replay([obs(1,'wrong',error_kind='concept'),obs(2,'wrong')],NOW)
    assert p.errors=={'concept':1,'unclassified':1}


def test_self_assessed_partial_is_observation_not_trusted_memory_or_bkt():
    event=Observation('self','q','v1','kp',NOW,'unknown',reliable=False,rating='hard')
    p=replay([event],NOW)
    assert ('q','v1') not in p.cards
    assert p.skills['kp'].right==p.skills['kp'].wrong==0
    assert p.skills['kp'].unknown==1


def test_due_review_overflow_is_explicit_not_silently_discarded():
    p=replay([obs(i,'wrong') for i in range(5)],NOW+timedelta(days=1))
    plan=allocate([Candidate(str(i),'v1','lhopital',5) for i in range(5)],p,NOW+timedelta(days=1),10)
    assert plan['due_remaining']==3
    assert len(plan['items'])==2


def test_review_debt_keeps_a_dynamic_fresh_coverage_opportunity():
    at=NOW+timedelta(days=4)
    p=replay([obs(i,'wrong') for i in range(5)],at)
    pool=[Candidate(str(i),'v1','lhopital',5) for i in range(5)]
    pool.append(Candidate('new-topic','v1','implicit',5))
    result=allocate(pool,p,at,10)
    assert len(result['items'])==2
    assert [kind for _,kind in result['items']]==['review','new']
    assert result['new_coverage_reservation_minutes']==5
    assert result['review_debt_minutes']==20


def test_future_attempt_does_not_leak_into_past_plan():
    assert not replay([obs(1,at=NOW+timedelta(days=1))],NOW).cards


def test_local_database_timezone_is_normalized_for_fsrs():
    local = NOW.astimezone(timezone(timedelta(hours=8)))
    utc = replay([obs(1,at=NOW)],NOW)
    shanghai = replay([obs(1,at=local)],local)
    assert utc.cards[('1','v1')].to_dict()==shanghai.cards[('1','v1')].to_dict()


def test_cooldown_is_not_permanent_exclusion():
    p=replay([obs(1)],NOW+timedelta(days=3))
    plan=allocate([Candidate('new','v1','lhopital',5)],p,NOW+timedelta(days=3),10)
    assert plan['items'][0][0].question_id=='new'


def test_small_error_does_not_collapse_bkt_and_one_success_not_mastery():
    events=[obs(i,at=NOW+timedelta(days=i)) for i in range(12)]
    before=replay(events,NOW+timedelta(days=12)).skills['lhopital'].probability
    after=replay(events+[obs(15,'wrong',at=NOW+timedelta(days=12))],NOW+timedelta(days=12)).skills['lhopital']
    assert 0<before-after.probability<.2
    assert replay([obs(1)],NOW).skills['lhopital'].stage=='learning'


def test_recent_unresolved_weakness_remains_ahead_of_unseen_topics():
    from backend.services.planning_service import GoalCandidate, select_daily_goals
    from backend.mastery.enums import MasteryState
    for grade in ('not_mastered', 'partial'):
        weak = GoalCandidate(kp_id='weak', state=MasteryState.UNSEEN,
            next_review_at=None, last_practiced_at=NOW,
            last_self_grade=grade, adaptive_cooldown=True)
        unseen = GoalCandidate(kp_id='unseen', state=MasteryState.UNSEEN,
            next_review_at=None, last_practiced_at=None)
        assert select_daily_goals([unseen, weak], NOW)[0].kp_id == 'weak'
