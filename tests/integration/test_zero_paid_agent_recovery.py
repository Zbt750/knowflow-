import json
import httpx
import pytest
from sqlalchemy import select,func
from backend.errors import AppError
from backend.models.learning import DailyPlan,PracticeItem,Question,KnowledgePoint
from backend.models.learning_task import LearningTask
from backend.services.learning_task_service import create_task,run_task,get_task
from backend.schemas.learning_task import CreateTask
from backend.services.learning_task_tools import TaskTools
from datetime import datetime,timezone
from uuid import UUID
from tests.integration.test_learning_tasks import session_factory,clean_database,clean_tasks

@pytest.mark.parametrize('failure,expected', [('network','provider_network'),('timeout','provider_timeout'),('truncated','answer_truncated')])
@pytest.mark.parametrize('zero_inventory',[False,True])
def test_query_then_failure_preserves_evidence_and_explicit_retry_is_idempotent(session_factory,failure,expected,zero_inventory,request):
    if zero_inventory:
        def restore_inventory():
            with session_factory.begin() as db:
                for question in db.scalars(select(Question)):question.is_active=True
        request.addfinalizer(restore_inventory)
        with session_factory.begin() as db:
            # ORM版本钩子保持Question/QuestionVersion一致；不绕过DB防篡改约束。
            for question in db.scalars(select(Question)):question.is_active=False
    class Model:
        model='fixed-no-network'
        def __init__(self):self.calls=0
        def tool_turn(self,messages,tools,*,timeout):
            self.calls+=1
            if self.calls in {1,3}:
                return {'message':{'tool_calls':[{'id':f'query-{self.calls}','function':{'name':'get_question_availability','arguments':'{}'}}]}}
            if self.calls==2:
                if failure=='truncated':raise AppError('answer_truncated',retryable=False)
                try:
                    raise (httpx.RemoteProtocolError('fixed fixture') if failure=='network' else httpx.ReadTimeout('fixed fixture'))
                except Exception as exc:raise AppError('generation_failed',retryable=True) from exc
            return {'message':{'content':json.dumps({'message':'已读取当前库存；这是建议，没有创建计划。','needs_clarification':False})}}
    model=Model()
    t=create_task(session_factory,CreateTask(goal='查询题库有哪些题，只给建议不要创建计划',budget_minutes=20))
    failed=run_task(session_factory,t.task_id,model)
    assert failed.status=='failed' and failed.error_code==expected and model.calls==2, (model.calls,failed.model_dump())
    assert len(failed.trace)==1 and failed.trace[0]['status']=='completed'
    count=failed.trace[0]['result']['practice_eligible_count']
    assert (count==0 if zero_inventory else count>0)
    assert get_task(session_factory,t.task_id).trace==failed.trace
    recovered=run_task(session_factory,t.task_id,model)
    assert recovered.status=='answered' and model.calls==4
    assert recovered.metrics['attempt_history'][0]['trace']==failed.trace
    assert recovered.metrics['attempt_history'][0]['error_code']==expected
    assert run_task(session_factory,t.task_id,model).status=='answered' and model.calls==4
    with session_factory() as db:
        assert db.scalar(select(func.count()).select_from(LearningTask))==1
        assert db.scalar(select(func.count()).select_from(DailyPlan))==0
        assert db.scalar(select(func.count()).select_from(PracticeItem))==0


def _advice_only_task(factory, kp_id):
    goal="我今天只有90分钟，根据最近学习记录给数学二复习建议；未经我确认不要创建或追加今日学习。"
    task=create_task(factory,CreateTask(goal=goal,budget_minutes=90))
    with factory.begin() as db:
        row=db.get(LearningTask,task.task_id)
        row.context={**row.context,"planner_handoff":{
            "version":"planner-handoff-v1","request_type":"recommend",
            "target_knowledge_node_ids":[str(kp_id)],"requested_question_count":None,
            "constraints":{"scope_origin":"explicit_user_scope"}}}
    return task


def _tool_call(call_id,name,args):
    return {"id":call_id,"type":"function","function":{"name":name,"arguments":json.dumps(args,ensure_ascii=False)}}


def test_recommendation_finishes_after_state_inventory_and_candidate_without_writes(session_factory):
    tools,questions=__import__("tests.integration.test_learning_tasks",fromlist=["prepared_tools"]).prepared_tools(session_factory)
    assert questions
    kp_id=UUID(questions[0]["kp_id"])
    created=_advice_only_task(session_factory,kp_id)
    class Provider:
        model="fixed-no-network"
        def __init__(self):self.calls=0;self.requests=[]
        def tool_turn(self,messages,tools,*,timeout):
            self.calls+=1;self.requests.append((messages,tools))
            if self.calls==1:
                return {"message":{"tool_calls":[
                    _tool_call("state-1","get_learning_state",{"kp_ids":[str(kp_id)]}),
                    _tool_call("inventory-1","get_question_availability",{"kp_ids":[str(kp_id)]})]}}
            if self.calls==2:
                return {"message":{"tool_calls":[_tool_call("candidate-1","find_questions",{"kp_ids":[str(kp_id)]})]}}
            assert not tools, "finalization must disable tools"
            payload=json.loads(messages[-1]["content"])
            evidence=payload["evidence"]
            candidate=evidence["question_candidates"][0]
            node=candidate.get("kp_name") or "当前知识点"
            minutes=candidate.get("minutes")
            reason=(evidence["learning_states"][0].get("learning_progress") or {}).get("reason") or "本轮读取到当前节点学习状态"
            message=f"依据记录：{reason}。题库已查到具体候选；建议先独立完成{node}的练习题。"
            if type(minutes) is int:message+=f"预计{minutes}分钟；其余时间按作答表现决定是否继续复习。"
            message+="90分钟是上限，本次只提供建议，未创建或追加今日学习。"
            return {"message":{"content":json.dumps({"message":message,"needs_clarification":False},ensure_ascii=False)}}
    provider=Provider()
    with session_factory() as db:
        before_tasks=db.scalar(select(func.count()).select_from(LearningTask))
    result=run_task(session_factory,created.task_id,provider,now=datetime(2026,1,1,tzinfo=timezone.utc))
    assert result.status=="answered" and provider.calls==3, (
        f"status={result.status} error={result.error_code} calls={provider.calls} "
        f"trace={result.trace} metrics={result.metrics} message={result.message}"
    )
    assert result.metrics["intent"]=="recommend"
    assert result.metrics["executed_tool_calls"]==3
    assert result.metrics["loop_stop_reason"]=="recommendation_evidence_collected"
    assert "题库" in result.message and "未创建或追加" in result.message
    assert "90分钟" in result.message
    with session_factory() as db:
        assert db.scalar(select(func.count()).select_from(LearningTask))==before_tasks
        assert db.scalar(select(func.count()).select_from(DailyPlan))==0
        assert db.scalar(select(func.count()).select_from(PracticeItem))==0


