import pytest
from backend.services.personal_generation_intent import _preferences,explicitly_generate,DEFAULT_GENERATION_COUNT
from backend.services.generation_outcomes import with_outcomes
from backend.services.personal_question_service import result_message


@pytest.mark.parametrize('text,count',[
    ('帮我生成一道更难的类似题',1),('帮我出一道类似题',1),('再来一题',1),
    ('给我出一题更难的',1),('生成两道类似题',2),('生成三道题，难度高一点',3),
    ('帮我生成练习题',DEFAULT_GENERATION_COUNT),
    ('帮我生成比这题还难的题',1),('给我出个更难的',1),('再来一道更难的',1),('再来一道',1),
    ('生成 3 道题',3),('生成 5 道题，难很多',5),
    ('那给我再生成2道都是中等的题目\n最新出题要求：你帮我生成一道比这道更难的题',1),
    ('生成两道计算题\n最新出题要求：更难一点',2),
    ('生成两道计算题\n最新出题要求：改成一道证明题',1),
    ('先出两道，算了只出一道更难的题',1),
    ('生成一道类似题。原题：分析下面2道选择题。',1),
])
def test_explicit_quantity_precedes_defaults_old_instructions_and_difficulty(text,count):
    assert sum(n for _,n in _preferences(text)[1])==count
    if '最新出题要求' not in text:assert explicitly_generate(text)


def test_typed_groups_keep_total_without_adding_a_default_group():
    assert _preferences('生成两道选择题和一道填空题')[1]==[('single_choice',2),('fill_blank',1)]


def test_api_and_parser_share_single_question_default():
    from uuid import uuid4
    from backend.schemas.personal_questions import GenerationTarget
    assert DEFAULT_GENERATION_COUNT == GenerationTarget(kp_id=uuid4()).count == 1


def test_pre_call_budget_stop_is_not_counted_as_a_physical_provider_request():
    summary=with_outcomes({'requested':1,'calls':[],'attempted_indices':[1],
        'question_ids':[],'failures':[{'index':1,'reason':'BUDGET_STOPPED'}]})['outcome_summary']
    assert summary['attempted_count']==summary['provider_calls']==0
    assert summary['network_failed_count']==summary['quality_rejected_count']==0


def test_stopped_slots_are_not_reported_as_quality_rejections():
    result=with_outcomes({'requested':3,'question_ids':[],'calls':[{}],'attempted_indices':[1],
        'failures':[{'index':1,'reason':'PROVIDER_TIMEOUT'}]})
    summary=result['outcome_summary']
    assert summary['failed_count']==1 and summary['not_attempted_count']==2
    assert summary['quality_rejected_count']==0 and summary['provider_calls']==1
    text=result_message(result)
    assert '2道尚未执行' in text and '质量检查失败' not in text


def test_actual_partial_failure_shape_classifies_answer_conflict_not_unattempted():
    # Redacted shape of actual batch e3217d80...: second response parsed far
    # enough to prove answer/final_value conflict, not a missing model call.
    result=with_outcomes({'requested':2,'question_ids':['saved'],'calls':[{},{}],
        'failures':[{'index':2,'reason':'FORMAT_ERROR','issues':['answer_final_value_conflict']}]})
    summary=result['outcome_summary']
    assert summary['requested_count']==2 and summary['saved_count']==1 and summary['failed_count']==1
    assert summary['quality_rejected_count']==1 and summary['structure_rejected_count']==0
    assert '1道答案或解析校验不一致' in result_message(result)
    assert '未通过检查或未生成' not in result_message(result)
