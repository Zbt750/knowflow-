"""F-01..04 contracts from the independent r7final UI reports; no model/network."""
from contextlib import nullcontext
from datetime import datetime, timezone
import json
from types import SimpleNamespace as NS
from uuid import UUID

import pytest
from backend.models.learning import Question, QuestionVersion, KnowledgePoint
from backend.models.learning_task import LearningTask
from backend.models.practice_request import PracticeRequest
from backend.schemas.learning_assistant import StudyContext
from backend.services.assistant_router import route_message
from backend.services import study_preview_revision as revision
from backend.services.practice_preview_reference import latest_preview
from scripts.naiwa_answer_handoff_provider import HandoffEvidenceProvider
from tests.unit.test_naiwa_answer_handoff_provider import finalization_messages

NOW=datetime(2026,10,26,4,tzinfo=timezone.utc)
ROOT,LEAF,OTHER=[UUID(int=n) for n in (101,102,103)]


def revised(monkeypatch, *, roots=True, budget=25, changed=False, today=False,
            eligible=True, missing=False, restricted=False, source_changed=False,
            resolved=False, outside=False, minutes=(4,5)):
    qids=[UUID(int=n) for n in (201,202)]
    versions=[UUID(int=n) for n in (301,302)]
    rows={qid:NS(id=qid,kp_id=OTHER if outside else LEAF,estimated_minutes=estimate,question_type='single_choice',
                 difficulty='basic',bank_scope='public') for qid,estimate in zip(qids,minutes)}
    read_nodes=[]

    class DB:
        def scalars(self,query):
            entity=query.column_descriptions[0]['entity']
            if entity is Question:return list(rows.values())[1:] if missing else list(rows.values())
            return [qids[0]] if today else []
        def get(self,entity,ident):
            if entity is QuestionVersion:return NS(question_id=qids[versions.index(ident)])
            assert entity is KnowledgePoint
            return NS(id=ident)

    class Tools:
        def __init__(self,*args,**kwargs):
            self.explicit_scope={ROOT,LEAF};self.nodes=set();self.questions=set();self.state_read=set()
            self.required_count=None;self.required_type=None;self.basic_only=False;self.excluded_scope=set();self.draft=None
        def validate_paper_candidates(self,args):
            # Same fixture evidence/version assertions, new internal entrypoint.
            return self.execute('validate_plan',args)
        def execute(self,name,args):
            if name=='get_learning_state':
                read_nodes.extend(args['kp_ids']);self.state_read.update(UUID(str(k)) for k in args['kp_ids']);return {'states':[]}
            assert name=='validate_plan'
            assert LEAF in self.state_read,'candidate leaf evidence must be read, not only its root'
            selected=[rows[UUID(str(k))] for k in args['question_ids']]
            self.draft={'questions':[{'question_id':str(q.id),'question_version':str(versions[qids.index(q.id)])} for q in selected],
                        'total_minutes':sum(q.estimated_minutes for q in selected)}
            return {'valid':True}

    monkeypatch.setattr(revision,'TaskTools',Tools)
    monkeypatch.setattr(revision,'question_version_reference',lambda q:str(UUID(int=999)) if changed and q.id==qids[0] else str(versions[qids.index(q.id)]))
    monkeypatch.setattr(revision,'question_eligibility',lambda q,n:NS(practice_eligible=eligible))
    monkeypatch.setattr(revision,'_descendant_ids',
                        lambda db,ids:({ROOT,LEAF} if ROOT in ids else set(ids)))
    monkeypatch.setattr(revision,'question_source_category',
                        lambda q:'personal_ai_practice' if source_changed else 'exam_curated')
    scope=[str(ROOT if roots else LEAF)]
    constraints={'preview_query_state':{'source_categories':['exam_curated']}} if restricted else {}
    if resolved:constraints.update(scope_version=1,resolved_scope_node_ids=list(map(str,(ROOT,LEAF))))
    handoff={'target_knowledge_node_ids':scope,'constraints':constraints}
    previous={'questions':[{'question_id':str(q),'question_version':str(v),'kp_id':str(LEAF)} for q,v in zip(qids,versions)],
              'total_minutes':9,'review_minutes':0}
    result=revision.revise_question_preview(lambda:nullcontext(DB()),
        {'previous_draft':previous,'previous_planner_handoff':handoff,'planner_handoff':handoff},
        budget,'只修改预算，减少练习量，先给我看看',NOW)
    return result,qids,read_nodes


@pytest.mark.parametrize('roots,resolved',[(True,False),(False,False),(True,True)])
def test_f01_unchanged_nine_minute_candidates_survive_root_or_leaf_scope(monkeypatch,roots,resolved):
    result,qids,read_nodes=revised(monkeypatch,roots=roots,resolved=resolved)
    assert result['status']=='ready',result
    assert result['draft']['total_minutes']==9
    assert [q['question_id'] for q in result['draft']['questions']]==list(map(str,qids))
    assert str(LEAF) in list(map(str,read_nodes))
    assert '已进入今日卷' not in result['message']


def test_f01_smaller_budget_keeps_a_feasible_original_subset(monkeypatch):
    result,qids,_=revised(monkeypatch,budget=5)
    assert result['status']=='ready' and result['draft']['total_minutes']==4
    assert [q['question_id'] for q in result['draft']['questions']]==[str(qids[0])]


