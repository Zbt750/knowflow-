import json
from uuid import UUID
import pytest
from sqlalchemy import select,func
from backend.models.learning import Question,QuestionVersion,DailyPlan,PracticeItem
from backend.schemas.generation_difficulty import DifficultyRequirement
from backend.services.personal_question_service import run_generation,bank_rows
from backend.services.generation_difficulty import normalize_requirement,legacy_difficulty
from tests.integration.test_personal_general_generation import general_bank,GeneralModel,request,NOW


class DifficultyModel(GeneralModel):
    def __init__(self,estimated,relative='unknown',numeric_only=False):
        super().__init__();self.estimated=estimated;self.relative=relative;self.numeric_only=numeric_only
    def complete(self,messages,**kwargs):
        raw,usage=super().complete(messages,**kwargs);data=json.loads(raw)
        if self.numeric_only:data['stem']='已知等比级数首项为20、公比为参数r，说明其收敛条件，并计算r=1/2时的和。'
        data['difficulty_assessment']={'estimated_level':self.estimated,'relative_change':self.relative,
            'reason':'结合收敛条件讨论和求和公式两步计算，比仅套公式多一步条件分析。',
            'mechanisms':['reasoning_steps','method_combination']}
        return json.dumps(data,ensure_ascii=False),usage


@pytest.mark.parametrize('text,level,relative',[
    ('基础题','basic','unknown'),('中等题','medium','unknown'),('较难题','hard','unknown'),('综合挑战题','challenge','unknown'),
    ('比原题简单一点','basic','easier'),('比原题难一点','hard','harder'),
    ('比原题难很多','challenge','much_harder'),('保持相近难度','medium','similar'),
])
def test_difficulty_survives_request_gate_save_version_and_preview(general_bank,text,level,relative):
    factory,kp=general_bank;body=request(kp,'calculation')
    body.difficulty_requirement=normalize_requirement(text)
    body.targets[0].difficulty=legacy_difficulty(body.difficulty_requirement)
    body.user_requirement=text
    if relative!='unknown':body.reference_text='当|x|<1时，求级数sum nx^n的和。'
    model=DifficultyModel(level,relative)
    result=run_generation(factory,body,model,now=NOW)
    assert len(result['question_ids'])==1,result
    qid=result['question_ids'][0];summary=result['difficulty_summaries'][qid]
    assert summary['requirement']['raw_text']==text
    assert summary['model_assessment']['estimated_level']==level
    assert summary['estimated_label']=={'basic':'基础','medium':'中等','hard':'较难','challenge':'综合挑战'}[level]
    assert summary['relative_label']=={'unknown':'未指定相对变化','easier':'比原题简单','harder':'比原题更难',
        'much_harder':'比原题难很多','similar':'与原题难度相近'}[relative]
    assert summary['independent_check']['status']=='not_independently_verified'
    assert model.requests[0]['difficulty_requirement']['relative_change']==body.difficulty_requirement.relative_change
    assert model.requests[0]['user_requirement']==text
    with factory() as db:
        q=db.get(Question,UUID(qid));version=db.get(QuestionVersion,q.current_version_id)
        assert q.grading_config['generation']['difficulty_summary']==summary
        assert version.grading_config['generation']['difficulty_summary']==summary
        assert bank_rows(db)['items'][0]['difficulty_summary']==summary
        for table in (DailyPlan,PracticeItem):assert db.scalar(select(func.count()).select_from(table))==0


@pytest.mark.parametrize('fault',['opposite_relative','wrong_absolute','numeric_only'])
def test_obvious_difficulty_conflict_cannot_save_or_create_paper(general_bank,fault):
    factory,kp=general_bank;body=request(kp,'calculation')
    body.user_requirement='出较难题' if fault=='wrong_absolute' else '比原题难很多'
    body.difficulty_requirement=normalize_requirement(body.user_requirement)
    body.reference_text='已知等比级数首项为2、公比为参数r，说明其收敛条件，并计算r=1/2时的和。'
    model=DifficultyModel('basic' if fault=='wrong_absolute' else 'challenge',
        'easier' if fault=='opposite_relative' else 'much_harder',numeric_only=fault=='numeric_only')
    result=run_generation(factory,body,model,now=NOW)
    assert not result['question_ids'] and model.calls==1,result
    assert result['diagnostics'][0]['code']=='personal_generation_difficulty_mismatch'
    assert result['failures'][0]['review_status']=='INSUFFICIENT_EVIDENCE'
    with factory() as db:
        for table in (Question,QuestionVersion,DailyPlan,PracticeItem):assert db.scalar(select(func.count()).select_from(table))==0


def test_stale_client_level_cannot_override_original_relative_request(general_bank):
    factory,kp=general_bank;body=request(kp,'calculation')
    body.targets[0].difficulty='basic'
    body.difficulty_requirement=DifficultyRequirement(raw_text='比原题难很多',target_level='basic')
    body.reference_text='当|x|<1时，求级数sum nx^n的和。'
    model=DifficultyModel('basic','easier')
    result=run_generation(factory,body,model,now=NOW)
    assert not result['question_ids']
    assert model.requests[0]['difficulty']=='comprehensive'
    assert model.requests[0]['difficulty_requirement']['relative_change']=='much_harder'
    assert body.targets[0].difficulty=='basic'  # caller was not mutated
