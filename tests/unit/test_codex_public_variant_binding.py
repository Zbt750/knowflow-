from copy import deepcopy
from uuid import uuid4
import pytest
from backend.models.learning import KnowledgePoint
from backend.services.question_generation import (
    DifficultyReason, Output,prepare_codex_public_original,current_generation_binding,
    generation_hash,CODEX_PUBLIC_VARIANT_VERSION,
)
from backend.services.auto_question_review import attach_codex_independent_review

def test_codex_variant_binding_preserves_hash_origin_and_personal_guards():
    node=KnowledgePoint(id=uuid4(),code='TEST_FIXTURE.variant.node',name='矩阵的秩',
        subject='考研数学',is_active=True,is_assessable=True,is_reference_only=False)
    node.children=[]
    review=dict(derived_answer='B',method_evidence=[
        {'method':'rank-nullity','result':'TEST_FIXTURE：三列矩阵秩为2，零空间维度为3减2等于1。'},
        {'method':'explicit-vector','result':'TEST_FIXTURE：构造非零核向量且另外两列独立，交叉验证零空间维数1。'}],
        explanation_key_steps=['TEST_FIXTURE：秩加零空间维数等于列数。','TEST_FIXTURE：明确构造非零零向量同时两列独立。'],
        option_truth_table={'A':False,'B':True,'C':False,'D':False})
    q=prepare_codex_public_original(Output(stem='三列矩阵秩为2，其零空间维数为多少？',
        question_type='single_choice',options={'A':'0','B':'1','C':'2','D':'3'},
        correct_answer='B',explanation='秩加零空间维数等于列数，所以3-2=1。',final_value='1'),
        node,request_id='TEST_FIXTURE.variant.binding',**review,
        difficulty_reason={
            'knowledge_depth':'TEST_FIXTURE：结合矩阵秩与零空间维数理解线性映射结构。',
            'reasoning_steps':'TEST_FIXTURE：先应用秩零度关系，再用条件排除其他可能维数。',
            'trap_design':'TEST_FIXTURE：混淆行数与列数会使零空间维数计算方向出错。',
            'application_value':'TEST_FIXTURE：训练将代数条件转化为线性映射维数结论。'})
    config=deepcopy(q.grading_config)
    config['generation'].update(version=CODEX_PUBLIC_VARIANT_VERSION,mode='adapted',
        parent_question_id=str(uuid4()),transformation_summary='TEST_FIXTURE：从判断线性相关改为在明确秩约束下计算核空间维数。')
    q.grading_config=config;q.is_variant=True;q.source_status='traceable'
    attach_codex_independent_review(q,node,**review)
    config=deepcopy(q.grading_config);config['generation']['verified_content_hash']=generation_hash(q);q.grading_config=config
    assert current_generation_binding(q,node)
    q.bank_scope='personal';assert not current_generation_binding(q,node);q.bank_scope='public'
    q.stem+=' 漂移。';assert not current_generation_binding(q,node);q.stem=q.stem[:-4]
    config=deepcopy(q.grading_config);config['generation']['parent_question_id']='invalid';q.grading_config=config
    assert not current_generation_binding(q,node)


def test_difficulty_reason_contract_requires_four_specific_distinct_fields():
    reason={
        'knowledge_depth':'结合矩阵秩与零空间维数的结构关系进行判断。',
        'reasoning_steps':'先确认矩阵列数，再应用秩零度定理计算零空间维数。',
        'trap_design':'把矩阵行数误当作列数会导致零空间维数结论错误。',
        'application_value':'训练将代数条件转化为线性映射的空间维数结论。',
    }
    assert set(DifficultyReason.model_validate(reason).model_dump())==set(reason)
    with pytest.raises(ValueError):
        DifficultyReason.model_validate({**reason,'trap_design':'太短'})
    with pytest.raises(ValueError):
        DifficultyReason.model_validate({**reason,'application_value':reason['knowledge_depth']})