@pytest.mark.parametrize('change,reason',[
    ({'changed':True},'question_version_changed'),
    ({'today':True},'already_in_today_plan'),
    ({'missing':True},'question_missing'),
    ({'eligible':False},'question_not_practice_eligible'),
    ({'restricted':True,'source_changed':True},'source_constraint'),
    ({'outside':True},'outside_original_scope'),
])
def test_f01_candidate_exclusions_have_the_actual_individual_reason(monkeypatch,change,reason):
    result,qids,_=revised(monkeypatch,**change)
    step=next(s for s in result['trace'] if s['tool']=='revalidate_saved_candidates')
    rejected=step['result']['rejected_candidates']
    assert any(reason in row['reasons'] for row in rejected)
    if reason!='already_in_today_plan':assert '已进入今日卷' not in result['message']
    if reason!='question_version_changed':assert '版本变化' not in result['message']
    if result['draft']:
        assert str(qids[0]) not in [q['question_id'] for q in result['draft']['questions']]


def test_f01_no_feasible_budget_reports_budget_not_false_staleness(monkeypatch):
    result,_,_=revised(monkeypatch,budget=5,minutes=(6,7))
    assert result['status']=='needs_info' and result['draft'] is None
    assert '预算' in result['message'] and '已进入今日卷' not in result['message'] and '版本变化' not in result['message']


def test_f01_revision_trace_is_json_serializable_without_changing_tool_ids(monkeypatch):
    result,qids,_=revised(monkeypatch)
    assert result['status']=='ready'
    persisted=json.loads(json.dumps(result['trace'],ensure_ascii=False))
    state=next(step for step in persisted if step['tool']=='get_learning_state')
    validation=next(step for step in persisted if step['tool']=='validate_plan')
    assert state['arguments_summary']['kp_ids']==[str(LEAF)]
    assert validation['arguments_summary']['question_ids']==list(map(str,qids))
    assert [q['question_id'] for q in result['draft']['questions']]==list(map(str,qids))
    assert result['draft']['total_minutes']==9


@pytest.mark.parametrize('message',[
    '给我看一道洛必达法则的练习题，先不要加入今日卷。',
    '给我看一道洛必达法则的练习题。',
    '帮我找一道洛必达法则的练习题。',
])
def test_f02_show_and_find_are_read_only_question_previews(message):
    route=route_message(message,StudyContext(surface='study'))
    assert (route.capability,route.intent)==('data_query','find')
    assert route.write_risk is False


@pytest.mark.parametrize('kind',['committed_task','accepted_request'])
def test_f03_committed_same_session_question_remains_resolvable(monkeypatch,kind):
    sid,tid,qid,vid,kp=[UUID(int=n) for n in range(401,406)]
    ref={'question_id':str(qid),'question_version':str(vid),'kp_id':str(kp),'question_type':'single_choice'}
    metadata={'planner_task_id':str(tid)} if kind=='committed_task' else {'practice_request_id':str(tid)}
    row=NS(id=UUID(int=410),session_id=sid,role='assistant',status='completed',metadata_=metadata)
    task=NS(session_id=sid,status='ready',metrics={'commit':{'item_ids':[str(UUID(int=411))]}},draft={'questions':[ref]},context={})
    request=NS(source_conversation_id=sid,status='accepted',expires_at=NOW,
               request={'preview_draft':{'questions':[ref]},'constraints':{}})
    class DB:
        def scalar(self,query):return row
        def get(self,entity,ident):
            if entity is LearningTask:return task
            if entity is PracticeRequest:return request
            return None
    selected,error=latest_preview(lambda:nullcontext(DB()),sid,'把刚才那道题加入今天的学习。',NOW)
    assert error is None
    assert selected['question_id']==str(qid) and selected['question_version']==str(vid)
    assert selected['committed_reference'] is True
    task.session_id=UUID(int=999);request.source_conversation_id=UUID(int=999)
    selected,error=latest_preview(lambda:nullcontext(DB()),sid,'把刚才那道题加入今天的学习。',NOW)
    assert selected is None and error


def test_f04_selection_finalization_does_not_emit_the_learning_statistics_template():
    messages=finalization_messages([{'kp_id':'k','recent_attempts':[]}])
    payload=json.loads(messages[1]['content'])
    payload.update(intent='plan',goal='把刚才那道题加入今天的学习。',
                   validated_plan='服务端已校验方案：1道选择题，共3分钟，尚未加入今日卷。')
    messages[1]['content']=json.dumps(payload,ensure_ascii=False)
    answer=json.loads(HandoffEvidenceProvider().tool_turn(messages,[],timeout=1)['message']['content'])['message']
    assert '只读学习证据回读' not in answer and '近期作答' not in answer
    assert payload['validated_plan'] in answer


def test_f04_explicit_statistics_and_selection_keep_both_subgoals():
    messages=finalization_messages([{'kp_id':'k','recent_attempts':[{'attempt_id':'a','result':'wrong','assisted':False}]}])
    payload=json.loads(messages[1]['content'])
    payload.update(intent='plan',goal='先统计独立答错几道，再给我选一道题预览',validated_plan='已校验的待确认题目预览')
    messages[1]['content']=json.dumps(payload,ensure_ascii=False)
    answer=json.loads(HandoffEvidenceProvider().tool_turn(messages,[],timeout=1)['message']['content'])['message']
    assert '独立答错1条' in answer and payload['validated_plan'] in answer