def test_repeated_tool_loop_is_suppressed_then_returns_evidence_limited_advice(session_factory):
    tools,questions=__import__("tests.integration.test_learning_tasks",fromlist=["prepared_tools"]).prepared_tools(session_factory)
    kp_id=UUID(questions[0]["kp_id"])
    created=_advice_only_task(session_factory,kp_id)
    class RepeatingProvider:
        model="fixed-no-network"
        def __init__(self):self.calls=0
        def tool_turn(self,messages,tools,*,timeout):
            self.calls+=1
            if self.calls<=2:
                return {"message":{"tool_calls":[_tool_call(f"state-{self.calls}","get_learning_state",{"kp_ids":[str(kp_id)]})]}}
            return {"message":{"content":json.dumps({"message":"基于目前记录建议复习。","needs_clarification":False},ensure_ascii=False)}}
    provider=RepeatingProvider()
    result=run_task(session_factory,created.task_id,provider,now=datetime(2026,1,1,tzinfo=timezone.utc))
    assert result.status=="answered" and provider.calls==3
    assert result.metrics["loop_stop_reason"]=="repeated_tool_call"
    assert result.metrics["executed_tool_calls"]==1 and result.metrics["reused_tool_calls"]==1
    assert "学习状态" in result.message and "没有创建或追加" in result.message
    assert sum(item["tool"]=="get_learning_state" and item["status"]=="completed" for item in result.trace)==1
    with session_factory() as db:
        assert db.scalar(select(func.count()).select_from(DailyPlan))==0
        assert db.scalar(select(func.count()).select_from(PracticeItem))==0


def test_tool_loop_cap_exits_without_fabricating_a_plan(session_factory):
    with session_factory() as db:
        node=db.scalar(select(Question.kp_id).limit(1))
    assert node is not None
    created=_advice_only_task(session_factory,node)
    class LoopingProvider:
        model="fixed-no-network"
        def __init__(self):self.calls=0
        def tool_turn(self,messages,tools,*,timeout):
            self.calls+=1
            return {"message":{"tool_calls":[_tool_call(f"search-{self.calls}","search_knowledge",{"query":f"TEST_FIXTURE missing node {self.calls}"})]}}
    provider=LoopingProvider()
    result=run_task(session_factory,created.task_id,provider,now=datetime(2026,1,1,tzinfo=timezone.utc))
    assert result.status=="answered" and provider.calls==6
    assert result.error_code=="finalizer_requested_tools"
    assert result.metrics["executed_tool_calls"]==5
    assert "没有创建或加入今日学习" in result.message
    with session_factory() as db:
        assert db.scalar(select(func.count()).select_from(DailyPlan))==0
        assert db.scalar(select(func.count()).select_from(PracticeItem))==0


def test_recommendation_provider_failure_retains_read_evidence_without_plan_write(session_factory):
    tools,questions=__import__("tests.integration.test_learning_tasks",fromlist=["prepared_tools"]).prepared_tools(session_factory)
    kp_id=UUID(questions[0]["kp_id"])
    created=_advice_only_task(session_factory,kp_id)
    class FailingProvider:
        model="fixed-no-network"
        def __init__(self):self.calls=0
        def tool_turn(self,messages,tools,*,timeout):
            self.calls+=1
            if self.calls==1:
                return {"message":{"tool_calls":[
                    _tool_call("state-1","get_learning_state",{"kp_ids":[str(kp_id)]}),
                    _tool_call("inventory-1","get_question_availability",{"kp_ids":[str(kp_id)]})]}}
            if self.calls==2:
                return {"message":{"tool_calls":[_tool_call("candidate-1","find_questions",{"kp_ids":[str(kp_id)]})]}}
            try:
                raise httpx.RemoteProtocolError("TEST_FIXTURE disconnected")
            except Exception as exc:
                raise AppError("generation_failed",retryable=True) from exc
    provider=FailingProvider()
    result=run_task(session_factory,created.task_id,provider,now=datetime(2026,1,1,tzinfo=timezone.utc))
    assert provider.calls==3 and result.status=="answered" and result.error_code=="provider_network"
    assert "学习状态" in result.message and "题库" in result.message
    assert result.trace and any(item.get("tool")=="get_learning_state" and item.get("status")=="completed" for item in result.trace)
    with session_factory() as db:
        assert db.scalar(select(func.count()).select_from(DailyPlan))==0
        assert db.scalar(select(func.count()).select_from(PracticeItem))==0
