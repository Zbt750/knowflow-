"""Thirty-day deterministic scheduler simulation; not a real student outcome trial."""
import json,os
from pathlib import Path
from datetime import datetime,timedelta,timezone
from backend.services.adaptive_scheduler import Observation,Candidate,replay,allocate


def test_thirty_days_across_ability_absence_budget_and_inventory_profiles():
    start=datetime(2026,1,1,8,tzinfo=timezone.utc)
    pool=[Candidate(f'q{k}-{i}','v1',f'kp{k}',5) for k in range(3) for i in range(12)]
    evidence={};final={}
    for profile in ['high','mixed','low']:
        events=[];days=[]
        for day in range(30):
            now=start+timedelta(days=day)
            projection=replay(events,now)
            if 10<=day<=14:
                days.append({'day':day,'absent':True,'attempts':0});continue
            budget=5 if 20<=day<=23 else 30
            candidates=[] if day==29 else pool[:2] if day==25 else pool
            plan=allocate(candidates,projection,now,budget)
            assert 0<=plan['minutes']<=budget
            assert len({c.question_id for c,_ in plan['items']})==len(plan['items'])
            assert all(c in candidates for c,_ in plan['items'])
            if day==15:assert plan['due_total']>0
            if day==29:assert plan['items']==[] and plan['minutes']==0
            for index,(candidate,kind) in enumerate(plan['items']):
                outcome='right' if profile=='high' or (profile=='mixed' and (day+index)%3) else 'wrong'
                events.append(Observation(f'{profile}-{day}-{index}',candidate.question_id,candidate.version_id,candidate.kp_id,now+timedelta(seconds=index),outcome))
            days.append({'day':day,'budget_minutes':budget,'available_candidates':len(candidates),'planned_minutes':plan['minutes'],'planned_count':len(plan['items']),'review_count':sum(kind=='review' for _,kind in plan['items']),'due_remaining':plan['due_remaining'],'review_debt_minutes':plan['review_debt_minutes']})
        projected=replay(events,start+timedelta(days=30))
        final[profile]=sum(skill.probability for skill in projected.skills.values())/len(projected.skills)
        assert all(0<=skill.probability<=1 for skill in projected.skills.values())
        evidence[profile]={'days':days,'final_average_bkt':final[profile],'fsrs_cards':len(projected.cards)}
    assert final['high']>final['mixed']>final['low']
    output=os.environ.get('PHASE45I_CLOSE_OUTPUT')
    if output:
        (Path(output)/'thirty-day-deterministic.json').write_text(json.dumps({'status':'PASS','evidence_kind':'DETERMINISTIC_SYNTHETIC_SIMULATION','real_student_efficacy':False,'profiles':evidence},indent=2),encoding='utf-8')
