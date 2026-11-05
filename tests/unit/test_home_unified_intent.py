from backend.services.home_intent import parse_rule, exact_edit
import json
import pytest
from types import SimpleNamespace as NS
from backend.services.home_intent import HomeIntent, resolve


def paper():
    return {'selected_kp_ids':['a','b'],'budget_minutes':90,'total_minutes':90,'questions':[
        {'question_id':str(i),'question_version_id':'v'+str(i),'kp_id':'a' if i<3 else 'b','kp_name':'洛必达法则' if i<3 else '隐函数求导','minutes':5} for i in range(18)]}


@pytest.mark.parametrize('text', ['不要删除第3道题', '别恢复原来的推荐方案',
    '不要只练洛必达法则', '不用把预算改成60分钟',
    '不删除第3道题', '不想恢复原来的推荐方案', '不许替换原来的题'])
def test_negated_mutations_never_change_the_current_plan(text):
    original=paper()
    intent,trace=resolve(text,original,lambda:pytest.fail('explicit negation needs no model'))
    assert intent.operation=='clarify'
    assert exact_edit(original,intent)==original
    assert trace['model_calls']==0


@pytest.mark.parametrize('number,count',[('十一',11),('二十',20),('二十三',23)])
def test_multi_character_chinese_append_quantity_is_not_a_suffix(number,count):
    from backend.services.bank_selection_intent import bank_selection_request
    text=f'帮我加入{number}道洛必达法则的题'
    assert bank_selection_request(text)['count']==count
    intent,trace=resolve(text,paper(),lambda:pytest.fail('explicit count needs no model'))
    assert intent.operation=='append' and intent.quantity==count


def test_delete_one_with_multiple_matches_clarifies_instead_of_replacing():
    a=paper();intent=parse_rule('删除一道洛必达法则的题。',a)
    assert intent.operation=='clarify' and exact_edit(a,intent)==a


def test_remove_scope_only_removes_that_nodes_items():
    a=paper();i=parse_rule('把洛必达法则这个知识点移除。',a);b=exact_edit(a,i)
    assert b['questions']==a['questions'][3:] and b['selected_kp_ids']==['b']


def test_budget_only_preserves_all_question_identities_order_and_scope():
    a=paper();i=parse_rule('预算改成10分钟。',a);b=exact_edit(a,i)
    assert b['questions']==a['questions'] and b['selected_kp_ids']==a['selected_kp_ids']
    assert b['budget_minutes']==10 and b['total_minutes']==90


@pytest.mark.parametrize('text', [
    '按从易到难排序。',
    '把简单题放前面，综合题放最后。',
    '前半部分基础，后半部分综合。',
])
def test_easy_to_hard_reorder_changes_only_order_and_preserves_pinned_versions(text):
    a=paper()
    levels=['comprehensive','basic','medium','advanced','basic','hard']*3
    for question,level in zip(a['questions'],levels):
        question['difficulty']=level
    intent,trace=resolve(text,a,lambda:pytest.fail('explicit reorder is deterministic'))
    assert intent.operation=='reorder' and intent.order=='easy_to_hard'
    assert trace['model_calls']==0
    b=exact_edit(a,intent)
    expected=sorted(a['questions'],key=lambda q:{'basic':0,'medium':1,'hard':2,'comprehensive':3,'advanced':3}[q['difficulty']])
    assert b['questions']==expected
    assert b['selected_kp_ids']==a['selected_kp_ids']
    assert b['total_minutes']==a['total_minutes']
    assert {(q['question_id'],q['question_version_id']) for q in b['questions']} == {
        (q['question_id'],q['question_version_id']) for q in a['questions']}
    assert a['questions']!=b['questions']


@pytest.mark.parametrize('text', [
    '整卷难度提高一点。',
    '今天安排得简单一些。',
    '整体难一点。',
])
def test_whole_plan_difficulty_change_is_not_misrepresented_as_done(text):
    original=paper()
    intent,trace=resolve(text,original,lambda:pytest.fail('unsupported whole-plan difficulty should clarify locally'))
    assert intent.operation=='clarify'
    assert '不能自动替换整卷' in intent.question
    assert exact_edit(original,intent)==original
    assert trace['model_calls']==0


@pytest.mark.parametrize('text',['追加一道并删掉两道','先生成再追加一道','加一道洛必达并把难度改简单',
    '追加一道洛必达，预算改成60分钟','只保留洛必达再追加一道'])
def test_compound_never_silently_executes_one_part(text):
    intent,trace=resolve(text,paper(),lambda:pytest.fail('compound already needs clarification'))
    assert intent.operation=='clarify' and trace['model_calls']==0


