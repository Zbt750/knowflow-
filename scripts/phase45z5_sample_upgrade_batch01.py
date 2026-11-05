"""Versioned content upgrades of frozen sample items; no new question identities."""
from __future__ import annotations
import argparse
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
from uuid import UUID

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session
from scripts.phase45z5_original_batch02 import item
from scripts.phase45z5_original_batch01 import table_fingerprint, policy_rule_fingerprint
from backend.models.learning import Question, QuestionAttempt, LearningEvent, KpState
from backend.services.auto_question_review import (current_auto_review, question_snapshot_payload,
    question_snapshot_sha256, revoke_auto_qualification, attach_codex_independent_review,
    assess_auto_qualification, qualify_public_question)
from backend.services.question_generation import (generation_hash, DifficultyReason,
    CODEX_PUBLIC_ORIGINAL_VERSION)
from backend.services.auto_question_review import CODEX_REVIEW_VERSION
from backend.services.answer_grading import grade_final_answer

OUT=ROOT/'storage/quality-audits/phase45z5-20261013/sample-upgrades/batch01'
BACKUP=ROOT/'storage/quality-audits/phase45z5-20261013/originals/batch05/post-batch05-corrected.dump'
BACKUP_SHA='38FCA172E995E307216447DDF69261F41EAC8922072BF94808B2322337D1BB0C'

