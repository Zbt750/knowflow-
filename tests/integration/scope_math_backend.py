"""Dedicated disposable PostgreSQL + production routes + offline protocol provider."""
from datetime import datetime,timezone
import json,os,sys
from pathlib import Path
from uuid import UUID
from sqlalchemy import select,text,create_engine
from sqlalchemy.orm import sessionmaker
from backend.models.learning import KnowledgePoint

NOW=datetime(2026,10,20,2,tzinfo=timezone.utc)
ROOT=Path(__file__).resolve().parents[2]

def save(name,data):
    out=Path(os.environ['QUERY_FOLLOWUP_OUTPUT']);out.mkdir(parents=True,exist_ok=True)
    (out/name).write_text(json.dumps(data,ensure_ascii=False,indent=2,default=str),encoding='utf-8')

class Model:
    simulation=True;model='fixed-scope-math-no-network'
    def __init__(self,**kwargs):self.calls=0
    def classify_retrieval_intent(self,question):return None
    def complete(self,messages,*,attempt=1):
        request=json.loads(messages[-1]['content'])
        reference=(request.get('reference') or {}).get('statement','')
        if request.get('node'):
            if '错误样本' in reference:
                ledger=json.loads((ROOT/'storage/quality-audits/naiwa-real-retest-20261020-budget7/provider-ledger.json').read_text(encoding='utf-8'))
                raw=json.loads(next(r for r in ledger['requests'] if r['case_id']=='GENERATE')['response_text'])['choices'][0]['message']['content']
                return raw,None
            return json.dumps(dict(stem=r'求极限 $\lim_{x\to0}\frac{e^x-1-x-\frac{x^2}{2}}{x-\ln(1+x)}$。',
                question_type='single_choice',options=dict(A='0',B='1',C='2',D='1/2'),correct_answer='A',final_value='0',
                explanation=r'分子展开为 $x^3/6+O(x^4)$，分母展开为 $x^2/2+O(x^3)$，比值为 $x/3+O(x^2)$，原极限为 $0$。',steps=[],
                difficulty_assessment=dict(estimated_level='hard',relative_change='harder',reason='需要识别分子三阶与分母二阶小量并比较阶数。',mechanisms=['reasoning_steps','knowledge_depth'])),ensure_ascii=False),None
        return '固定Provider：仅验证工程链路。',None
    async def stream(self,messages,*,attempt=1):yield '固定Provider：仅验证工程链路。'
    def tool_turn(self,messages,tools,*,timeout):
        self.calls+=1
        payload=json.loads(messages[1]['content'])
        if 'evidence' in payload:
            assert not tools, 'finalization must not request additional tools'
            evidence=payload['evidence'];inventories=evidence['inventories']
            assert inventories and evidence['learning_states'] and evidence['question_candidates']
            stock=inventories[-1];count=stock['practice_eligible_count']
            names='、'.join(n['name'] for n in stock.get('eligible_nodes',[]))
            budget=payload['budget_minutes_upper_bound']
            save('fixed-finalization-'+str(len(evidence['learning_states']))+'-'+str(budget)+'.json',payload)
            return {'message':{'content':json.dumps({'message':f'固定Provider工程验收：已查询{names}的学习记录与库存，可练{count}道。建议先用{budget//3}分钟复习条件，再用{budget-budget//3}分钟练习与订正，总计{budget}分钟。仅为建议，未创建计划；不代表真实模型规划质量。','needs_clarification':False},ensure_ascii=False)}}
        handoff=payload['structured_handoff'];constraints=handoff['constraints']
        ids=constraints['resolved_scope_node_ids']
        with FACTORY() as db:
            nodes=list(db.scalars(select(KnowledgePoint).where(KnowledgePoint.id.in_([UUID(i) for i in ids]),KnowledgePoint.is_assessable.is_(True)).order_by(KnowledgePoint.code)))
        leaf=[str(n.id) for n in nodes][:8]
        tracefile=Path(os.environ['QUERY_FOLLOWUP_OUTPUT'])/'fixed-tool-prompts.json'
        trace=json.loads(tracefile.read_text(encoding='utf-8')) if tracefile.exists() else []
        trace.append({'handoff':handoff,'round':self.calls,'budget':payload['budget_minutes'],'simulation':True})
        save(tracefile.name,trace)
        def call(name,args):return {'id':name+str(self.calls),'type':'function','function':{'name':name,'arguments':json.dumps(args)}}
        if self.calls==1:
            return {'message':{'tool_calls':[call('get_question_availability',{}),call('get_learning_state',{'kp_ids':leaf})]}}
        if self.calls==2:
            return {'message':{'tool_calls':[call('find_questions',{'kp_ids':leaf})]}}
        evidence=[]
        for message in messages:
            if message.get('role')=='tool':
                try:evidence.append(json.loads(message['content']))
                except (ValueError,TypeError):pass
        inventory=next((r for r in evidence if 'practice_eligible_count' in r),{})
        count=inventory.get('practice_eligible_count','未知')
        budget=payload['budget_minutes'];names='、'.join(n.name for n in nodes)
        return {'message':{'content':json.dumps({'message':f'固定Provider工程验收：已查询{names}的学习记录和库存，可练{count}道。建议先用{budget//3}分钟复习条件，再用{budget-budget//3}分钟练习与订正，总计{budget}分钟。仅为建议，未创建计划；不代表真实模型规划质量。','needs_clarification':False},ensure_ascii=False)}}

