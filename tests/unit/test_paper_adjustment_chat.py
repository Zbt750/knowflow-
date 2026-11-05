import pytest
from backend.services.paper_adjustment_chat import parse_command


@pytest.mark.parametrize('text',[
    '不要删除第1题','能不能减少一道题？','如果换成408呢','先不要替换',
    '要不要删除第2题','等我确认以后再换掉',
])
def test_questions_negations_conditions_do_not_authorize_execution(text):
    assert parse_command(text)['action']=='query'


@pytest.mark.parametrize('text',[
    '先不要删除第1题','暂时不加入洛必达法则题目','别替换第2题',
])
def test_explicit_withdrawal_is_distinguished_from_a_question(text):
    command=parse_command(text)
    assert command['action']=='query' and command['revoke_proposal'] is True


@pytest.mark.parametrize('text,count',[
    ('减少一道洛必达法则题目',1),('减少两道洛必达法则题目',2),
    ('改成减少1道',1),
    ('减少两道洛必达法则题目，减少1道吧',1),
])
def test_count_and_correction_are_preserved(text,count):
    command=parse_command(text)
    assert command['action']=='remove' and command['count']==count


def test_actual_question_number_is_distinct_from_count():
    command=parse_command('删除第3题')
    assert command['number']==3 and command['count']==1


def test_confirmation_is_explicit_and_viewed_requires_distinct_phrase():
    assert parse_command('确认调整')['viewed'] is False
    assert parse_command('确认移除已浏览题目')['viewed'] is True
    assert parse_command('我想先看看') is None
    assert parse_command('取消本次调整')['action']=='cancel'


def test_easy_request_requires_reliable_difficulty_handling():
    assert parse_command('减少一道比较简单的题')['easy'] is True


def test_unparsed_chinese_ordinal_is_clarified_not_replaced_by_previous_target():
    assert parse_command('删除第十一题')['action']=='clarify'
    assert parse_command('减少两题洛必达法则')['count']==2


def test_append_only_budget_and_topic_replacement_parse_as_distinct_operations():
    added=parse_command('给我增加一道洛必达法则的题目。')
    assert added['action']=='add' and added['count']==1
    plan=parse_command('把今天数学题全部换成408，安排6个知识点，预算60分钟。')
    assert plan['action']=='replace' and plan['topic_count']==6
    assert plan['budget_minutes']==60
    assert plan['all_topic'] is True


def test_whole_topic_and_per_topic_edits_are_explicit():
    whole=parse_command('删除洛必达法则的全部题目')
    assert whole['action']=='remove' and whole['all_topic'] is True
    each=parse_command('分别减少一道洛必达法则和隐函数求导题目')
    assert each['each_topic'] is True and each['count']==1


@pytest.mark.parametrize('text',[
    '我真正不会的是等价无穷小替换，洛必达我会用。',
    '你把我的薄弱点记错了，我不会等价无穷小替换。',
    '给我讲讲等价无穷小替换。',
])
def test_topic_name_does_not_become_a_paper_edit(text):
    assert parse_command(text) is None


def test_read_only_budget_advice_does_not_fall_through_as_a_remove_command():
    assert parse_command('根据最近错题和薄弱点，给我90分钟数学二整体复习建议，不创建计划') is None
    assert parse_command('减少一道洛必达法则题，但不要加入今日卷')['action']=='query'
