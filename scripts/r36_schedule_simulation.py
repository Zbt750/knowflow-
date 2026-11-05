"""Deterministic synthetic learner trajectories; no database or user-effect claim."""
from collections import Counter
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import random
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from backend.services.adaptive_scheduler import Candidate, Observation, replay, allocate


def simulate(probability, seed):
    rng=random.Random(seed);start=datetime(2026,1,1,2,tzinfo=timezone.utc)
    candidates=[Candidate(f'k{k}-q{q}','v1',f'k{k}',5) for k in range(8) for q in range(12)]
    observations=[];days=[];previous=set();wrong=set()
    for day in range(30):
        now=start+timedelta(days=day)
        projection=replay(observations,now)
        plan=allocate(candidates,projection,now,60)
        ids=[c.question_id for c,_ in plan['items']]
        assert len(ids)==len(set(ids)) and plan['minutes']<=60
        counts=Counter(kind for _,kind in plan['items']);topics=Counter(c.kp_id for c,_ in plan['items'])
        correct_reviews=0;review_attempts=0;skips=0;wrong_revisited=len(wrong.intersection(ids))
        for index,(candidate,kind) in enumerate(plan['items']):
            result='skipped' if rng.random()<.04 else 'right' if rng.random()<probability else 'wrong'
            skips+=result=='skipped'
            if kind=='review' and result!='skipped':
                review_attempts+=1;correct_reviews+=result=='right'
            if result=='wrong':wrong.add(candidate.question_id)
            elif result=='right':wrong.discard(candidate.question_id)
            observations.append(Observation(f'd{day}-i{index}',candidate.question_id,candidate.version_id,
                candidate.kp_id,now+timedelta(minutes=index*5),result,reliable=result!='skipped'))
        days.append({'day':day+1,'budget_minutes':60,'planned_minutes':plan['minutes'],
            'budget_delta_minutes':plan['minutes']-60,'new_count':counts['new'],'review_count':counts['review'],
            'due_count':plan['due_total'],'due_remaining':plan['due_remaining'],
            'wrong_revisited_count':wrong_revisited,'previous_day_overlap_count':len(previous.intersection(ids)),
            'same_day_duplicate_count':len(ids)-len(set(ids)),'skip_count':skips,
            'review_accuracy':correct_reviews/review_attempts if review_attempts else None,'topics':dict(topics)})
        previous=set(ids)
    return {'configured_correct_probability':probability,'seed':seed,'days':days}


if __name__=='__main__':
    output=Path(sys.argv[1]);output.parent.mkdir(parents=True,exist_ok=True)
    result={'evidence_kind':'DETERMINISTIC_SYNTHETIC_SIMULATION','database_used':False,
        'real_learning_effect_validated':False,'status':'PASS',
        'scope':'30-day synthetic allocation and replay invariants only',
        'profiles':{name:simulate(p,3600+i) for i,(name,p) in enumerate([('low',.45),('medium',.7),('high',.9)])}}
    output.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print('3 synthetic profiles x 30 days; allocation invariants passed; no database')
