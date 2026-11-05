"""Only owned test schemas; no real model or original development DB."""
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from copy import deepcopy
from sqlalchemy import select,func
from backend.models.learning import Question,QuestionSourceAttestation
from backend.services.personal_question_service import run_generation
from backend.services.question_pack import import_pack,QuestionPack
from tests.integration.test_personal_question_bank import bank,body,NOW
from tests.integration.test_question_pack_import import session_factory,clean_database,pack_data
import json

class Frozen:
    simulation=True
    def __init__(self,upper=2):self.upper=upper
    def complete(self,messages,*,attempt=1):
        kind=json.loads(messages[-1]['content'])['question_type'];n=self.upper;answer=str(n*n//2)
        data={'stem':f'计算定积分：∫_0^{n} x dx = ____。','question_type':kind,
              'options':None if kind=='fill_blank' else {'A':'1','B':'2','C':'3','D':'4'},
              'correct_answer':answer if kind=='fill_blank' else 'B',
              'explanation':f'原函数为x²/2。代入上、下限，得到{n}²/2−0²/2={answer}。',
              'final_value':answer,'steps':[{'expression':f'{n*n}/2','value':answer}]}
        return json.dumps(data,ensure_ascii=False),{'prompt_tokens':10,'completion_tokens':10,'total_tokens':20}

def request(kp,kind='fill_blank'):
    return body(kp,1,surface='chat',types=[(kind,1)],generation_mode='ai_generated')

def test_cross_day_cross_batch_cross_type_and_variant(bank):
    factory,kp=bank
    first=run_generation(factory,request(kp),Frozen(),now=NOW)
    second=run_generation(factory,request(kp,'single_choice'),Frozen(),now=NOW+timedelta(days=1))
    variant=run_generation(factory,request(kp),Frozen(4),now=NOW+timedelta(days=1))
    assert len(first['question_ids'])==1,json.dumps(first,ensure_ascii=False)
    assert second['question_ids']==[] and any(x['reason']=='duplicate' for x in second['failures']),second
    assert len(variant['question_ids'])==1,variant

def test_concurrent_new_requests_save_once(bank):
    factory,kp=bank
    def run(_):return run_generation(factory,request(kp),Frozen(),now=NOW)
    with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(run,range(2)))
    assert sum(len(r['question_ids']) for r in results)==1,json.dumps(results,ensure_ascii=False)
    with factory() as db:assert db.scalar(select(func.count()).select_from(Question))==1

def test_public_cross_pack_duplicate_alias_preserves_canonical(session_factory,clean_database):
    first=pack_data();second=deepcopy(first);second['pack_id']='second-fixture'
    with session_factory() as db:
        initial=db.scalar(select(func.count()).select_from(Question))
        import_pack(db,QuestionPack.model_validate(first),apply=True)
        result=import_pack(db,QuestionPack.model_validate(second),apply=True)
        assert result['duplicates']==1,result
        assert db.scalar(select(func.count()).select_from(Question))==initial+1
        aliases=db.scalar(select(func.count()).select_from(QuestionSourceAttestation).where(QuestionSourceAttestation.mapping_type=='duplicate_import_alias'))
        assert aliases==1
        import_pack(db,QuestionPack.model_validate(second),apply=True)
        assert db.scalar(select(func.count()).select_from(QuestionSourceAttestation).where(QuestionSourceAttestation.mapping_type=='duplicate_import_alias'))==aliases
        db.rollback()

def test_concurrent_public_imports_and_dry_run(session_factory,clean_database):
    first=pack_data();second=deepcopy(first);second['pack_id']='second-concurrent-fixture'
    with session_factory() as db:
        initial=db.scalar(select(func.count()).select_from(Question))
        initial_aliases=db.scalar(select(func.count()).select_from(QuestionSourceAttestation))
        import_pack(db,QuestionPack.model_validate(first))
        assert db.scalar(select(func.count()).select_from(Question))==initial
        assert db.scalar(select(func.count()).select_from(QuestionSourceAttestation))==initial_aliases
    def run(data):
        with session_factory.begin() as db:return import_pack(db,QuestionPack.model_validate(data),apply=True)
    with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(run,[first,second]))
    assert sum(r['new'] for r in results)==1
    assert sum(r['duplicates'] for r in results)==1
    with session_factory() as db:assert db.scalar(select(func.count()).select_from(Question))==initial+1