def specs():
    rows=[
        ('c1e1bbe2-1fdb-5693-b489-32942fec1e57',item('polar-moment','math.exam.609e58acbace','B',
            '区域D={(x,y):x²+y²≤2x，y≥0}。二重积分∬_D(x²+y²)dA等于（ ）。',
            {'A':'π/2','B':'3π/4','C':'π','D':'3π/2'},
            '极坐标下r²≤2r cosθ，结合y≥0得0≤θ≤π/2、0≤r≤2cosθ。积分为∫₀^(π/2)∫₀^(2cosθ)r³drdθ=4∫₀^(π/2)cos⁴θdθ=3π/4。另令x=1+u，D变为上半单位圆，被积函数为1+2u+u²+y²；奇函数项积分为0，常数项积分π/2，径向二次项π/4，结果一致。',
            [('polar_domain_and_moment','极坐标区域由0≤r≤2cosθ、0≤θ≤π/2确定，径向积分后得4∫cos⁴θ=3π/4。'),('shift_and_symmetry','平移到上半单位圆后，常数项贡献π/2，关于u的奇项为0，平方半径项贡献π/4。')],
            [('domain','圆不是以原点为心，必须由r²≤2r cosθ确定角度及上界。'),('integral','包含Jacobian r，径向积分为4cos⁴θ；角积分为3π/4。')],
            {'A':False,'B':True,'C':False,'D':False},
            ('需要同时确定非同心圆的极坐标区域、Jacobian和四次余弦积分。','先分析角度范围与径向上界，再计算二阶面积矩并用平移对称性复核。','把圆误看成原点半径2圆或漏掉Jacobian都会改变积分值。','训练积分区域变换、面积矩计算及对称性校核的综合使用。'),['极坐标区域','积分变量变换','对称性'],difficulty='advanced')),
        ('95aaa417-4da8-5879-8148-22dc5a172b6b',item('dfs-return-order','cs408.ds.topic.2067aabae2b5','A',
            '无向图顶点A、B、C、D、E，边为AB、AC、BD、DC、CE。从A递归DFS，每个顶点按字母序检查邻居；首次进入顶点时记发现，返回调用者时记完成。发现序列和完成序列分别为（ ）。',
            {'A':'A B D C E；E C D B A','B':'A B D C E；D B E C A','C':'A B C D E；E D C B A','D':'A C E D B；B D E C A'},
            'A先访问B，B的未访问邻居D被递归访问，D再访问C，C最后访问E；已访问邻居不重新递归。E无未访问邻居先返回，随后C、D、B、A依次返回。因此发现ABDCE，完成ECDBA。递归活动栈最长为A→B→D→C→E。',
            [('recursive_adjacency_trace','按字母序邻接表递归，访问路径为A-B-D-C-E，遇到已访问邻居时跳过。'),('explicit_stack_completion_check','活动栈从A增长至ABDCE，完成时依次弹出E、C、D、B、A。')],
            [('discovery','邻接检查顺序约束确定发现次序A、B、D、C、E。'),('finish','各层均无其他未访问邻居，按递归返回逆序完成E、C、D、B、A。')],
            {'A':True,'B':False,'C':False,'D':False},
            ('需要用邻接次序、访问标记和递归返回区分DFS的两种事件顺序。','逐顶点递归进入，跳过已访问邻居，待所有邻居处理完才记录完成。','把发现顺序当作完成顺序或忘记图中的回边访问标记都会选错。','将DFS调用栈保存路径的知识运用于图中的真实状态推演。'),['DFS轨迹','递归调用栈','完成次序'])),
        ('4017027e-d5ca-582d-898c-1948bd7373a8',item('zero-square-integral','math.exam.4ea6e9d4fae7','D',
            '连续函数f定义在单位正方形D=[0,1]²上，且∬_D[f(x,y)−x−y]²dA=0。则∬_D f(x,y)dA及f的确定性为（ ）。',
            {'A':'0；f不唯一','B':'1；f仅几乎处处等于x+y','C':'2；f处处等于x+y','D':'1；f处处等于x+y'},
            '平方项连续且非负，若任一点非零，连续性使该点附近与正方形相交的正面积区域内平方项有正下界，积分将严格正，矛盾。因此f处处等于x+y。积分分解为∫₀¹∫₀¹x dydx+∫₀¹∫₀¹y dydx=1/2+1/2=1。连续性把几乎处处的结论加强为处处。',
            [('continuity_positive_neighborhood','连续非负函数积分为0，任一正值点将产生有正面积且正下界的邻域贡献，故平方项处处为0。'),('separated_square_integral','由f=x+y，分别积分两个坐标函数各得1/2，总积分为1。')],
            [('identity','平方项在整个闭区域连续，积分零迫使f(x,y)=x+y处处成立。'),('value','对x项及y项分别在单位正方形积分，各为1/2，合计1。')],
            {'A':False,'B':False,'C':False,'D':True},
            ('需要把非负连续函数零积分性质用于平方差，再计算由此确定的函数积分。','用反证法确定函数恒等式，再应用二重积分的线性性分拆求值。','忽略连续性只能得到几乎处处结论；不能因平方差积分零误认为f积分零。','训练二重积分性质与函数确定性及后续精确计算之间的联系。'),['连续非负函数','零积分性质','二重积分线性性'])),
        ('a642f4d0-bc86-5e62-b78b-bf9226584e57',item('tcp-dual-window-bottleneck','cs408.cn.topic.8679c379d738','C',
            'TCP无丢包且忽略协议头，RTT为100ms，MSS=1460B，cwnd=20 MSS，rwnd=64000B，链路8Mbit/s。只考虑窗口与链路约束，最大长期吞吐及能否仅增大rwnd达到链路速率为（ ）。',
            {'A':'5.12Mbit/s；可以','B':'8Mbit/s；可以','C':'2.336Mbit/s；不能','D':'2.336Mbit/s；可以'},
            '有效发送窗口为min(20×1460,64000)=29200B，窗口约束吞吐为29200×8/0.1=2.336Mbit/s，小于链路8Mbit/s。链路带宽时延积为8×10⁶×0.1/8=100000B。增大rwnd不会消除当前29200B的cwnd限制；达到链路速率还需cwnd至少100000B。',
            [('effective_window_and_rate','有效窗口取拥塞窗口与接收窗口最小值29200B，每RTT传一窗给出2.336Mbit/s。'),('bandwidth_delay_product','链路满速需要100000B飞行数据；仅增加接收窗口不能改变不足的拥塞窗口。')],
            [('window_minimum','20×1460=29200小于64000，发送窗口受cwnd限制。'),('saturation_requirement','链路BDP为100000B，增加rwnd后cwnd仍29200B，不能满速。')],
            {'A':False,'B':False,'C':True,'D':False},
            ('需区分拥塞窗口、接收窗口及链路带宽三个吞吐约束。','先取有效窗口求速率，再算带宽时延积分析单一窗口调整是否足够。','将rwnd单独用于吞吐公式会高估速率，且窗口增大不等于消除全部瓶颈。','训练TCP可靠传输中多约束吞吐计算和瓶颈改善判断。'),['TCP窗口','带宽时延积','吞吐瓶颈'])),
        ('b221a9a1-b46b-5c32-a7cb-a786690c1fda',item('two-dimensional-parity-ambiguity','cs408.co.topic.e2880988de52','B',
            '3×3数据位矩阵采用行、列偶校验，校验位本身保证无错。接收端发现第1、3行校验失败，第1、3列校验失败，其余通过。仅依据该综合症，最少数据位错误数及能否唯一定位所有错误为（ ）。',
            {'A':'1；可以','B':'2；不能','C':'4；可以','D':'4；不能'},
            '每个错误位改变其所在一行与一列的奇偶性；两个失败行要求至少两个数据位错误。位(1,1)、(3,3)同时翻转即可产生该综合症，达到下界2。位(1,3)、(3,1)翻转也产生同一综合症，故不能唯一定位全部错误；也不能由综合症断言实际恰有2位错。',
            [('syndrome_lower_bound','两个不同行校验失败，每行至少一个错误位，故错误位数至少2。'),('two_distinct_error_constructions','对角两位(1,1)(3,3)与交叉两位(1,3)(3,1)均产生相同失败行列，证明下界可达且定位不唯一。')],
            [('minimum','每位最多影响一个失败行，至少2位；两对角位置翻转满足综合症。'),('ambiguity','交叉位置翻转产生完全相同的行列校验综合症，无法唯一定位。')],
            {'A':False,'B':True,'C':False,'D':False},
            ('需用行列奇偶综合症建立错误数下界，并构造两种不同错误图样证明定位歧义。','先用失败行计数求下界，再逐行逐列检验两个可行的两位错误图样。','两行两列失败并不必然意味着四位错误；最少错误数不等于实际错误数。','训练校验码检测能力、定位能力和综合症信息不足的区分。'),['二维奇偶校验','错误综合症','定位歧义'])),
        ('e4f73fa0-9792-5b70-8a6e-e3b8c45d0775',item('cancellation-equivalent-order','math.calculus.limit.infinitesimal','A',
            '求lim(x→0)[sin x−x+x³/6]/[x³(1−cos x)]。（ ）',
            {'A':'1/60','B':'1/120','C':'−1/60','D':'0'},
            '分子前三阶抵消，sin x=x−x³/6+x⁵/120+o(x⁵)，故分子为x⁵/120+o(x⁵)。分母中1−cos x=x²/2+o(x²)，乘x³得到x⁵/2+o(x⁵)，极限为(1/120)/(1/2)=1/60。不能在相减抵消前仅用sin x∼x。',
            [('taylor_cancellation','正弦展开到五阶后低阶项抵消，分子系数1/120；分母五阶系数1/2。'),('coefficient_ratio_check','独立比较首个非零同阶系数，并验证两侧x均不影响商极限1/60。')],
            [('numerator_order','分子经低阶项消去后为x⁵/120+o(x⁵)，必须保留五阶。'),('denominator_order','分母为x⁵/2+o(x⁵)，系数相除得1/60。')],
            {'A':True,'B':False,'C':False,'D':False},
            ('需要识别减法中的阶次抵消并选择足够高阶展开，不能直接替换首阶等价无穷小。','先找到分子首个非零五阶项，再用分母等价式对齐阶次求比。','sin x直接替换为x会丢失决定极限的五阶项；余弦系数1/2不能漏掉。','训练等价无穷小适用边界与高阶Taylor展开的正确选择。'),['等价无穷小','高阶抵消','Taylor展开'])),
    ]
    return [{'id':qid,**data} for qid,data in rows]

