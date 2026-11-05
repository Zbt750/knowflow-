"""Explicit isolated UI fixture. Fixed model protocol is NOT DeepSeek quality proof."""
import json
import os
from pathlib import Path
from datetime import datetime,timezone
from uuid import UUID,uuid4
import httpx
from sqlalchemy import select,func
from backend.errors import AppError

NOW=datetime(2026,10,18,16,0,2,tzinfo=timezone.utc)
def configure(app):
    from backend.db import create_db_engine,create_session_factory
    from scripts.prepare_e2e_learning import validate_test_target
    from backend.models.learning import KnowledgePoint,Question,DailyPlan,PracticeItem,KpState
    from backend.services.personal_question_service import run_generation,append_personal
    from backend.schemas.personal_questions import PersonalGenerationRequest,GenerationTarget
    from tests.integration.generation_journey_backend import NODE_CODE,SeriesProvider
    root=Path(os.environ['ZERO_PAID_UX_OUT']);root.mkdir(parents=True,exist_ok=True)
    requests=[];network=[]
    def save(n,v):(root/n).write_text(json.dumps(v,ensure_ascii=False,indent=2,default=str),encoding='utf-8')
    # Deny real model transports regardless of credentials, classifiers or retries.
    sync,async_send=httpx.Client.send,httpx.AsyncClient.send
    def check(request):
        if request.url.host not in {'127.0.0.1','localhost','testserver'}:
            network.append({'host':request.url.host,'blocked':True});save('blocked-network.json',network)
            raise RuntimeError('zero_paid_network_denied')
    def send(client,request,*a,**kw):check(request);return sync(client,request,*a,**kw)
    async def asend(client,request,*a,**kw):check(request);return await async_send(client,request,*a,**kw)
    httpx.Client.send,httpx.AsyncClient.send=send,asend
    save('blocked-network.json',network)
    factory=create_session_factory(create_db_engine(validate_test_target(os.environ['TEST_DATABASE_URL'],os.environ['KAOYAN_OWNED_TEST_PORT'])))
    with factory() as db:node=db.scalar(select(KnowledgePoint).where(KnowledgePoint.code==NODE_CODE));kp=node.id
    class Source:
        simulation=True;model='fixed-independent-math-source'
        def complete(self,messages,*,attempt=1):
            return json.dumps({'stem':r'隔离原题：当 $|x|<1$ 时，求 $\sum_{n=1}^{\infty}nx^n$ 的和。',
                'question_type':'calculation','options':None,'correct_answer':r'$S(x)=x/(1-x)^2$',
                'final_value':'x/(1-x)^2','explanation':r'几何级数在开区间逐项求导后乘以x，得到 $S(x)=x/(1-x)^2$。','steps':[]},ensure_ascii=False),None
    result=run_generation(factory,PersonalGenerationRequest(request_key=uuid4(),generation_mode='ai_generated',surface='study',targets=[GenerationTarget(kp_id=kp,count=1,question_type='calculation',difficulty='basic')]),Source(),now=NOW)
    assert len(result['question_ids'])==1,result
    source_id=UUID(result['question_ids'][0]);added=append_personal(factory,question_ids=[source_id],now=NOW)
    with factory.begin() as db:
        source=db.get(Question,source_id)
        bad=Question(kp_id=kp,stem='隔离未审核题，不可作为毕业证据',correct_answer='1',explanation='仅隔离数据',question_type='calculation',content_trust='unreviewed')
        db.add(bad);db.flush()
        approved=db.scalar(select(Question).where(Question.answer_verification_event_id.is_not(None),Question.question_type=='single_choice'))
        assert approved is not None,'existing legitimate E2E review pipeline must provide an approved question'
        from backend.mastery.storage import policy_for_node
        # 在首次学习动作前通过已有业务服务绑定当前冻结题集；不伪造毕业。
        policy_for_node(db,approved.kp_id,bind_if_unset=True,now=NOW)
        plan=db.scalar(select(DailyPlan).where(DailyPlan.study_date=='2026-10-19'))
        item=PracticeItem(plan_id=plan.id,question_id=approved.id,question_version_id=approved.current_version_id,kp_id=approved.kp_id,ordinal=2)
        db.add(item);db.flush()
        from backend.services.answer_submission_service import submit_answer
        options=approved.options
        keys=list(options) if isinstance(options,dict) else ['A','B','C','D']
        wrong=next(k for k in keys if k!=approved.correct_answer.strip())
        receipt=submit_answer(db,item_id=item.id,selected_option=wrong,raw_answer=None,confidence='high',idempotency_key='zero-fixture-wrong',now=NOW)
        assert receipt.result=='wrong'
        save('fixture.json',{'source_question_id':source.id,'source_version_id':source.current_version_id,'node_id':kp,
            'source_item_id':added['numbers'][0]['item_id'],'approved_question_id':approved.id,
            'unreviewed_question_id':bad.id,'wrong_item_id':item.id,'wrong_result':receipt.result,'plan_id':plan.id})
    class Generator(SeriesProvider):
        def complete(self,messages,*,attempt=1):
            request=json.loads(messages[-1]['content']);requests.append(request);save('provider-requests.json',requests)
            if '错误样本' in request.get('reference',{}).get('statement',''):
                from pathlib import Path
                raw=json.loads(Path('tests/unit/fixtures/deepseek_series_conflict_20261019.json').read_text(encoding='utf-8'))
                return json.dumps(raw.get('response',raw),ensure_ascii=False),None
            return super().complete(messages,attempt=attempt)
    app.state.personal_generation_provider=Generator()
    from scripts.e2e_backend import OfflineProvider
    class Model(OfflineProvider):
        failed=set()
        def complete(self,messages,*,attempt=1):
            p='## 通用知识参考\n\n以下为模型通用知识回答，本轮未检索系统资料。\n\n'
            return p+('先独立思考，再核对适用条件。\n\n'*30)+r'\[\sum_{n=1}^{\infty}nx^n=\frac{x}{(1-x)^2},\quad |x|<1\]',None
        def tool_turn(self,messages,tools,*,timeout):
            user=json.loads(messages[1]['content']);goal=user['goal']
            tool_messages=[m for m in messages if m.get('role')=='tool']
            # Finalization deliberately receives a fresh compact evidence
            # bundle and no tool definitions; its messages therefore contain
            # no role=tool entries. Detect the final stage from the protocol,
            # not from the earlier conversational transcript.
            if not tools:
                fault=next((s for s in ['网络中断','超时','截断'] if s in goal),None)
                if fault and goal not in self.failed:
                    self.failed.add(goal)
                    if fault=='截断':raise AppError('answer_truncated',retryable=False)
                    try:raise (httpx.RemoteProtocolError('fixed offline') if fault=='网络中断' else httpx.ReadTimeout('fixed offline'))
                    except Exception as exc:raise AppError('generation_failed',retryable=True) from exc
                return {'message':{'content':json.dumps({'message':'已读取当前学习记录和实际库存。建议先复习4分钟，再独立练习10分钟，最后订正6分钟，总计20分钟。这是建议，尚未创建或加入计划。','needs_clarification':False},ensure_ascii=False)}}
            if not tool_messages:
                return {'message':{'tool_calls':[{'id':'state','function':{'name':'get_learning_state','arguments':json.dumps({'kp_ids':[str(kp)]})}},
                    {'id':'stock','function':{'name':'get_question_availability','arguments':'{}'}}]}}
            return {'message':{'content':json.dumps({'message':'已读取当前学习记录和实际库存。建议先复习4分钟，再独立练习10分钟，最后订正6分钟，总计20分钟。这是建议，尚未创建或加入计划。','needs_clarification':True},ensure_ascii=False)}}
    from backend.chat import service
    service.Provider=Model
    @app.get('/api/__zero/evidence')
    def evidence():
        from backend.models.learning import QuestionVersion,QuestionAttempt,LearningEvent
        from backend.models.learning_task import LearningTask
        from backend.models.chat import ChatSession
        with factory() as db:
            tables=[Question,QuestionVersion,PracticeItem,QuestionAttempt,LearningEvent,DailyPlan,LearningTask,ChatSession]
            def rows(model):
                return [{c.name:getattr(row,c.name) for c in model.__table__.columns} for row in db.scalars(select(model))]
            data={m.__tablename__:rows(m) for m in tables}
            data['fixed_provider_requests']=requests;data['real_model_http_requests']=0;data['blocked_network']=network
            return data
