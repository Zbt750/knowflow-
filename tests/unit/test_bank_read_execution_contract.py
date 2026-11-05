from backend.services.assistant_data_queries import bank_preview_count,apply_practice_filters


def test_explicit_bank_quantity_is_not_the_old_single_preview_default():
    for text,count in [('找五道隐函数题',5),('从正式题库找两道填空题，不要加入今日卷',2),('找十一道没做过的题',11)]:
        assert bank_preview_count(text)==count
    assert bank_preview_count('列出可练习的题')==16


def test_difficulty_and_actual_attempt_filter_survive_followup_until_explicit_reset():
    state={}
    apply_practice_filters(state,'找五道中等难度的、我没做过的题')
    assert set(state['difficulties'])=={'medium','improved'} and state['unattempted_only'] is True
    apply_practice_filters(state,'这些里面找两道填空题')
    assert set(state['difficulties'])=={'medium','improved'} and state['unattempted_only'] is True
    apply_practice_filters(state,'不限难度，做过的也可以')
    assert state['difficulties']==[] and state['unattempted_only'] is False


def test_do_not_exclude_attempted_is_not_reversed():
    state={'unattempted_only':True}
    apply_practice_filters(state,'不要排除我做过的题')
    assert state['unattempted_only'] is False


def test_specific_wrong_question_list_does_not_become_global_learning_statistics():
    from backend.services.assistant_router import route_message
    from backend.schemas.learning_assistant import StudyContext
    from backend.services.assistant_data_queries import classify_read_only_data_query
    text='那些题我答错过哪几道？'
    assert classify_read_only_data_query(text)=='history'
    assert route_message(text,StudyContext(surface='chat')).intent=='history'


def test_read_bank_does_not_need_an_extra_do_not_write_clause():
    from backend.services.assistant_router import route_message
    from backend.schemas.learning_assistant import StudyContext
    for text in ('从正式题库找五道隐函数题','从题库找一道洛必达题'):
        result=route_message(text,StudyContext(surface='study'))
        assert result.capability=='data_query' and result.intent=='find' and result.write_risk is False
    result=route_message('从题库找一道洛必达题加入今日卷',StudyContext(surface='study'))
    assert result.capability=='planner'


def test_negative_type_and_difficulty_are_exclusions_not_positive_selections():
    from backend.services.bank_selection_intent import bank_selection_request
    request=bank_selection_request('找两道题，不要填空题，不要难题')
    assert request['question_type'] is None and request['difficulty'] is None
    assert request['excluded_question_types']==['fill_blank'] and request['excluded_difficulties']==['hard']
    state={}
    apply_practice_filters(state,'找两道题，不要填空题，不要难题')
    assert state['excluded_question_types']==['fill_blank'] and 'hard' in state['excluded_difficulties']
    apply_practice_filters(state,'改为填空题，不限难度')
    assert state['excluded_question_types']==[] and state['excluded_difficulties']==[]


def test_negative_preference_does_not_cross_clause_into_positive_requirement():
    from backend.services.bank_selection_intent import bank_selection_request
    request=bank_selection_request('找两道题，不要难题，要基础题')
    assert request['difficulty']=='basic' and request['excluded_difficulties']==['hard']
