import json
import pytest
from backend.services.generation_difficulty import normalize_requirement,assess_difficulty,legacy_difficulty
from backend.services.question_generation import generate,Budget


@pytest.mark.parametrize('text,level,change',[
    ('出一道基础题','basic','unspecified'),('出一道中等题','medium','unspecified'),
    ('出一道较难的练习题','hard','unspecified'),('出一道综合挑战题','challenge','unspecified'),
    ('比原题简单一点','basic','easier'),('比原题难一点','hard','harder'),
    ('比原题难很多','challenge','much_harder'),('保持相近难度','basic','similar'),
    ('出一道难度更大一点的类似题','hard','harder'),('不要更难，保持原难度','basic','similar'),
    ('根据当前知识点出一道稍难的极限题','medium','unspecified'),
    ('给我一道稍难一点的练习','medium','unspecified'),
    ('比原题稍难一点','hard','harder'),('不要稍难，保持现有难度','basic','similar'),
    ('中等题。原题：综合应用函数定义','medium','unspecified'),
    ('难很多\n最新出题要求：简单一点','basic','easier'),
])
def test_absolute_and_relative_requirements_are_not_flattened(text,level,change):
    result=normalize_requirement(text)
    assert result.raw_text==text
    assert (result.target_level,result.relative_change)==(level,change)


def test_numeric_only_variant_is_rejected_not_claimed_as_harder():
    requirement=normalize_requirement('比原题难很多')
    summary,issues=assess_difficulty(requirement,None,stem='已知首项为20，公比为1/3，求级数的和。',reference='已知首项为2，公比为1/2，求级数的和。')
    assert issues==['difficulty_numeric_only']
    assert summary['constraint_check']['status']=='conflict'
    assert summary['independent_check']['status']=='not_independently_verified'


def test_unknown_difficulty_remains_unknown_not_independently_verified():
    summary,issues=assess_difficulty(normalize_requirement('比原题更难'),None,stem='设r为参数，讨论两个方法的适用条件。')
    assert not issues and summary['estimated_label']=='未评估'
    assert summary['independent_check']['status']=='not_independently_verified'
    assert '无法确认相对' in summary['notice']


def test_power_change_is_not_mistaken_for_only_larger_numbers():
    summary,issues=assess_difficulty(normalize_requirement('比原题更难'),None,
        stem='求级数sum n^3 x^n的和。',reference='求级数sum n^2 x^n的和。')
    assert not issues
    assert summary['independent_check']['status']=='not_independently_verified'


def test_model_self_rating_cannot_certify_or_overrule_relative_requirement():
    rating={'estimated_level':'hard','relative_change':'easier','reason':'减少了原题所需的逐项求导和条件讨论步骤。','mechanisms':['reasoning_steps']}
    summary,issues=assess_difficulty(normalize_requirement('比原题更难'),rating,stem='新的完整题干。',reference='参考原题。')
    assert 'difficulty_self_assessment_conflict' in issues
    assert '模型自评' in summary['notice']


def test_prompt_and_wire_metadata_keep_quality_payload_separate():
    class Model:
        simulation=True
        def complete(self,messages,**kwargs):
            self.prompt=messages[0]['content'];self.request=json.loads(messages[-1]['content'])
            return json.dumps({'stem':'计算首项为2公比为1/2的等比级数的和。','question_type':'fill_blank','options':None,
                'correct_answer':'4','explanation':'公比绝对值小于1，使用等比级数求和公式2/(1-1/2)=4。','final_value':'4','steps':[],
                'difficulty_assessment':{'estimated_level':'basic','relative_change':'unknown','reason':'只需识别等比级数并使用单一求和公式。','mechanisms':['reasoning_steps']}}),None
    model=Model();requirement=normalize_requirement('出一道基础题')
    output,trace=generate(model,{'node':{'code':'TEST_FIXTURE.series'},'difficulty_requirement':requirement.model_dump()},Budget(max_calls=1),prompt_version='personal-general-authoring-v1')
    assert output.correct_answer=='4' and 'difficulty_assessment' not in output.model_dump()
    assert trace['model_difficulty_assessment']['estimated_level']=='basic'
    assert '不能只把数字变大' in model.prompt and '不能把用户要求直接复制' in model.prompt