def test_complete_rule_never_resolves_a_model():
    i,t=resolve('再给我加一道洛必达法则的题。',paper(),lambda:pytest.fail('rule must be free'))
    assert i.operation=='append' and i.quantity==1 and t['source']=='rule'


def test_multi_topic_count_edit_is_atomic_and_defaults_unspecified_few_to_one():
    text='帮我减少几道洛必达法则的题目，增加几道隐函数的题目。'
    intent,trace=resolve(text,paper(),lambda:pytest.fail('named compound edit is deterministic'))
    assert intent.operation=='topic_count'
    assert intent.refs==['k1','k2'] and intent.deltas==[-1,1]
    assert '[underspecified_quantities_defaulted_to_one]' in intent.terms
    assert trace['source']=='rule' and trace['model_calls']==0


def test_followup_count_correction_reuses_the_named_topic():
    intent,trace=resolve('帮我减少两道洛必达法则的题目，减少1道吧。',paper(),
        lambda:pytest.fail('explicit same-message correction should be rule parsed'))
    assert intent.operation=='topic_count' and intent.refs==['k1'] and intent.deltas==[-1]
    assert trace['source']=='rule' and trace['model_calls']==0


@pytest.mark.parametrize('text', [
    '帮我把当前这些内容都换成408的题目，我今天打算做1个小时408的。',
    '根据我没有做过的知识点来进行安排题目就好，把当前的题目都换了，你安排6个知识点的408题目，题量是1个小时左右的。',
])
def test_cross_subject_replacement_is_a_versioned_proposal_intent(text):
    intent,trace=resolve(text,paper(),lambda:pytest.fail('408 replacement has a deterministic rule'))
    assert intent.operation=='subject_plan' and intent.terms=='408'
    assert intent.quantity==6 and intent.minutes==60
    assert trace['source']=='rule' and trace['model_calls']==0


def test_check_today_arrangement_is_read_only_summary_intent():
    intent,trace=resolve('我先看看今天怎么安排。',paper(),
        lambda:pytest.fail('read-only daily summary should be deterministic'))
    assert intent.operation=='summary'
    assert trace['model_calls']==0


def test_easy_target_without_reliable_difficulty_data_clarifies_safely():
    original=paper()
    intent,trace=resolve('减少一道比较简单的吧。',original,
        lambda:pytest.fail('difficulty uncertainty should be handled without a model'))
    assert intent.operation=='clarify'
    assert '没有可核验的逐题难度依据' in intent.question
    assert exact_edit(original,intent)==original
    assert trace['model_calls']==0


def test_budget_revision_with_previous_time_context_is_rule_parsed():
    intent=parse_rule('刚才90分钟太长了，改成60分钟。',paper())
    assert intent.operation=='budget' and intent.minutes==60


def test_additive_bank_phrase_for_implicit_function_is_not_a_replacement():
    from backend.services.bank_selection_intent import bank_selection_request
    request=bank_selection_request('给我来一道隐函数的题目')
    assert request and request['scope_mode']=='append' and request['additional_count']==1
    intent,trace=resolve('给我来一道隐函数的题目',paper(),lambda:pytest.fail('complete append must stay deterministic'))
    assert intent.operation=='append' and intent.quantity==1 and trace['source']=='rule'


def test_implicit_function_short_name_is_a_code_specific_scope_alias():
    from backend.services.learning_task_tools import TaskTools
    aliases=TaskTools._scope_aliases('隐函数求导','math.calculus.differential.implicit')
    assert '隐函数' in aliases and '隐函数的导数' in aliases
    unrelated=TaskTools._scope_aliases('隐函数求导','math.other.node')
    assert '隐函数' not in unrelated


@pytest.mark.parametrize('raw',['not JSON','{"operation":"append","quantity":1,"session_id":"forged"}',
                              '{"operation":"replace","terms":"洛必达法则"}'])
def test_invalid_or_unauthorized_model_proposal_never_changes_plan(raw):
    a=paper();calls=[]
    provider=NS(timeout=60,max_tokens=4000,complete=lambda *args,**kw:(calls.append(kw) or raw,None))
    i,t=resolve('这个太难了，换一道。',a,lambda:provider)
    assert i.operation=='clarify' and a==paper() and len(calls)==1
    assert t['model_calls']==1


def test_model_resolves_aliases_without_receiving_actual_ids_or_tool_access():
    calls=[]
    raw=HomeIntent(operation='remove_question',refs=['q1'],quantity=1).model_dump_json()
    def complete(messages,**kw):
        payload=json.loads(messages[1]['content']);assert 'value' not in payload['references']['q1']
        calls.append(kw);return raw,None
    i,t=resolve('第1道不要了。',paper(),lambda:NS(timeout=60,max_tokens=4000,complete=complete))
    assert i.refs==['q1'] and t['source']=='llm' and len(calls)==1
    ambiguous,_=resolve('刚才那道不要了。',paper(),lambda:NS(timeout=60,max_tokens=4000,complete=complete))
    assert ambiguous.operation=='clarify'