def run(db, apply):
    identity=db.execute(text('SELECT current_database(),inet_server_port(),system_identifier FROM pg_control_system()')).one()
    if tuple(map(str,identity))!=('phase45z5_work_20261013_test','59227','7694698872540080852'):raise ValueError('database_identity_mismatch')
    protected={m.__tablename__:table_fingerprint(db,m) for m in (QuestionAttempt,LearningEvent,KpState)}
    rules=policy_rule_fingerprint(db)
    preview_path=OUT/'preview.json'
    preview=json.loads(preview_path.read_text(encoding='utf-8')) if apply else None
    results=[]
    for spec in specs():
        with db.begin_nested():
            q=db.scalar(select(Question).where(Question.id==UUID(spec['id'])).with_for_update())
            node=q.kp;old=current_auto_review(q,node);before=question_snapshot_sha256(q)
            if q.bank_scope!='public' or q.generation_batch_id or node.code!=spec['node'] or old is None:raise ValueError('scope_or_current_review_mismatch')
            if q.answer_verification_event_id or db.scalar(select(QuestionAttempt.id).where(QuestionAttempt.question_id==q.id).limit(1)):raise ValueError('history_requires_separate_flow')
            if apply and before!=next(x['before_snapshot'] for x in preview['results'] if x['id']==spec['id']):raise ValueError('snapshot_changed')
            payload=question_snapshot_payload(q)
            revoke_auto_qualification(db,question_id=q.id,expected_event_id=old.id,expected_snapshot_sha256=before,idempotency_key='z5-sample-upgrade01:'+spec['id']+':revoke:'+before)
            for field in ('question_type','stem','options','correct_answer','explanation'):setattr(q,field,deepcopy(getattr(spec['output'],field)))
            q.difficulty=spec['difficulty'];q.skill_tags=spec['tags'];q.question_role='comprehensive'
            config=deepcopy(q.grading_config);config.pop('codex_independent_review',None)
            config.setdefault('content_revisions',[]).append({'version':'phase45z5-sample-upgrade-v1','before':payload,'before_snapshot_sha256':before,'reason':'Substantive replacement of confirmed shallow sample content within the same node.','at':datetime.now(timezone.utc).isoformat(),'human_verified':False})
            # A substantive rewrite invalidates the old verifier-family binding.
            # Bind the new content to the existing Codex offline review path so
            # the current qualification service can assess it from fresh evidence.
            config['generation']={
                'version':CODEX_PUBLIC_ORIGINAL_VERSION,'mode':'original',
                'authoring_mode':'codex_offline','model':'codex_offline_authoring',
                'model_calls':0,'real_model_called':False,
                'prompt_version':CODEX_PUBLIC_ORIGINAL_VERSION,
                'verifier_version':CODEX_REVIEW_VERSION,
                'family':'codex_independent_content_review','node_code':node.code,
                'request_id':'phase45z5-sample-upgrade:'+spec['id']+':'+before,
                'parent_question_id':None,
                'difficulty_reason':DifficultyReason.model_validate(spec['reason']).model_dump(),
                'difficulty_reason_version':'exam-difficulty-reason-v1'}
            config.update(verified=False,method=None,practice_method='single_choice',generated_practice_method='single_choice')
            q.grading_config=config
            attach_codex_independent_review(q,node,derived_answer=spec['answer'],method_evidence=spec['methods'],explanation_key_steps=spec['steps'],option_truth_table=spec['truth'])
            config=deepcopy(q.grading_config);config['generation']['verified_content_hash']=generation_hash(q);q.grading_config=config;db.flush()
            assessment=assess_auto_qualification(db,q,node,all_questions=list(db.scalars(select(Question).where(Question.bank_scope=='public'))))
            if assessment.get('status')!='AUTO_VERIFIED':
                stages=assessment.get('stages',{})
                failed={k:v for k,v in stages.items() if not isinstance(v,dict) or v.get('status')!='PASS'}
                raise ValueError('quality_gate:'+spec['id']+':'+json.dumps(
                    {'status':assessment.get('status'),'failed_stages':failed,
                     'assessment':assessment if not stages else None,
                     'guard_state':{'question_active':q.is_active,'question_hidden':getattr(q,'is_hidden',None),
                         'node_active':node.is_active,'node_assessable':node.is_assessable,
                         'node_is_reference_only':node.is_reference_only,'node_has_children':bool(node.children),
                         'node_matches_question':node.id==q.kp_id}},
                    ensure_ascii=False,default=str))
            event,qualification=qualify_public_question(db,question_id=q.id,node_id=node.id,expected_snapshot_sha256=question_snapshot_sha256(q),idempotency_key='z5-sample-upgrade01:'+spec['id']+':'+question_snapshot_sha256(q))
            cases={label:grade_final_answer(question_type=q.question_type,config=q.grading_config,answer=None,selected_option=label,expected=q.correct_answer,options=q.options).result for label in (*q.options,'','Z')}
            if any(cases[x]!=('right' if x==q.correct_answer else 'wrong') for x in q.options) or cases['']!='unknown' or cases['Z']!='unknown':raise ValueError('grader_failed')
            results.append({'id':spec['id'],'node':node.code,'before_snapshot':before,'after_snapshot':question_snapshot_sha256(q),'new_event':str(event.id),'grader_cases':cases,'qualification':qualification['status']})
    if protected!={m.__tablename__:table_fingerprint(db,m) for m in (QuestionAttempt,LearningEvent,KpState)} or rules!=policy_rule_fingerprint(db):raise ValueError('protected_history_changed')
    return {'status':'APPLIED' if apply else 'DRY_RUN_ROLLED_BACK','results':results,'protected_history':protected,'policy_rule_fingerprint':rules,'paid_calls':0}

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--apply',action='store_true');args=parser.parse_args()
    if hashlib.sha256(BACKUP.read_bytes()).hexdigest().upper()!=BACKUP_SHA:raise SystemExit('backup_hash_mismatch')
    engine=create_engine('postgresql+psycopg://postgres@127.0.0.1:59227/phase45z5_work_20261013_test')
    try:
        with Session(engine,expire_on_commit=False) as db:
            report=run(db,args.apply)
            db.commit() if args.apply else db.rollback()
        OUT.mkdir(parents=True,exist_ok=True);path=OUT/('checkpoint.json' if args.apply else 'preview.json')
        if path.exists():raise SystemExit('refusing_existing_report')
        path.write_text(json.dumps(report,ensure_ascii=False,indent=2,default=str),encoding='utf-8')
        print(json.dumps({'status':report['status'],'upgraded':len(report['results'])}))
    finally:engine.dispose()
