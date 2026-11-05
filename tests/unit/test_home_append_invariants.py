from types import SimpleNamespace as NS
from uuid import uuid4
import pytest
from backend.services.bank_selection_intent import bank_selection_request
from backend.services import home_recommendation_service as home
from backend.services import practice_service as practice


@pytest.mark.parametrize('goal',[
    '帮我增加一道洛必达法则的题目。','帮我加入一道洛必达法则的题目。',
    '再来一道洛必达法则的题目。','在原来的推荐基础上加一道题。',
    '再加一道类似的题。','洛必达法则的题你再给我加一道','再来一道这个知识点的题'])
def test_addition_phrases_have_an_explicit_append_operation_and_one_requested_addition(goal):
    request=bank_selection_request(goal)
    assert request is not None and request['scope_mode']=='append'
    assert request['count']==request['additional_count']==1
    if '类似' in goal:assert request['similar'] is True


@pytest.mark.parametrize('phrase',['增加','再给我加'])
@pytest.mark.parametrize('amount',[1,2])
@pytest.mark.parametrize('scope_count',[6,9])
def test_eighteen_original_questions_and_six_scopes_survive_five_results_and_duplicates(monkeypatch,amount,scope_count,phrase):
    scopes=[uuid4() for _ in range(scope_count)];original_ids=[uuid4() for _ in range(18)];extra=[uuid4() for _ in range(5)]
    rows={qid:NS(id=qid,current_version_id=uuid4(),estimated_minutes=5,kp_id=scopes[i%scope_count]) for i,qid in enumerate(original_ids+extra)}
    for qid in extra:rows[qid].kp_id=scopes[0]
    original=[{'question_id':str(q),'question_version_id':str(rows[q].current_version_id),
               'kp_id':str(rows[q].kp_id),'version':'stable'} for q in original_ids]
    found=[{'question_id':str(q),'question_version':'stable','in_today_plan':False} for q in [original_ids[0],extra[0],extra[0],*extra[1:]]]
    checked=[];reads=[]
    tools=NS(nodes=set(),questions=set(),budget_minutes=120,get_learning_state=lambda db,args:reads.append(args.kp_ids) or {},
        find_questions=lambda *a:{'questions':found,'candidate_list_complete':True},
        validate_plan=lambda db,args:checked.append(args.question_ids) or {'valid':True})
    monkeypatch.setattr(home,'_tools',lambda *a,**kw:tools)
    monkeypatch.setattr(home,'question_version_reference',lambda q:'stable')
    goal=(f'洛必达法则的题你再给我加{amount}道' if phrase=='再给我加' else f'帮我增加{amount}道洛必达法则的题目。');request=bank_selection_request(goal)
    assert request is not None
    assert request['append'] and request['scope_mode']=='append'
    selected,evidence,error=home._bank_candidates(NS(get=lambda cls,key:rows[key]),None,goal,[scopes[0]],
        {'questions':original,'selected_kp_ids':list(map(str,scopes))},request,120,base_scope_ids=scopes)
    assert error is None and selected==original_ids+extra[:amount]
    assert checked==[selected] and len(set(selected))==18+amount
    assert evidence['base_scope_ids']==list(map(str,scopes))
    assert evidence['retained_ids']==list(map(str,original_ids))
    assert evidence['selected_addition_ids']==list(map(str,extra[:amount]))
    assert [kp for batch in reads for kp in batch]==scopes
    assert all(len(batch)<=8 for batch in reads)
    assert [q['question_version_id'] for q in original]==[str(rows[q].current_version_id) for q in original_ids]
    if amount==1:
        saved={'questions':original+[{'question_id':str(extra[0]),'question_version_id':str(rows[extra[0]].current_version_id),
            'kp_id':str(rows[extra[0]].kp_id),'version':'stable'}],'selected_kp_ids':list(map(str,scopes))}
        second,_,error=home._bank_candidates(NS(get=lambda cls,key:rows[key]),None,'再加一道洛必达法则的题目',[scopes[0]],
            saved,bank_selection_request('再加一道洛必达法则的题目'),120,base_scope_ids=scopes)
        assert error is None and second==original_ids+extra[:2]
        assert saved['questions'][:18]==original


def test_explicit_replacement_is_not_reclassified_as_append():
    request=bank_selection_request('只练洛必达法则，不要其他知识点，再加入一道题。')
    assert request['scope_mode']=='replace' and request['append'] is False
    assert bank_selection_request('把原来的推荐全部替换成洛必达法则，加入一道题。')['scope_mode']=='replace'


def test_exact_paper_order_keeps_the_original_prefix_even_across_question_types():
    a,b,c=[uuid4() for _ in range(3)]
    items=[('kp',None,'single_choice',c,None),('kp',None,'proof',b,None),('kp',None,'calculation',a,None)]
    ordered=practice._order_paper_items(items,[a,b,c])
    assert [item[3] for item in ordered]==[a,b,c]
    assert items[0][3]==c  # Sorting does not mutate caller input.


def test_old_increase_replacement_recovers_full_saved_base_without_modifying_history(monkeypatch):
    kp=uuid4();original=[{'question_id':str(uuid4()),'question_version_id':str(uuid4()),'kp_id':str(kp),'minutes':5} for _ in range(18)]
    row=NS(id=uuid4(),session_id=uuid4(),status='ready',goal='帮我增加一道洛必达法则的题目。',
        draft={'questions':[{'question_id':str(uuid4())}]},metrics={},budget_minutes=90,message='试卷预览5道',error_code=None,
        context={'home_recommendation':True,'baseline':{'questions':original,'selected_kp_ids':[str(kp)],'total_minutes':90,'budget_minutes':90}})
    monkeypatch.setattr(home,'_draft_version',lambda row:'a'*64)
    result=home._result_view(NS(get=lambda *a:None),row)
    assert result['status']=='needs_info' and result['draft'] is None
    assert result['retained_baseline']['questions']==original
    assert row.status=='ready' and len(row.draft['questions'])==1


def test_new_candidate_version_change_is_not_silently_accepted_or_replaced(monkeypatch):
    kp=uuid4();base,new=uuid4(),uuid4();version=uuid4()
    rows={base:NS(current_version_id=version,reference='base-version'),new:NS(current_version_id=uuid4(),reference='changed')}
    original=[{'question_id':str(base),'question_version_id':str(version),'kp_id':str(kp),'version':'base-version'}]
    tools=NS(nodes=set(),questions=set(),budget_minutes=90,get_learning_state=lambda *a:{},
        find_questions=lambda *a:{'questions':[{'question_id':str(new),'question_version':'old-version','in_today_plan':False}],'candidate_list_complete':True},
        validate_plan=lambda *a:pytest.fail('stale candidate must not produce a validated preview'))
    monkeypatch.setattr(home,'_tools',lambda *a,**kw:tools)
    monkeypatch.setattr(home,'question_version_reference',lambda q:q.reference)
    result,evidence,_=home._bank_candidates(NS(get=lambda cls,qid:rows[qid]),None,'增加一道洛必达题',[kp],
        {'questions':original},bank_selection_request('增加一道洛必达题'),90,base_scope_ids=[kp])
    assert result is None and evidence['error']=='bank_candidate_stale'
    assert original[0]['question_id']==str(base) and len(original)==1
