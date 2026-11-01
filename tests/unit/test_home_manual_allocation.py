from types import SimpleNamespace as NS
from uuid import uuid4, UUID
import pytest
from backend.services import home_recommendation_service as home


def fixture(monkeypatch, *, empty=False, fail=False):
    scopes=[uuid4() for _ in range(3)]
    nodes={k:NS(id=k,name=f'真实节点{i}',parent_id=None,is_active=True,is_assessable=True) for i,k in enumerate(scopes)}
    original=[{'question_id':str(uuid4()),'question_version_id':str(uuid4()),'version':'v1',
               'kp_id':str(scopes[i%2]),'kp_name':nodes[scopes[i%2]].name,'minutes':5} for i in range(18)]
    extra={'question_id':str(uuid4()),'question_version_id':str(uuid4()),'version':'v2',
           'kp_id':str(scopes[2]),'kp_name':nodes[scopes[2]].name,'minutes':5}
    records={UUID(q['question_id']):NS(current_version_id=UUID(q['question_version_id'])) for q in original+[extra]}
    calls=[]
    def paper(db, ids, minutes, now, question_limit=None, candidate_question_ids=None, **kw):
        calls.append((ids,question_limit,candidate_question_ids,kw))
        if fail:raise RuntimeError('query outage')
        qs=([q for q in original+[extra] if UUID(q['question_id']) in candidate_question_ids]
            if candidate_question_ids is not None else [] if empty else [extra])
        return {'questions':qs,'selected_kp_ids':[str(k) for k in ids],'total_minutes':sum(q['minutes'] for q in qs),'budget_minutes':minutes}
    monkeypatch.setattr(home,'_paper',paper)
    monkeypatch.setattr(home,'question_version_reference',lambda q:'v1')
    checked=[]
    tools=NS(nodes=set(),questions=set(),budget_minutes=90,get_learning_state=lambda *a:{},validate_plan=lambda db,args:checked.append(args.question_ids) or {'valid':True})
    monkeypatch.setattr(home,'_tools',lambda *a:tools)
    db=NS(get=lambda cls,k:nodes.get(k) if cls is home.KnowledgePoint else records.get(k))
    base={'questions':original,'selected_kp_ids':[str(k) for k in scopes[:2]],'budget_minutes':90}
    return db,scopes,base,extra,calls,checked


def test_manual_add_preserves_eighteen_and_allocates_one_without_budget_truncation(monkeypatch):
    db,ids,base,extra,calls,checked=fixture(monkeypatch)
    paper=home._manual_scope_paper(db,ids,90,None,base)
    assert paper['questions']==base['questions']+[extra]
    assert paper['total_minutes']==95 and paper['selected_kp_ids']==list(map(str,ids))
    assert calls[0][0]==[ids[2]] and calls[0][1]==1
    assert calls[-1][2]==[UUID(q['question_id']) for q in base['questions']+[extra]]
    assert paper['scope_nodes'][-1]['name']=='真实节点2'
    assert paper['scope_nodes'][-1]['assigned_count']==1 and checked


def test_empty_new_node_is_named_and_explicit_without_discarding_original(monkeypatch):
    db,ids,base,extra,calls,checked=fixture(monkeypatch,empty=True)
    paper=home._manual_scope_paper(db,ids,90,None,base)
    assert paper['questions']==base['questions']
    assert paper['scope_nodes'][-1]['allocation_status']=='no_eligible_questions'
    assert paper['scope_nodes'][-1]['assigned_count']==0
    assert paper['scope_nodes'][-1]['name']=='真实节点2'
    assert paper['allocation_kp_ids']==list(map(str,ids[:2]))


def test_explicit_removal_only_removes_that_nodes_questions(monkeypatch):
    db,ids,base,extra,calls,checked=fixture(monkeypatch)
    paper=home._manual_scope_paper(db,[ids[1]],90,None,base)
    assert paper['questions']==[q for q in base['questions'] if q['kp_id']==str(ids[1])]


