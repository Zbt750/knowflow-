import pytest
from types import SimpleNamespace as NS
from uuid import UUID
from backend.services.paper_adjustment_chat import (
    _replacement_fill_candidates, _requested_408_topic_scope, _topic_count_batch, parse_command,
)

@pytest.mark.parametrize('text',['先取消这次408替换方案，保留当前正式卷。','请取消本次数学调整方案。','帮我撤回刚才的替换方案，其他不动。'])
def test_scoped_pending_cancellation_precedes_subject_replacement(text):
    assert parse_command(text)['action']=='cancel'

@pytest.mark.parametrize('text',['不要取消这次408替换方案。','能否取消这次408替换方案？','如果取消这次替换方案呢？'])
def test_cancellation_questions_and_denials_preserve_the_draft(text):
    assert parse_command(text)=={'action':'query','text':text,'revoke_proposal':False}


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


def test_whole_paper_topic_count_never_fills_from_unselected_topics():
    selected=[NS(id=i) for i in range(1,7)]
    unselected=NS(id=7)
    pools=[(node,[NS(id=node.id*10+offset,estimated_minutes=offset+1)
        for offset in range(3)]) for node in selected]
    pools.append((unselected,[NS(id=70,estimated_minutes=1),NS(id=71,estimated_minutes=2)]))
    chosen=pools[:6]

    fill=_replacement_fill_candidates(pools,chosen,preserve_replaced_quantity=False)
    assert {question.id//10 for question in fill}==set(range(1,7))
    assert len(fill)==12

    # A scoped course-topic replacement retains its old quantity and may use
    # additional admitted questions from other course topics.
    preserve=_replacement_fill_candidates(pools,chosen,preserve_replaced_quantity=True)
    assert {question.id//10 for question in preserve}==set(range(1,8))


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


def test_batch_chat_resolves_full_topic_name_over_short_parent_alias():
    nodes=[
        NS(id=UUID(int=1),name='磁盘调度'),
        NS(id=UUID(int=2),name='操作系统'),
        NS(id=UUID(int=3),name='操作系统概念与发展'),
    ]
    edits,error=_topic_count_batch(
        '预算90分钟，增加一道磁盘调度的题目，增加一道操作系统概念与发展的题目。',nodes)
    assert error is None
    assert [(node.name,delta) for node,delta in edits]==[
        ('磁盘调度',1),('操作系统概念与发展',1)]


def test_cross_subject_topic_replacement_is_scoped_to_explicit_408_course():
    os_root=NS(id=UUID(int=10),name='操作系统',subject='408',parent_id=None,
        is_active=True,is_assessable=False)
    os_basics=NS(id=UUID(int=11),name='操作系统概念与发展',subject='408',parent_id=os_root.id,
        is_active=True,is_assessable=True)
    os_memory=NS(id=UUID(int=12),name='操作系统内存管理',subject='408',parent_id=os_root.id,
        is_active=True,is_assessable=True)
    ds_root=NS(id=UUID(int=13),name='数据结构',subject='408',parent_id=None,
        is_active=True,is_assessable=False)
    ds_tree=NS(id=UUID(int=14),name='二叉搜索树',subject='408',parent_id=ds_root.id,
        is_active=True,is_assessable=True)
    source_math=NS(id=UUID(int=15),name='洛必达法则',subject='考研数学',parent_id=None,
        is_active=True,is_assessable=True)
    scope,course=_requested_408_topic_scope(
        '把洛必达法则的题目全部换成408操作系统的题目。',
        [os_root,os_basics,os_memory,ds_root,ds_tree,source_math])
    assert course=='操作系统'
    assert scope=={os_root.id,os_basics.id,os_memory.id}
    broad,broad_course=_requested_408_topic_scope('把今天数学题全部换成408。',[os_root,os_basics])
    assert broad is broad_course is None


def test_cross_subject_target_scope_uses_course_after_last_replacement_phrase():
    os_root=NS(id=UUID(int=20),name='操作系统',subject='408',parent_id=None,
        is_active=True,is_assessable=False)
    os_leaf=NS(id=UUID(int=21),name='操作系统概念与发展',subject='408',parent_id=os_root.id,
        is_active=True,is_assessable=True)
    math_leaf=NS(id=UUID(int=22),name='洛必达法则',subject='考研数学',parent_id=None,
        is_active=True,is_assessable=True)
    scope,course=_requested_408_topic_scope(
        '操作系统题目不要动，把洛必达法则换成408操作系统。',[os_root,os_leaf,math_leaf])
    assert course=='操作系统' and scope=={os_root.id,os_leaf.id}


def test_single_math_topic_replacement_does_not_expand_to_the_whole_math_paper():
    from backend.services.paper_adjustment_chat import _is_whole_math_replacement
    assert not _is_whole_math_replacement('把洛必达法则的题目全部换成408操作系统的题目。')
    assert _is_whole_math_replacement('把今天的数学题全部换成408。')
    assert _is_whole_math_replacement('把全部数学内容换成408。')


@pytest.mark.parametrize('text',[
 '给今天的408卷增加两道堆的题、增加两道二叉搜索树的题，其他不变，先给我看待确认方案。',
 '堆增加2道，二叉搜索树增加2道，其他不变，先预览。',
 '堆增加两道、二叉搜索树增加两道。',
])
def test_named_single_character_topic_and_enumeration_batch(text):
    nodes=[NS(id=UUID(int=701),name='堆'),NS(id=UUID(int=702),name='二叉搜索树')]
    edits,error=_topic_count_batch(text,nodes)
    assert error is None,error
    assert [(node.id,delta) for node,delta in edits]==[(nodes[0].id,2),(nodes[1].id,2)]


def test_one_character_topic_does_not_match_unrelated_word():
    nodes=[NS(id=UUID(int=711),name='堆'),NS(id=UUID(int=712),name='二叉搜索树'),NS(id=UUID(int=713),name='洛必达法则')]
    edits,error=_topic_count_batch('一堆资料需要整理，二叉搜索树增加2道，洛必达法则减少1道。',nodes)
    assert error is None
    assert [(node.id,delta) for node,delta in edits]==[(nodes[1].id,2),(nodes[2].id,-1)]


def test_enumeration_inside_displayed_topic_name_is_not_an_operation_boundary():
    nodes=[NS(id=UUID(int=721),name='概念甲、概念乙'),NS(id=UUID(int=722),name='二叉搜索树')]
    edits,error=_topic_count_batch('概念甲、概念乙增加2道、二叉搜索树减少1道。',nodes)
    assert error is None
    assert [(node.id,delta) for node,delta in edits]==[(nodes[0].id,2),(nodes[1].id,-1)]


@pytest.mark.parametrize('text',[
 '取消这次删除方案，保留当前正式卷。',
 '先取消刚才的追加方案，原卷不动。',
 '撤回本次多知识点方案。',
])
def test_cancel_pending_proposal_is_independent_of_operation_type(text):
    assert parse_command(text)['action']=='cancel'

@pytest.mark.parametrize('text',[
 '不要取消这次删除方案。','能不能取消这次删除方案？','如果取消这次删除方案会怎么样？',
])
def test_cancel_pending_proposal_queries_and_denials_do_not_cancel(text):
    assert parse_command(text)['action']=='query'


@pytest.mark.parametrize('message,expected',[
 ('给我生成一道洛必达法则练习题，不加入今日卷。','generation'),
 ('用奶蛙AI给我生成一道行列式的性质练习题，考查三阶可逆矩阵和伴随矩阵的行列式关系，先生成个人参考题，不加入今日卷。','generation'),
 ('不要生成新题，也不要加入今日卷。','qa'),
 ('先不生成洛必达法则题，只看看。','data_query'),
])
def test_generation_consent_is_separate_from_paper_insertion(message,expected):
    from backend.services.assistant_router import route_message
    from backend.schemas.learning_assistant import StudyContext
    route=route_message(message,StudyContext())
    assert route.capability==expected
    if expected!='generation':assert route.write_risk is False
