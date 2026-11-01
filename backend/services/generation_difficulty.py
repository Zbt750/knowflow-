"""Preserve relative constraints and report only what we can actually check."""
import re
from backend.schemas.generation_difficulty import DifficultyRequirement,ModelDifficultyAssessment

LEVELS = {'basic':'基础','medium':'中等','hard':'较难','challenge':'综合挑战'}
CHANGES = {'unspecified':'未指定相对变化','easier':'比原题简单','much_easier':'比原题明显简单',
    'similar':'与原题难度相近','harder':'比原题更难','much_harder':'比原题难很多','unknown':'无法可靠判断'}
LEGACY_LEVEL = {'basic':'basic','improved':'medium','comprehensive':'challenge'}


def gradient_requested(text):
    text=(text or '').split('最新出题要求：')[-1]
    text=re.split(r'(?:原题|参考题|题目正文)\s*[:：]',text,1)[0]
    if re.search(r'(?:不要|不用|不需要|别).{0,4}(?:梯度|不同难度|由易到难)',text):return False
    return bool(re.search(r'由易到难|从易到难|不同难度|梯度|从基础到(?:困难|综合|难)',text))


def requirement_for_target(body,target):
    """A gradient is a sequence of slot constraints, not one global level."""
    if gradient_requested(body.user_requirement):
        requirement=normalize_requirement('',target.difficulty)
        return requirement.model_copy(update={'raw_text':body.user_requirement or '', 'absolute_explicit':True})
    return body.difficulty_requirement or normalize_requirement(body.user_requirement or '',target.difficulty)


def normalize_requirement(raw='',legacy='basic'):
    # The pasted math problem may itself mention “基础/综合”. Only the user's
    # instruction (and its most recent amendment) defines requested difficulty.
    text = (raw or '').split('最新出题要求：')[-1]
    text = re.split(r'(?:原题|参考题|题目正文)\s*[:：]',text,1)[0]
    change='unspecified'
    if re.search(r'不要.{0,4}(?:更难|稍难|略难)|不(?:要|必).{0,4}提高|相近|相同难度|保持.{0,5}难度|难度不变|差不多',text): change='similar'
    elif re.search(r'简单很多|容易很多|大幅.{0,4}(?:降低|简单)|降低很多',text): change='much_easier'
    elif re.search(r'简单(?:一[点些]|点|些)|更简单|容易(?:一[点些]|点|些)|更容易|降低|调低',text): change='easier'
    elif re.search(r'难很多|难得多|难多了|大幅.{0,4}(?:提高|提升)|提高很多|更有挑战|难度.{0,3}更大.{0,2}很多',text): change='much_harder'
    elif re.search(r'更难|(?<!稍)(?<!略)(?<!微)难(?:一[点些]|点|些)|比.{0,12}难|提高|提升|调高|难度.{0,3}(?:更大|增大|加大)|加大.{0,3}难度',text): change='harder'
    explicit = True
    if re.search(r'综合挑战|综合性|综合题|综合练习|综合难度|挑战级|高难挑战',text): level='challenge'
    elif re.search(r'较难|高难度|困难|难题|难的题',text): level='hard'
    elif change == 'unspecified' and re.search(r'稍难|略难|稍微.{0,3}难|略微.{0,3}难',text): level='medium'
    elif re.search(r'中等|适中|中级',text): level='medium'
    elif re.search(r'基础|入门|简单题|简单的|容易的',text): level='basic'
    else:
        explicit=False
        level=('challenge' if change=='much_harder' else 'hard' if change=='harder' else
               'basic' if change in {'easier','much_easier'} else LEGACY_LEVEL.get(legacy,'basic'))
        if re.search(r'综合|挑战',text) and change=='unspecified': level='challenge';explicit=True
    return DifficultyRequirement(raw_text=(raw or '')[:4000],target_level=level,
                                 relative_change=change,absolute_explicit=explicit)


def legacy_difficulty(requirement):
    return {'basic':'basic','medium':'improved','hard':'improved','challenge':'comprehensive'}[requirement.target_level]


def _numeric_skeleton(text):
    # Deliberately conservative: only prove the same wording with numbers
    # changed. No symbolic equivalence or difficulty inferred from word count.
    stem=re.split(r'\n\s*A[.、．)]',text or '',1)[0]
    return re.sub(r'\d+(?:\.\d+)?','#',re.sub(r'\s+','',stem))


def only_numeric_size_changed(stem,reference):
    # Changing a power or derivative order may genuinely add reasoning steps;
    # that is NOT evidence of a mere coefficient-size substitution. Leave
    # such cases unverified instead of rejecting a valid parameter variation.
    structure = r'\^(?:\{[^{}]{1,40}\}|[+-]?\d+)|第\d+阶|\d+阶导数'
    if re.findall(structure,stem) != re.findall(structure,reference): return False
    return _numeric_skeleton(stem)==_numeric_skeleton(reference)


def assess_difficulty(requirement,model_assessment,*,stem,reference=None):
    model=ModelDifficultyAssessment.model_validate(model_assessment).model_dump() if model_assessment else None
    issues=[]
    if requirement.relative_change!='unspecified' and reference and only_numeric_size_changed(stem,reference):
        issues.append('difficulty_numeric_only')
    if model:
        if requirement.absolute_explicit and model['estimated_level']!='unknown' and model['estimated_level']!=requirement.target_level:
            issues.append('difficulty_self_assessment_conflict')
        relative=model['relative_change']
        allowed={'harder':{'harder','much_harder'},'much_harder':{'much_harder'},
                 'easier':{'easier','much_easier'},'much_easier':{'much_easier'},'similar':{'similar'}}
        if reference and requirement.relative_change in allowed and relative!='unknown' and relative not in allowed[requirement.relative_change]:
            issues.append('difficulty_self_assessment_conflict')
    summary={'requirement':requirement.model_dump(),'target_label':LEVELS[requirement.target_level],
        'target_basis':'explicit' if requirement.absolute_explicit else 'relative_inferred' if requirement.relative_change!='unspecified' else 'request_default',
        'relative_label':CHANGES[requirement.relative_change], 'model_assessment':model,
        'estimated_label':LEVELS.get(model['estimated_level'],'未评估') if model else '未评估',
        'relative_estimate':CHANGES.get(model['relative_change'],'无法可靠判断') if model and reference else '无法可靠判断',
        'constraint_check':{'status':'conflict' if issues else 'no_obvious_conflict','issues':sorted(set(issues))},
        'independent_check':{'status':'not_independently_verified',
            'issues':[], 'reference_available':bool(reference)},
        'notice':'难度来自模型自评，尚无独立难度验证；不代表真实考研难度分布。' if model else
                 '本次未提供可靠的实际难度估计，不能确认已满足目标难度。'}
    if requirement.relative_change!='unspecified' and not reference:
        summary['notice']+=' 未取得可比较原题，无法确认相对难度变化。'
    if requirement.relative_change=='similar' and not requirement.absolute_explicit:
        summary['target_label']='与原题相近（绝对等级未确定）'
    return summary,sorted(set(issues))
