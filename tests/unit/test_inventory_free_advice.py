import re
from backend.services.learning_task_service import _inventory_free_advice

def trace(attempts=None, state_ok=True):
    result=[{'tool':'get_question_availability','status':'completed','result':{'available_to_append_count':0,'eligible_nodes':[{'name':'SYNTHETIC 洛必达'}]}}]
    if state_ok: result.append({'tool':'get_learning_state','status':'completed','result':{'states':[{'recent_attempts':attempts or []}]}})
    return result

def test_zero_inventory_advice_distinguishes_observed_evidence_and_exact_time():
    attempts=[{'attempt_id':str(i),'result':r,'assisted':a} for i,(r,a) in enumerate([('right',False),('wrong',False),('right',True)])]
    message=_inventory_free_advice(trace(attempts),90)
    assert '独立答对1次' in message and '独立答错1次' in message and '辅助后答对1次' in message
    assert sum(map(int,re.findall(r'\d+\. (\d+)分钟',message)))==90
    assert '程序根据实际工具证据' in message and '没有创建或追加' in message

def test_no_history_or_failed_tool_is_never_invented():
    assert '没有可用的作答历史' in _inventory_free_advice(trace(),90)
    assert '读取失败或尚未取得' in _inventory_free_advice(trace(state_ok=False),90)
    assert _inventory_free_advice([],90) is None

def test_explicit_advice_without_formal_plan_is_read_only_recommendation():
    from backend.services.learning_task_tools import classify_task_intent
    assert classify_task_intent('根据实际做题情况给我90分钟复习建议，不创建正式计划')=='recommend'
    assert classify_task_intent('安排90分钟数学二，先别直接创建学习计划')=='recommend'
    assert classify_task_intent('题库里有多少题，不创建计划')=='query'
    assert classify_task_intent('给我安排两道题')=='plan'