FACTORY=None
def create_e2e_app():
    global FACTORY
    from scripts.prepare_e2e_learning import validate_test_target
    from sqlalchemy.engine import make_url
    url=validate_test_target(os.environ['TEST_DATABASE_URL'],os.environ['KAOYAN_OWNED_TEST_PORT'])
    target=make_url(url)
    assert target.database=='kaoyan_test' and target.port not in {5433,63044}
    FACTORY=sessionmaker(create_engine(url))
    with FACTORY.begin() as db:
        db.execute(text('TRUNCATE chat_sessions, knowledge_points, daily_plans CASCADE'))
    from tests.integration.query_followup_backend import prepare_fixture
    facts=prepare_fixture(FACTORY,question_specs=[
        {'stem':r'【正确原题】求 $\lim_{x\to0}\frac{e^x-1-x}{x^2}$。','options':dict(A='1/2',B='1',C='0',D='2')},
        {'stem':r'【错误样本回放原题】求 $\lim_{x\to0}\frac{e^x-1-x}{x^2}$。','options':dict(A='1/2',B='1',C='0',D='2')},
        {},{},{},{}])
    # Query fixtures deliberately contain sparse imported history. Keep that
    # history on yesterday's plan; today's UI items use real version snapshots
    # and have no fabricated submission receipt.
    from backend.models.learning import DailyPlan,PracticeItem,Question
    with FACTORY.begin() as db:
        old=db.scalar(select(DailyPlan));old.study_date='2026-10-19'
        today=DailyPlan(study_date='2026-10-20',status='active');db.add(today);db.flush()
        for ordinal,index in enumerate((0,1,4),1):
            q=db.get(Question,UUID(facts['question_ids'][index]))
            db.add(PracticeItem(plan_id=today.id,question_id=q.id,kp_id=q.kp_id,ordinal=ordinal))
    save('scope-math-fixture.json',facts)
    # All network sockets except this OWNED PostgreSQL are denied, including
    # any implicit classifier, judge or transport fallback.
    def guard(event,args):
        if event=='socket.connect' and len(args)>1:
            addr=args[1]
            if not(isinstance(addr,tuple) and addr[0] in {'127.0.0.1','::1'} and addr[1]==target.port):
                save('blocked-network.json',{'event':event,'reason':'offline_scope_math_denied'})
                raise RuntimeError('offline_scope_math_denied')
    sys.addaudithook(guard)
    save('offline-guard.json',{'real_model_requests':0,'allowed_socket':'owned PostgreSQL only',
        'owned_pg_port':target.port,'fixed_provider':True,'production_routes_only':True})
    from scripts.e2e_backend import create_e2e_app as offline
    app=offline()
    from backend.chat import service
    service.Provider=Model
    app.state.personal_generation_provider=Model()
    from backend.api.deps import get_time_provider
    app.dependency_overrides[get_time_provider]=lambda:lambda:NOW
    import backend.app as app_module
    def skip_retrieval(application,settings):
        application.state.retrieval_stack=None;application.state.retrieval_error='offline_scope_math_no_rag'
        return False
    app_module._try_build_retrieval_stack=skip_retrieval
    return app

if __name__=='__main__':
    from scripts.prepare_e2e_learning import validate_test_target
    from backend.models.learning_task import LearningTask
    from backend.models.learning import Question,QuestionVersion,PracticeItem,QuestionAttempt,LearningEvent,DailyPlan
    from backend.models.chat import ChatMessage
    factory=sessionmaker(create_engine(validate_test_target(os.environ['TEST_DATABASE_URL'],os.environ['KAOYAN_OWNED_TEST_PORT'])))
    with factory() as db:
        db.execute(text('SET TRANSACTION READ ONLY'))
        data={model.__tablename__:[{c.name:getattr(row,'metadata_' if c.name=='metadata' else c.name) for c in model.__table__.columns} for row in db.scalars(select(model))]
              for model in [LearningTask,Question,QuestionVersion,PracticeItem,QuestionAttempt,LearningEvent,DailyPlan,ChatMessage]}
        data['identity']=dict(db.execute(text('SELECT current_database() db,current_user role,current_setting(\'port\') port')).one()._mapping)
    save('database-'+sys.argv[1]+'.json',data)
    print(json.dumps(data,ensure_ascii=False,default=str))
