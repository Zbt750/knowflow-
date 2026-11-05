"""Real selector adapter contracts; fake database/tools are NOT PostgreSQL proof."""
from copy import deepcopy
from types import SimpleNamespace as NS
from uuid import uuid4

import pytest

from backend.services.home_intent import resolve
from backend.services import home_recommendation_service as home


@pytest.mark.parametrize('text', [
    '把当前题量补足到90分钟', '目前只有30分钟，继续补题到90分钟',
    '根据我的薄弱知识点内容，给我把当前题添加到我90分钟左右完成的题量。',
])
def test_total_time_is_not_one_question_or_budget_change(text):
    intent, trace = resolve(text, {}, lambda: pytest.fail('complete target uses no model'))
    assert intent.operation == 'fill_time' and intent.minutes == 90
    assert trace['model_calls'] == 0


@pytest.mark.parametrize('text', ['第三道题换成一道难一点的', '第3道题换成一道填空题'])
def test_single_replacement_has_exact_current_reference(text):
    paper = {'questions': [{'question_id':str(i),'kp_id':'a'} for i in range(6)]}
    intent, _ = resolve(text, paper, lambda: pytest.fail('explicit ordinal uses no model'))
    assert intent.operation == 'replace_question' and intent.refs == ['q3']


def test_target_fill_selects_multiple_real_candidates_without_changing_originals(monkeypatch):
    kp=uuid4(); base_ids=[uuid4() for _ in range(6)]; new_ids=[uuid4() for _ in range(8)]
    rows={qid:NS(current_version_id=uuid4(),estimated_minutes=5 if qid in base_ids else 10) for qid in base_ids+new_ids}
    original=[{'question_id':str(q),'question_version_id':str(rows[q].current_version_id),
               'version':'v','kp_id':str(kp),'minutes':5} for q in base_ids]
    paper={'questions':original}; snapshot=deepcopy(paper); checked=[]
    candidates=[{'question_id':str(q),'question_version':'v','kp_id':str(kp),'minutes':10,'in_today_plan':False} for q in new_ids]
    tools=NS(nodes=set(),questions=set(),state_facts={},budget_minutes=90,required_type=None,
             get_learning_state=lambda *a:{},find_questions=lambda *a:{'questions':candidates,'candidate_list_complete':True},
             validate_plan=lambda db,args:checked.append(args.question_ids) or {'valid':True})
    monkeypatch.setattr(home,'_tools',lambda *a:tools)
    monkeypatch.setattr(home,'question_version_reference',lambda q:'v')
    request={'append':True,'scope_mode':'append','count':1,'difficulty':None,'target_minutes':90}
    selected,evidence,error=home._bank_candidates(NS(get=lambda cls,key:rows[key]),None,'补足到90分钟',[kp],paper,request,90)
    assert error is None and selected == base_ids+new_ids[:6]
    assert evidence['target_time']['actual_minutes']==90
    assert checked == [selected] and paper == snapshot


def test_time_subset_prefers_real_near_target_over_all_returned_candidates():
    chosen = home._target_time_choices([
        {'question_id':'a','minutes':17,'kp_id':'k'},
        {'question_id':'b','minutes':10,'kp_id':'k'},
        {'question_id':'c','minutes':10,'kp_id':'k'},
    ], 20, {})
    assert [q['question_id'] for q in chosen]==['b','c']


def test_type_constraint_is_passed_to_query_not_applied_to_retained_paper(monkeypatch):
    kp=uuid4();base,new=uuid4(),uuid4();rows={q:NS(current_version_id=uuid4()) for q in [base,new]}
    original=[{'question_id':str(base),'question_version_id':str(rows[base].current_version_id),'kp_id':str(kp),'version':'v'}]
    def query(db,args):
        assert args.question_type=='fill_blank'
        return {'questions':[{'question_id':str(new),'question_version':'v','in_today_plan':False}]}
    tools=NS(nodes=set(),questions=set(),required_type='fill_blank',required_difficulty=None,basic_only=True,
             budget_minutes=90,get_learning_state=lambda *a:{},find_questions=query)
    def check(db,args):
        assert tools.required_type is None and tools.basic_only is False
        return {'valid':True}
    tools.validate_plan=check
    monkeypatch.setattr(home,'_tools',lambda *a:tools)
    monkeypatch.setattr(home,'question_version_reference',lambda q:'v')
    result,_,error=home._bank_candidates(NS(get=lambda cls,key:rows[key]),None,'加入一道填空题',[kp],{'questions':original},
        {'append':True,'scope_mode':'append','count':1,'difficulty':None,'question_type':'fill_blank'},90)
    assert error is None and result==[base,new]


