"""Regression inputs from independent ex4 UI report; no model/network calls."""
import pytest
from backend.services.learning_task_service import _missing_plan_message
from backend.services.assistant_router import route_message
from backend.services.assistant_data_queries import classify_read_only_data_query
from backend.schemas.learning_assistant import StudyContext


def test_missing_plan_is_not_explained_as_append_inventory_failure():
    trace = [{'tool': 'find_questions', 'status': 'completed', 'result': {
        'questions': [{'question_id': 'q', 'in_today_plan': True}]}}]
    message = _missing_plan_message(trace, budget_minutes=60)
    assert '60分钟' in message and '未形成' in message
    assert '没有新题可追加' not in message
    assert '保留' in message and '校验' in message


@pytest.mark.parametrize('message', [
    '你说我级数很差，但我还没做过级数题，你为什么这么判断？',
    '根据什么？是我的自述还是实际作答记录？',
    '你把我的薄弱点记错了，请说明依据。',
])
def test_attribution_is_a_business_evidence_query(message):
    route = route_message(message, StudyContext(surface='study'))
    assert (route.capability, route.intent) == ('data_query', 'evidence_basis')


def test_self_report_is_acknowledged_by_a_separate_evidence_route():
    route = route_message('我真正不会的是等价无穷小替换，洛必达我会用。', StudyContext(surface='study'))
    assert (route.capability, route.intent) == ('data_query', 'self_report')


def test_general_recent_progress_does_not_depend_on_current_question():
    assert classify_read_only_data_query('我最近做得怎么样？') == 'learning_state'


def test_concept_why_question_remains_qa():
    route = route_message('为什么不能对这个极限使用洛必达法则？', StudyContext(surface='study'))
    assert route.capability == 'qa'


@pytest.mark.parametrize('message,expected',[
    ('今天只学60分钟，不要覆盖原来的90分钟计划',60),
    ('把原来的90分钟改为60分钟',60),
    ('之前安排了90分钟；现在改为半小时',30),
    ('我刚才花了30分钟，现在还可以学45分钟',45),
])
def test_changed_budget_does_not_reuse_a_trailing_old_duration(message,expected):
    from backend.services.learning_assistant_service import explicit_minutes
    assert explicit_minutes(message)==expected


@pytest.mark.parametrize('message',[
    '我不会等价无穷小替换', '我现在会用等价无穷小替换', '等价无穷小替换我会用',
])
def test_explicit_student_reports_keep_source_and_never_claim_verification(message):
    from backend.services.learner_self_report import extract_self_reports
    claims=extract_self_reports(message)
    assert len(claims)==1 and claims[0]['topic']=='等价无穷小替换'
    assert claims[0]['source']=='self_report' and claims[0]['independently_verified'] is False


def test_model_attribution_does_not_manufacture_a_self_report():
    from backend.services.learner_self_report import extract_self_reports
    assert not extract_self_reports('你说我级数很差，你为什么这么判断？')


@pytest.mark.parametrize('budget',[60,90])
def test_study_budget_and_paper_estimate_are_distinct_and_activity_minutes_sum(budget):
    import re
    from backend.services.planner_facts import render_pending_plan_recommendation
    summary={'version':'planner-factual-summary-v1','consistency':{'valid':True},
        'coverage':{'learning_state_complete':True,'inventory_complete':True},
        'inventory':{'additional_eligible_count':0},'today_plan':{'total_items':1,'completed_items':0,
            'pending_items':1,'remaining_minutes':46,'pending_item_details':[{'knowledge_point_name':'SYNTHETIC 数学二',
            'question_id':'q','estimated_minutes':46}]}}
    result=render_pending_plan_recommendation(summary,budget_minutes=budget)
    assert '预计还需约46分钟' in result and f'本次{budget}分钟建议预览' in result
    parts=re.search(r'先用(\d+)分钟.*再用(\d+)分钟.*最后(\d+)分钟',result)
    assert parts and sum(int(p) for p in parts.groups())==budget
    assert '原计划保留' in result and '二者不应混用' in result
