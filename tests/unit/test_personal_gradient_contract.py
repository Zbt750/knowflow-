from types import SimpleNamespace as NS
from uuid import uuid4
import pytest

from backend.services.personal_generation_intent import generation_intent
from backend.services import generation_difficulty as difficulty
from backend.schemas.learning_assistant import AssistantRequest
from backend.services.learning_assistant_service import _generation_confirmation_turn


def test_three_gradient_slots_keep_distinct_difficulties_and_no_formal_append():
    node=NS(id=uuid4(),name='洛必达法则',code='synthetic.lhopital')
    db=NS(scalars=lambda query:[node])
    ctx=NS(knowledge_node_ids=[],question_id=None,surface='chat',daily_plan_id=None)
    request=generation_intent(db,'生成三道洛必达法则的练习题，由易到难',ctx,uuid4())
    assert [(t.difficulty,t.count) for t in request.targets]==[('basic',1),('improved',1),('comprehensive',1)]
    assert request.append_to_today is False and request.plan_id is None
    assert [difficulty.requirement_for_target(request,t).target_level for t in request.targets]==['basic','medium','challenge']


def test_negative_gradient_does_not_override_single_level():
    assert not difficulty.gradient_requested('不要梯度，全部生成基础题')


def test_explicit_multi_knowledge_point_allocations_keep_each_requested_count():
    lhopital=NS(id=uuid4(),name='洛必达法则',code='synthetic.lhopital',is_active=True,is_assessable=True)
    implicit=NS(id=uuid4(),name='隐函数求导',code='synthetic.implicit_derivative',is_active=True,is_assessable=True)
    db=NS(scalars=lambda query:[lhopital,implicit])
    ctx=NS(knowledge_node_ids=[],question_id=None,surface='chat',daily_plan_id=None)

    request=generation_intent(db,'给我生成三道洛必达法则、两道隐函数练习题',ctx,uuid4())

    assert [(t.kp_id,t.count) for t in request.targets]==[(lhopital.id,3),(implicit.id,2)]
    assert sum(t.count for t in request.targets)==5
    assert request.append_to_today is False


def test_each_current_knowledge_point_uses_only_validated_context_scope():
    lhopital=NS(id=uuid4(),name='洛必达法则',code='synthetic.lhopital',is_active=True,is_assessable=True)
    implicit=NS(id=uuid4(),name='隐函数求导',code='synthetic.implicit_derivative',is_active=True,is_assessable=True)
    unrelated=NS(id=uuid4(),name='行列式的性质',code='synthetic.determinant',is_active=True,is_assessable=True)
    ctx=NS(knowledge_node_ids=[lhopital.id,implicit.id],question_id=None,surface='chat',daily_plan_id=None)
    db=NS(scalars=lambda query:[lhopital,implicit,unrelated])

    request=generation_intent(db,'每个知识点各生成一道填空题',ctx,uuid4())

    assert [(target.kp_id,target.count,target.question_type) for target in request.targets]==[
        (lhopital.id,1,'fill_blank'),(implicit.id,1,'fill_blank')]
    assert all(target.kp_id!=unrelated.id for target in request.targets)

    from backend.errors import AppError
    one_node_ctx=NS(knowledge_node_ids=[lhopital.id],question_id=None,surface='chat',daily_plan_id=None)
    with pytest.raises(AppError,match='personal_generation_scope_required'):
        generation_intent(db,'每个知识点各生成一道填空题',one_node_ctx,uuid4())


def test_per_difficulty_counts_create_real_personal_generation_slots():
    node=NS(id=uuid4(),name='洛必达法则',code='synthetic.lhopital',is_active=True,is_assessable=True)
    db=NS(scalars=lambda query:[node])
    ctx=NS(knowledge_node_ids=[],question_id=None,surface='chat',daily_plan_id=None)

    request=generation_intent(db,'生成两道基础、两道中等、一道困难的洛必达法则练习题',ctx,uuid4())

    assert [(t.difficulty,t.count) for t in request.targets]==[
        ('basic',2),('improved',2),('comprehensive',1)]
    assert sum(t.count for t in request.targets)==5
    assert all(t.kp_id==node.id for t in request.targets)


def test_multi_knowledge_point_generation_rejects_unresolved_or_over_limit_allocations():
    first=NS(id=uuid4(),name='洛必达法则',code='synthetic.lhopital',is_active=True,is_assessable=True)
    second=NS(id=uuid4(),name='隐函数求导',code='synthetic.implicit_derivative',is_active=True,is_assessable=True)
    third=NS(id=uuid4(),name='隐函数积分',code='synthetic.implicit_integral',is_active=True,is_assessable=True)
    ctx=NS(knowledge_node_ids=[],question_id=None,surface='chat',daily_plan_id=None)
    from backend.errors import AppError

    with pytest.raises(AppError,match='validation_failed'):
        generation_intent(NS(scalars=lambda query:[first,second]),
            '给我生成四道洛必达法则、两道隐函数练习题',ctx,uuid4())
    with pytest.raises(AppError,match='personal_generation_scope_required'):
        generation_intent(NS(scalars=lambda query:[first,second,third]),
            '给我生成两道隐函数练习题',ctx,uuid4())


def test_multi_target_confirmation_must_match_server_issued_card_and_session():
    kp_a,kp_b=uuid4(),uuid4()
    sid,card_id=uuid4(),uuid4()
    allocations=[
        {'kp_id':str(kp_a),'question_type':'single_choice','count':3,'difficulty':'basic'},
        {'kp_id':str(kp_b),'question_type':'fill_blank','count':2,'difficulty':'improved'},
    ]
    card={'question':'给我生成三道洛必达法则、两道隐函数填空题','proposed_targets':[
        {**allocation,'name':name} for allocation,name in zip(allocations,['洛必达法则','隐函数求导'])],
        'nodes':[{'kp_id':str(kp_a)},{'kp_id':str(kp_b)}]}
    candidate=NS(id=card_id,session_id=sid,role='assistant',status='completed',metadata_={
        'personal_generation_confirmation':card,'personal_generation_mode':'ai_generated',
        'study_context':{'knowledge_node_ids':[str(kp_a),str(kp_b)]}})
    db=NS(get=lambda model,ident:candidate if ident==card_id else None)
    ctx=NS(model_dump=lambda **kwargs:{'knowledge_node_ids':[str(kp_a),str(kp_b)]})
    body=AssistantRequest(question=card['question'],personal_generation_mode='ai_generated',
        personal_generation_confirmed_targets=allocations,
        personal_generation_confirmation_message_id=card_id)

    assert _generation_confirmation_turn(db,sid,body,ctx) is candidate

    altered=AssistantRequest(question=card['question'],personal_generation_mode='ai_generated',
        personal_generation_confirmed_targets=[allocations[0],{**allocations[1],'count':1}],
        personal_generation_confirmation_message_id=card_id)
    from backend.errors import AppError
    with pytest.raises(AppError) as exc:
        _generation_confirmation_turn(db,sid,altered,ctx)
    assert exc.value.code=='personal_generation_confirmation_invalid'

    # Legacy single-node confirmations remain valid only for single-node
    # cards. A multi-node allocation cannot be partially accepted by selecting
    # one node from its display list.
    partial=AssistantRequest(question=card['question'],personal_generation_mode='ai_generated',
        personal_generation_confirmed_kp_id=kp_a,
        personal_generation_confirmation_message_id=card_id)
    with pytest.raises(AppError) as exc:
        _generation_confirmation_turn(db,sid,partial,ctx)
    assert exc.value.code=='personal_generation_confirmation_invalid'