@pytest.mark.parametrize('text', ['不要把当前题量补足到90分钟','不要替换第3道题',
    '补足到90分钟并删除第3道题','替换第3道并追加两道题',
    '补足到90分钟，再加两道洛必达题','补足到90分钟并换第三道题'])
def test_negative_and_compound_requests_do_not_change_plan(text):
    intent,_=resolve(text,{'questions':[{'question_id':str(i),'kp_id':'k'} for i in range(4)]})
    assert intent.operation=='clarify'


def test_replacement_preserves_every_other_id_and_exact_position(monkeypatch):
    kp=uuid4(); original_ids=[uuid4() for _ in range(18)]; extra=uuid4()
    rows={q:NS(current_version_id=uuid4()) for q in original_ids+[extra]}
    original=[{'question_id':str(q),'question_version_id':str(rows[q].current_version_id),'version':'v','kp_id':str(kp)} for q in original_ids]
    def query(db,args):
        assert args.exclude_question_ids==original_ids
        assert tools.required_difficulty=='hard'
        return {'questions':[{'question_id':str(extra),'question_version':'v','in_today_plan':False}]}
    checked=[]
    tools=NS(nodes=set(),questions=set(),budget_minutes=90,get_learning_state=lambda *a:{},find_questions=query,
             validate_plan=lambda db,args:checked.append(args.question_ids) or {'valid':True})
    monkeypatch.setattr(home,'_tools',lambda *a:tools)
    monkeypatch.setattr(home,'question_version_reference',lambda q:'v')
    selected,_,error=home._bank_candidates(NS(get=lambda cls,key:rows[key]),None,'第3道换成难一点的',[kp],
        {'questions':original},{'append':True,'scope_mode':'append','count':1,'difficulty':'hard','replacement_index':2},90)
    assert error is None and selected==original_ids[:2]+[extra]+original_ids[3:]
    assert checked==[selected]


def test_time_shortage_does_not_fabricate_candidates_or_change_base():
    candidates=[{'question_id':'a','kp_id':'k','minutes':5}]
    assert home._target_time_choices(candidates,60,{})==candidates
    assert home._target_time_choices(candidates,3,{})==[]


def test_target_ranking_uses_real_wrong_result_not_self_report_or_unknown():
    candidates=[{'question_id':'a','kp_id':'a','minutes':10},{'question_id':'b','kp_id':'b','minutes':10}]
    states={'a':{'self_report':1,'recent_attempts':[]},'b':{'recent_attempts':[{'result':'wrong'}]}}
    assert home._target_time_choices(candidates,10,states)==[candidates[1]]


def test_unknown_reference_never_replaces_a_whole_scope():
    for text in ('把刚才那道题换掉','第99道题换成填空题'):
        intent,_=resolve(text,{'questions':[{'question_id':'x','kp_id':'k'}]})
        assert intent.operation=='clarify'


def test_named_different_scope_is_not_silently_ignored_during_single_replacement(monkeypatch):
    kp,other=uuid4(),uuid4()
    monkeypatch.setattr(home,'_tools',lambda *a:NS(explicit_scope={other}))
    paper={'questions':[{'question_id':str(uuid4()),'kp_id':str(kp)}],'selected_kp_ids':[str(kp)]}
    result,_,error=home._bank_exact_revision(None,None,'第1道换成隐函数题',paper,'replace_question',90,['q1'])
    assert result is None and '原方案已保留' in error