def test_new_leaf_coverage_uses_formal_selector_without_advisory_time_cap(monkeypatch):
    calls=[]
    monkeypatch.setattr(home,'preview_initial_questions',lambda *a,**kw:calls.append(kw) or [])
    home._paper(None,[uuid4()],90,None,question_limit=1,coverage_preview=True)
    assert calls[0]['minute_limit'] is None
    assert calls[0]['question_limit']==1
    assert calls[0]['candidate_question_ids'] is None


def test_formal_revalidation_keeps_empty_scope_out_of_selector_without_hiding_selection():
    full=[str(uuid4()),str(uuid4())]
    paper={'selected_kp_ids':full,'allocation_kp_ids':full[:1]}
    assert home._allocation_ids(paper)==[UUID(full[0])]
    assert paper['selected_kp_ids']==full


def test_multiple_nodes_have_independent_allocation_traces_and_real_counts(monkeypatch):
    db,ids,base,extra,calls,checked=fixture(monkeypatch)
    other=uuid4();ids.append(other)
    second={**extra,'question_id':str(uuid4()),'kp_id':str(other),'kp_name':'新增第二节点'}
    original_get=db.get
    db.get=lambda cls,k:NS(id=other,name='新增第二节点',parent_id=None,is_active=True,is_assessable=True) if cls is home.KnowledgePoint and k==other else original_get(cls,k)
    def paper(db,scope,minutes,now,question_limit=None,candidate_question_ids=None,**kw):
        if candidate_question_ids is not None:
            qs=base['questions']+[extra,second]
        else:
            qs=[extra] if scope==[ids[2]] else [second]
            kw['selection_diagnostics'].update(candidates_found=5,eligible_count=3)
        return {'questions':qs,'total_minutes':sum(q['minutes'] for q in qs),'budget_minutes':minutes}
    monkeypatch.setattr(home,'_paper',paper)
    trace={}
    result=home._manual_scope_paper(db,ids,90,None,base,diagnostics=trace)
    assert result['questions']==base['questions']+[extra,second]
    assert result['total_minutes']==100
    assert sum(n['assigned_count'] for n in result['scope_nodes'])==20
    for entry in trace['nodes'][2:]:
        assert entry['received'] and entry['candidates_found']==5
        assert entry['candidates_accepted']==entry['assigned']==1 and entry['rejected_reason'] is None


def test_one_policy_rejection_does_not_prevent_another_new_node(monkeypatch):
    db,ids,base,extra,calls,checked=fixture(monkeypatch)
    empty=uuid4();ids.insert(2,empty);get=db.get
    db.get=lambda cls,k:NS(id=k,name='暂无法安排',parent_id=None,is_active=True,is_assessable=True) if cls is home.KnowledgePoint and k==empty else get(cls,k)
    original_paper=home._paper
    def paper(db,scope,*a,**kw):
        if scope==[empty]:
            kw['selection_diagnostics'].update(candidates_found=2,eligible_count=2)
            raise ValueError('question_version_or_eligibility_invalid')
        return original_paper(db,scope,*a,**kw)
    monkeypatch.setattr(home,'_paper',paper)
    trace={};result=home._manual_scope_paper(db,ids,90,None,base,diagnostics=trace)
    assert result['questions']==base['questions']+[extra]
    assert result['scope_nodes'][2]['assigned_count']==0
    assert trace['nodes'][2]['rejected_reason']=='question_version_or_eligibility_invalid'
    assert trace['nodes'][3]['assigned']==1


@pytest.mark.parametrize('case',['query','unknown','stale'])
def test_failures_leave_input_plan_unchanged(monkeypatch,case):
    import copy
    db,ids,base,extra,calls,checked=fixture(monkeypatch,fail=case=='query')
    before=copy.deepcopy(base)
    if case=='unknown':ids.append(uuid4())
    if case=='stale':monkeypatch.setattr(home,'question_version_reference',lambda q:'changed')
    with pytest.raises((ValueError,RuntimeError)):
        home._manual_scope_paper(db,ids,90,None,base)
    assert base==before