def test_provider_failure_is_safe_and_not_retried():
    calls=[]
    def fail(*a,**kw):calls.append(1);raise TimeoutError()
    i,t=resolve('帮我换一个合适的',paper(),lambda:NS(timeout=60,max_tokens=4000,complete=fail))
    assert i.operation=='clarify' and calls==[1] and t['failure']=='TimeoutError'


def test_history_is_bounded_by_caller_and_only_loaded_for_model_fallback():
    calls=[]
    def history():calls.append('history');return [{'role':'user','content':'先前讨论'}]
    def complete(messages,**kw):
        data=json.loads(messages[1]['content'])
        assert data['history'][0]['content']=='先前讨论'
        assert data['current_plan']['question_count']==18
        return HomeIntent(operation='clarify',question='请指定题号').model_dump_json(),None
    provider=NS(timeout=60,max_tokens=4000,complete=complete)
    resolve('再加一道洛必达法则的题',paper(),lambda:provider,history_factory=history)
    assert calls==[]
    intent,_=resolve('这个太难了，换一道',paper(),lambda:provider,history_factory=history)
    assert calls==['history'] and intent.operation=='clarify'


@pytest.mark.parametrize('text',['预算改成1分钟','预算改成999分钟'])
def test_invalid_rule_parameters_are_safe_not_uncaught_schema_errors(text):
    intent,trace=resolve(text,paper(),lambda:pytest.fail('invalid rule does not need paid retry'))
    assert intent.operation=='clarify' and trace['failure']=='rule_schema_invalid'


@pytest.mark.parametrize('data',[{'operation':'unsupported'},{'operation':'append','quantity':0},
    {'operation':'budget','minutes':'60'},{'operation':'append','task_id':'invented'}])
def test_strict_schema_rejects_invalid_proposals(data):
    from pydantic import ValidationError
    with pytest.raises(ValidationError):HomeIntent.model_validate(data)


@pytest.mark.parametrize('text,count',[('洛必达法则的题你再给我加一道，原来的别动。',1),
    ('帮我增加一道洛必达法则的题目',1),('在原方案上再加两道洛必达法则的题',2)])
def test_spoken_append_count_uses_rule_and_never_replace(text,count):
    intent,_=resolve(text,paper(),lambda:pytest.fail('complete append should not call a model'))
    assert intent.operation=='append' and intent.quantity==count


def test_explicit_count_reduction_preserves_scope_and_retained_versions():
    a=paper()
    intent,trace=resolve('保留推荐范围，减少到2道题',a,lambda:pytest.fail('explicit count must not require a model'))
    assert intent.operation=='count' and intent.quantity==2
    b=exact_edit(a,intent)
    assert b['questions']==a['questions'][:2]
    assert b['selected_kp_ids']==a['selected_kp_ids']
    assert b['question_limit']==2
    assert a==paper()


@pytest.mark.parametrize('text,count', [
    ('今天安排一个小时的408。',6),
    ('根据我没有做过的知识点安排六个408知识点，60分钟左右。',6),
    ('把今天数学题全部换成408，安排四个知识点，60分钟。',4),
])
def test_r38_subject_budget_plan_is_deterministic_and_text_bound(text,count):
    intent,trace=resolve(text,paper(),lambda:pytest.fail('explicit subject planning needs no model'))
    assert (intent.operation,intent.terms,intent.minutes,intent.quantity)==('subject_plan','408',60,count)
    assert trace['model_calls']==0


@pytest.mark.parametrize('text',[
    '不要把数学题换成408，预算60分钟。',
    '先别安排一个小时的408。',
    '能不能把数学题换成408，安排60分钟？',
    '如果有空就安排一个小时的408。',
    '以后安排一个小时的408。',
])
def test_r38_subject_negation_question_condition_and_delay_preserve_proposal(text):
    before=paper()
    intent,trace=resolve(text,before,lambda:pytest.fail('authority boundary needs no model'))
    assert intent.operation=='clarify'
    assert exact_edit(before,intent)==before
    assert trace['model_calls']==0


def test_r38_model_cannot_invent_subject_budget_or_topic_count():
    from backend.services.home_intent import validate
    proposed=HomeIntent(operation='subject_plan',terms='408',minutes=90,quantity=6)
    assert validate(proposed,'今天安排一个小时的408。',paper()).operation=='clarify'
