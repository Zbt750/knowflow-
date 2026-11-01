from types import SimpleNamespace
from copy import deepcopy
import pytest
from backend.services.phase45hs_verifiers import problem
from backend.services.answer_grading import grade_final_answer

def q(stem,answer,options=None):
    return SimpleNamespace(stem=stem,correct_answer=answer,options=options,question_type='single_choice' if options else 'fill_blank')

@pytest.mark.parametrize('question',[
    q('空栈,入栈序列a,b,c；依次操作Push、Push、Pop、Push、Pop、Pop,出栈序列为？','b,c,a'),
    q('MTU=1000B,转发总长2100B的IP数据报（首部20B）,尽量大分片。第2片总长度与MF分别为？','A',{'A':'996,1','B':'1000,1','C':'996,0','D':'1000,0'}),
    q('某计算机主存地址为32位,按字节编址；Cache数据区容量为32KB,主存块大小为64B,采用4路组相联映射。Cache中比较器的个数和位数分别为（）。','B',{'A':'4,18','B':'4,19','C':'8,19','D':'4,20'}),
    q('二叉树4个叶权值1,2,3,4,最小带权路径长度WPL为？','19'),
    q('对n个互不相同的符号构造Huffman树,若整棵树共有19个结点,求n。','10'),
    q('字符a…c的码字依次为0,10,11。译码串01011,选结果：','abc'),
    q('1.5的IEEE754单精度浮点数表示为（）。','A',{'A':'3FC00000H','B':'3F800000H','C':'40000000H','D':'BF800000H'}),
])
def test_unseen_parameters_answers_and_counterexamples(question):
    result=problem(question);assert result and result['status']=='PASS',result
    wrong=deepcopy(question);wrong.correct_answer='D' if question.options else '9999'
    assert problem(wrong)['status']!='PASS'
    if question.options:
        ambiguous=deepcopy(question);ambiguous.options['D']=ambiguous.options[question.correct_answer]
        assert problem(ambiguous)['status']=='FAIL'
    extra=deepcopy(question);extra.stem+='还须满足未知条件。'
    assert not problem(extra) or problem(extra)['status']!='PASS'

def test_bad_conditions_are_not_guessed():
    for question in [q('空栈,入栈序列a,b；依次操作Pop、Push,出栈序列为？','a'),
        q('字符a…c的码字依次为0,10,11。译码串01,选结果：','a'),
        q('对n个互不相同的符号构造Huffman树,若整棵树共有20个结点,求n。','10'),
        q('CRC检验通过可以断定传输未发生错误。','1')]:
        assert problem(question)['status']=='UNKNOWN'

def test_all_private_historical_hs_passes_have_counterexamples():
    import json
    from pathlib import Path
    path=Path('storage/quality-audits/phase45hs-20261010/formal-bank-export.json')
    if not path.exists():pytest.skip('Private historical payload unavailable')
    data=json.loads(path.read_text(encoding='utf-8'));tested=0
    for row in data['questions']:
        question=q(row['stem'],row['correct_answer'],row['options'])
        result=problem(question)
        if not result or result['status']!='PASS':continue
        tested+=1;wrong=deepcopy(question);wrong.correct_answer='Z' if question.options else '9999'
        assert problem(wrong)['status']!='PASS'
        extra=deepcopy(question);extra.stem+='附加条件未知。'
        assert not problem(extra) or problem(extra)['status']!='PASS'
    assert tested>=15

@pytest.mark.parametrize('expected,answer,result',[('31e','31*E','right'),('-2*pi','-2π','right'),
    ('31e','31.00001e','wrong'),('31e','x+1','unknown'),('31e','__import__("os")','unknown')])
def test_bounded_constant_actual_grader(expected,answer,result):
    args=dict(question_type='fill_blank',config={'verified':True,'method':'constant_final'},answer=answer,selected_option=None,expected=expected,options=None)
    assert grade_final_answer(**args).result==result
    args['config']['verified']=False
    assert grade_final_answer(**args).result=='unknown'
