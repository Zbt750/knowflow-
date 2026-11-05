"""Build and exercise a small, isolated Math II/408 public-foundation pilot.

No paid model, formal development-database writes, policy changes, or human
verification are performed. Full candidate text is kept only under ignored
storage/quality-audits.
"""
from __future__ import annotations

import argparse
from fractions import Fraction
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sqlalchemy import select, text
from sqlalchemy.engine import make_url

from backend.config import get_settings
from backend.db import create_db_engine, create_session_factory
from backend.models.learning import KnowledgePoint, KpMasteryPolicy, Question
from backend.services.golden_learning_slice import digest
from backend.services.question_generation import (
    Output, assess_output, current_generation_binding, promote,
    GENERATION_VERSION,
)
from backend.services.question_eligibility import question_eligibility
from backend.services.question_quality import duplicates, grader_checks, audit_teaching_question
from backend.services.quality_verifiers import verify_problem, VERSION as VERIFIER_VERSION
from backend.services.question_production_pipeline import validate_question_content
from backend.services.question_attestation import has_current_source_attestation, question_content_sha256
from scripts.audit_question_quality import json_input, safe_output
from scripts.review_golden_slice import fingerprints
from scripts.run_question_repair_pilot import (
    isolated_factory, clone_inventory, business_check,
)


NODES = [
    {"code":"math.exam.de439863790e", "target":10, "core":True},
    {"code":"math.exam.c431f98f817c", "target":10, "core":True},
    {"code":"math.exam.c5c672022b7f", "target":10, "core":True},
    {"code":"math.exam.fd2f9e3739d9", "target":10, "core":True},
    {"code":"math.exam.f4e5ed0360ea", "target":8, "core":False},
    {"code":"math.exam.c106a40cda48", "target":8, "core":False},
    {"code":"cs408.co.topic.324b03e7b481", "target":10, "core":True},
    {"code":"cs408.ds.topic.1efaf3d00b50", "target":10, "core":True},
    {"code":"cs408.ds.topic.8b04b55a0408", "target":8, "core":False},
    {"code":"cs408.os.topic.006da51a6b0f", "target":8, "core":False},
    {"code":"cs408.cn.topic.7789c3d9d6f7", "target":8, "core":False},
    {"code":"cs408.os.topic.bc235cd7a2fb", "target":8, "core":False},
]


def _number(value):
    value = Fraction(value)
    return str(value.numerator) if value.denominator == 1 else f"{value.numerator}/{value.denominator}"


def _choice(stem, answer, explanation, distractors, index, *, family, mode="original", parent=None):
    correct = str(answer)
    values = [correct, *[str(v) for v in distractors]]
    if len(values) != 4 or len(set(values)) != 4:
        raise ValueError(f"invalid_option_fixture:{family}:{values}")
    keys = ["A", "B", "C", "D"]
    keys = keys[index % 4:] + keys[:index % 4]
    options = dict(zip(keys, values))
    right = keys[0]
    return {"family":family, "mode":mode, "parent":parent,
            "output":Output(stem=stem, question_type="single_choice", options=options,
                correct_answer=right, explanation=explanation, final_value=correct)}


def _numeric(stem, answer, explanation, *, family, mode="original", parent=None):
    value = _number(answer)
    return {"family":family, "mode":mode, "parent":parent,
            "output":Output(stem=stem, question_type="fill_blank", options=None,
                correct_answer=value, explanation=explanation, final_value=value)}


def specs_for(code, parent_by_family):
    """Deterministic, bounded exercise variants; no model generated content."""
    specs = []
    if code == "math.exam.de439863790e":
        combos = [(2,2),(3,2),(4,2),(5,2),(2,3),(3,3),(4,3),(5,3),(2,4),(3,4),(4,4),(5,4)]
        for i,(power,point) in enumerate(combos):
            value = power * point**(power-1)
            stem = f"求函数f(x)=x^{power}在x={point}处的导数。"
            explanation = f"由幂函数求导，f'(x)={power}x^{power-1}；代入x={point}，得f'({point})={value}。这里求的是导数值，不是函数值。"
            if i % 3 == 0:
                specs.append(_choice(stem,value,explanation,[value+1,value-1,value+2],i,family="power_derivative"))
            else:
                specs.append(_numeric(stem,value,explanation,family="power_derivative"))
    elif code == "math.exam.c431f98f817c":
        pairs = [(1,1),(2,1),(3,1),(4,1),(2,2),(3,2),(4,2),(5,2),(2,3),(3,3),(4,3),(5,3)]
        for i,(upper,power) in enumerate(pairs):
            value = Fraction(upper**(power+1),power+1)
            stem = f"计算∫_0^{upper}x^{power}dx。"
            explanation = (f"原函数为x^{power+1}/{power+1}；代入上下限得到"
                f"({upper}^{power+1}-0)/{power+1}={_number(value)}。")
            if i % 2:
                specs.append(_choice(stem,_number(value),explanation,[_number(value+1),_number(value-1),_number(value+2)],i,family="power_integral"))
            else:
                specs.append(_numeric(stem,value,explanation,family="power_integral"))
    elif code == "math.exam.c5c672022b7f":
        rows = [("exp",1),("exp",2),("exp",3),("exp",4),
                ("sin",1),("sin",2),("sin",3),("log",1),("log",2),("log",3)]
        for i,(kind,a) in enumerate(rows):
            if kind == "exp":
                stem=f"求极限lim(x→0)(e^({a}*x)-1)/x。"
                reason=f"利用e^u=1+u+o(u)，令u={a}x，极限为{a}。"
            elif kind == "sin":
                stem=f"求极限lim(x→0)sin({a}*x)/x。"
                reason=f"令u={a}x，并用lim(u→0)sin(u)/u=1，极限为{a}。"
            else:
                stem=f"求极限lim(x→0)ln(1+{a}*x)/x。"
                reason=f"令u={a}x，并用ln(1+u)~u，极限为{a}。"
            if i % 3 == 0:
                specs.append(_choice(stem,a,reason,[a+1,a-1,a+2],i,family="exp_limit"))
            else:
                specs.append(_numeric(stem,a,reason,family="exp_limit"))
    elif code == "math.exam.fd2f9e3739d9":
        parent=parent_by_family.get("improper_integral_parameter")
        for i,m in enumerate(range(2,14)):
            value=2*(m-1)
            stem=f"设积分∫_1^∞a/[x(2x+a)]dx=ln({m})，且a>-2，求a。"
            explanation=("原函数可写为ln(x)-ln(2x+a)。由端点极限，积分等于ln(1+a/2)；"
                f"令其等于ln({m})，得a=2({m}-1)={value}。域条件a>-2保证积分区间内分母不出现额外奇点。")
            mode="adapted" if i == 1 and parent else "original"
            specs.append(_numeric(stem,value,explanation,family="improper_integral_parameter",
                                  mode=mode,parent=parent if mode=="adapted" else None))
    elif code == "math.exam.f4e5ed0360ea":
        matrices=[(1,2,3,4),(2,1,4,3),(3,2,1,5),(2,3,5,1),(4,1,2,3),
                  (3,1,4,2),(2,5,1,3),(5,2,3,1),(4,3,2,1),(3,5,2,4)]
        for i,(a,b,c,d) in enumerate(matrices):
            value=a*d-b*c
            stem=f"计算二阶行列式D=|ab;cd|，其中a={a}，b={b}，c={c}，d={d}。"
            explanation=f"二阶行列式按ad-bc计算：{a}×{d}-{b}×{c}={value}。"
            if i % 3:
                specs.append(_choice(stem,value,explanation,[value+1,value-1,value+2],i,family="determinant_2x2"))
            else:
                specs.append(_numeric(stem,value,explanation,family="determinant_2x2"))
    elif code == "math.exam.c106a40cda48":
        rows=[(2,3,2,4,1,2),(3,2,1,1,4,2),(4,2,1,2,3,4),(2,5,3,3,4,1),
              (5,2,2,2,3,5),(3,4,2,5,2,1),(2,4,5,3,5,2),(4,3,1,2,5,3),
              (3,5,4,4,2,1),(5,3,2,3,4,5)]
        for i,(a,b,x,c,d,y) in enumerate(rows):
            e=a*x+b*y; f=c*x+d*y
            if a*d-b*c == 0: raise ValueError("singular codex-authored fixture")
            stem=f"解方程组：{a}x+{b}y={e}；{c}x+{d}y={f}。"
            value=f"({x},{y})"
            distractors=[]
            for pair in ((y,x),(x+1,y),(x,y+1),(x-1,y+2),(x+2,y-1),(x+1,y+1)):
                option=f"({pair[0]},{pair[1]})"
                if option!=value and option not in distractors: distractors.append(option)
                if len(distractors)==3: break
            explanation=f"用消元法求解，并代回两条方程核对：第一式左边为{a}×{x}+{b}×{y}={e}，第二式左边为{c}×{x}+{d}×{y}={f}，所以解为{x}和{y}。"
            if i%2==0:
                specs.append(_numeric(stem+"求x的值。",x,explanation,family="linear_system_2x2"))
            else:
                specs.append(_choice(stem+"求(x,y)。",value,explanation,distractors,i,family="linear_system_2x2"))
    elif code == "cs408.co.topic.324b03e7b481":
        for i,bits in enumerate((8,10)):
            lo=f"−2^{bits-1}"; hi=f"2^{bits-1}−1"
            value=f"{lo} ～ {hi}"
            distractors=[f"−2^{bits} ～ 2^{bits}−1",f"−2^{bits-2} ～ 2^{bits-2}−1",f"−2^{bits-1} ～ 2^{bits-1}"]
            options=[value,*distractors]; keys=["A","B","C","D"]; keys=keys[i%4:]+keys[:i%4]
            opts=dict(zip(keys,options)); key=keys[0]
            explanation=f"{bits}位补码范围为[-2^{bits-1}, 2^{bits-1}-1]，负端点包含最小值，正端点少一个。"
            if i%2==0:
                endpoint="最小" if i%4==0 else "最大"
                endpoint_value=-(1<<(bits-1)) if endpoint=="最小" else (1<<(bits-1))-1
                stem=f"{bits}位补码所能表示的{endpoint}整数是多少？"
                specs.append(_numeric(stem,endpoint_value,explanation,family="signed_range"))
                continue
            stem=f"{bits}位补码所能表示的整数范围是（ ）。"
            specs.append({"family":"signed_range","mode":"original","parent":None,
                "output":Output(stem=stem,question_type="single_choice",options=opts,correct_answer=key,
                    explanation=explanation,final_value=value)})
        decode_rows=[
            ("按原码解释（最高位为符号位、其余位表示绝对值），字长为8位，编码10000101表示的十进制整数是多少？",-5,
             "最高位1表示负数，其余7位表示5，故真值为-5。"),
            ("按反码解释（正数编码同原码、负数由正数码逐位取反），字长为8位，编码11111101表示的十进制整数是多少？",-2,
             "反码逐位取反得到正数码00000010，对应2，因此真值为-2。"),
            ("按移码解释（真值=无符号编码值-2^(n-1)），字长为8位，编码10000010表示的十进制整数是多少？",2,
             "无符号编码值为130，偏置值为2^7=128，真值为130-128=2。"),
        ]
        for stem,value,explanation in decode_rows:
            specs.append(_numeric(stem,value,explanation,family="fixed_point_decode"))
        pairs=[(0xA3,0x75),(0x51,0x22),(0x80,0x01),(0x6F,0xD0),(0xF0,0x40)]
        for i,(xraw,yraw) in enumerate(pairs,5):
            def signed(raw): return raw-256 if raw>=128 else raw
            x,y=signed(xraw),signed(yraw); exact=x-y; wrapped=exact%256; wrapped=wrapped-256 if wrapped>=128 else wrapped
            of=int(not -128<=exact<=127); value=f"{wrapped}，{of}"
            options=[value,f"{wrapped}，{1-of}",f"{wrapped+1}，{of}",f"{wrapped-1}，{of}"]
            keys=["A","B","C","D"]; keys=keys[i%4:]+keys[:i%4]
            opts=dict(zip(keys,options)); key=keys[0]
            stem=(f"假设8位字长计算机中，带符号整数x、y的补码分别为`[x]补={xraw:02X}H`、"
                  f"`[y]补={yraw:02X}H`，通过补码加减运算器得到x-y的值及OF标志分别为：")
            explanation=(f"先将两个补码解释为有符号整数x={x}、y={y}，精确差为{x-y}；"
                f"8位结果按模256回绕为{wrapped}，是否越出[-128,127]决定OF={of}。")
            if i%2==0:
                numeric_stem=(f"假设8位字长计算机中，带符号整数x、y的补码分别为`[x]补={xraw:02X}H`、"
                    f"`[y]补={yraw:02X}H`，计算x-y并按8位补码解释，所得带符号整数为多少？")
                specs.append(_numeric(numeric_stem,wrapped,explanation,family="signed_subtract_value"))
            else:
                specs.append({"family":"signed_subtract","mode":"original","parent":None,
                    "output":Output(stem=stem,question_type="single_choice",options=opts,correct_answer=key,
                        explanation=explanation,final_value=value)})
    elif code == "cs408.ds.topic.1efaf3d00b50":
        parent=parent_by_family.get("full_tree_count")
        for i,n in enumerate((9,15)):
            leaves=(n+1)//2
            stem=f"一棵有{n}个结点的完全二叉树，其叶结点数为多少？"
            explanation=f"按1开始编号，结点i为叶结点当且仅当2i>{n}；因此叶结点数为ceil({n}/2)={leaves}。"
            if i%2==0:
                specs.append(_numeric(stem,leaves,explanation,family="complete_tree"))
            else:
                specs.append(_choice(stem,leaves,explanation,[leaves+1,leaves-1,leaves+2],i,family="complete_tree"))
        storage_rows=[(31,5,"左孩子"),(31,6,"右孩子"),(31,19,"双亲")]
        for count,index,relation in storage_rows:
            value=2*index if relation=="左孩子" else 2*index+1 if relation=="右孩子" else index//2
            stem=f"在按1开始下标顺序存储、共有{count}个结点的完全二叉树中，结点i={index}的{relation}下标是多少？"
            explanation=f"顺序存储采用1起始下标：{relation}下标按规则计算为{value}。"
            specs.append(_numeric(stem,value,explanation,family="complete_tree_storage_index"))
        for i,k in enumerate((2,3,5,8,13),5):
            value=2*k-1
            stem=f"非空二叉树每个非叶结点恰有2个孩子，叶结点数为k，若k={k}，求总结点数。"
            explanation=f"设非叶结点数为m，则边数既为m+k-1又为2m，故m=k-1；总结点数m+k=2k-1={value}。"
            mode="adapted" if i==5 and parent else "original"
            if i%2:
                spec=_choice(stem,value,explanation,[value+1,value-1,value+2],i,family="full_tree_count",mode=mode,parent=parent if mode=="adapted" else None)
            else:
                spec=_numeric(stem,value,explanation,family="full_tree_count",mode=mode,parent=parent if mode=="adapted" else None)
            specs.append(spec)
    elif code == "cs408.ds.topic.8b04b55a0408":
        arrays=[([1,3,5,7,9,11,13],9),([2,4,6,8,10,12,14,16],2),
            ([3,8,13,18,23,28,33,38,43],33),([1,5,9,13,17,21,25,29,33,37],37),
            ([4,10,16,22,28,34,40],16),([0,6,12,18,24,30,36,42],42),
            ([2,9,16,23,30,37,44,51,58],23),([5,12,19,26,33,40,47],47),
            ([1,2,4,8,16,32,64,128,256,512,1024],32),([7,14,21,28,35,42,49,56],56)]
        for i,(arr,target) in enumerate(arrays):
            low,high,trace=0,len(arr)-1,[]
            while low<=high:
                mid=(low+high)//2; trace.append(arr[mid])
                if arr[mid]==target: break
                if arr[mid]<target: low=mid+1
                else: high=mid-1
            count=len(trace); stem=(f"在升序数组[{','.join(map(str,arr))}]中，按1起始下标执行二分查找："
                f"初始low=1、high=n，mid=floor((low+high)/2)，使用闭区间，目标值为{target}且保证存在；求成功前的关键字比较次数？")
            explanation=f"依题目给定的闭区间和中点规则，逐次比较的关键字为{','.join(map(str,trace))}，共{count}次。"
            if i%2:
                specs.append(_numeric(stem,count,explanation,family="binary_search_steps"))
            else:
                specs.append(_choice(stem,count,explanation,[count+1,count-1,count+2],i,family="binary_search_steps"))
    elif code == "cs408.os.topic.006da51a6b0f":
        sequences=[("FIFO",[1,2,3,1,4,1,5]),("LRU",[1,2,3,1,4,1,5]),
            ("FIFO",[0,1,2,0,3,4,0,1]),("LRU",[0,1,2,0,3,4,0,1]),
            ("FIFO",[2,3,2,1,5,2,4,5]),("LRU",[2,3,2,1,5,2,4,5]),
            ("FIFO",[1,3,0,3,5,6,3,0]),("LRU",[1,3,0,3,5,6,3,0]),
            ("FIFO",[4,1,2,4,3,5,1,2]),("LRU",[4,1,2,4,3,5,1,2])]
        for i,(algorithm,refs) in enumerate(sequences):
            frames=[]; faults=0
            for page in refs:
                if page not in frames:
                    faults+=1
                    if len(frames)==3: frames.pop(0)
                    frames.append(page)
                elif algorithm=="LRU": frames.remove(page); frames.append(page)
            stem=f"采用{algorithm}页面置换算法，内存有3个页框且初始为空，访问序列为{','.join(map(str,refs))}，求缺页次数？"
            explanation=f"逐项模拟{algorithm}，只有访问页不在3个页框时记一次缺页；按题目定义，缺页共{faults}次。"
            if i%2:
                specs.append(_numeric(stem,faults,explanation,family="page_replacement_faults"))
            else:
                specs.append(_choice(stem,faults,explanation,[faults+1,max(0,faults-1),faults+2],i,family="page_replacement_faults"))
    elif code == "cs408.cn.topic.7789c3d9d6f7":
        for i,prefix in enumerate((24,25,26,27,28,29,30,23,22,21)):
            count=2**(32-prefix)-2
            stem=f"某IPv4子网前缀长度为/{prefix}，按排除网络地址和广播地址的普通子网规则，可分配主机地址数是多少？"
            explanation=f"主机位为32-{prefix}={32-prefix}位；在题目明确的传统子网约定下，可用地址数为2^{32-prefix}-2={count}。"
            if i%2:
                specs.append(_numeric(stem,count,explanation,family="subnet_host_count"))
            else:
                specs.append(_choice(stem,count,explanation,[count+2,count-2,count+4],i,family="subnet_host_count"))
    elif code == "cs408.os.topic.bc235cd7a2fb":
        rows=[(2,5,3),(4,1,6,2),(3,7,2,5),(5,2,8,1,4),(6,3,2,7),
              (1,4,2,6,3,5),(7,2,5,3),(2,8,4,1,6),(3,6,9,2),(5,1,4,7,2)]
        for bursts in rows:
            waits=[sum(bursts[:i]) for i in range(len(bursts))]
            average=Fraction(sum(waits),len(bursts)); stem=("所有进程到达时间均为0，按给定顺序采用FCFS调度，"
                f"运行时间依次为{','.join(map(str,bursts))}，平均等待时间是多少？")
            explanation=f"FCFS等待时间依次为{','.join(map(str,waits))}，合计{sum(waits)}；除以{len(bursts)}个进程，平均等待时间为{_number(average)}。"
            specs.append(_numeric(stem,average,explanation,family="fcfs_waiting_time"))
    return specs


def qualified(q, node, *, teaching_enabled):
    eligibility=question_eligibility(q,node,teaching_enabled=teaching_enabled)
    if not eligibility.practice_eligible: return False, {"reason":"practice_ineligible"}
    content=validate_question_content(q)
    independent=verify_problem(q)
    grading=grader_checks(q)
    if content.status != "STRUCTURALLY_COMPLETE": return False, {"reason":"incomplete_structure"}
    if independent.get("status") != "PASS": return False, {"reason":"independent_answer_not_pass","verifier":independent}
    if grading.get("status") != "PASS": return False, {"reason":"grader_boundary_not_pass","grader":grading}
    if q.kp_id != node.id or not node.is_active or not node.is_assessable: return False, {"reason":"mapping_invalid"}
    teaching=audit_teaching_question(q,node,baseline=eligibility)
    if not teaching["teaching_practice_eligible"]: return False, {"reason":"teaching_quality_not_eligible","quality":teaching}
    return True, {"verifier":independent,"grader":grading,"teaching_quality":teaching,
        "practice_eligibility":eligibility.public_dict(),"content_status":content.status}


def _policy_dict(policy):
    return {key:str(getattr(policy,key)) for key in KpMasteryPolicy.__table__.columns.keys()}


def _question_row(q, node, check, candidate):
    generation=(q.grading_config or {}).get("generation",{})
    return {"question_id":str(q.id),"node_code":node.code,"node_name":node.name,
        "question_type":q.question_type,"stem":q.stem,"options":q.options,
        "correct_answer":q.correct_answer,"explanation":q.explanation,
        "question_role":q.question_role,"difficulty":q.difficulty,"skill_tags":q.skill_tags,
        "question_provenance":q.question_provenance,"content_trust":q.content_trust,
        "source_status":q.source_status,"answer_provenance":q.answer_provenance,
        "answer_reliability":q.answer_reliability,"content_sha256":question_content_sha256(q),
        "generation_version":generation.get("version"),"generation_family":generation.get("family"),
        "identity_label":generation.get("identity_label"),"parent_question_id":generation.get("parent_question_id"),
        "authoring_mode":generation.get("authoring_mode"),"independent_verifier":check["verifier"],
        "grader_boundary":check["grader"],"teaching_quality":check["teaching_quality"],
        "strict_evidence_capability":question_eligibility(q,node,teaching_enabled=True).evidence_capability,
        "real_model_called":bool(generation.get("real_model_called")),"candidate_id":candidate}


def run(args):
    output=safe_output(args.output_dir)
    diagnosis=json_input(args.diagnosis/"report.json")
    raw=json_input(args.diagnosis/"inventory-snapshot.json")
    if digest(raw) != diagnosis.get("inventory_snapshot_sha256"):
        raise ValueError("frozen inventory snapshot digest mismatch")
    settings=get_settings()
    if settings.teaching_practice_enabled: raise ValueError("refuse pilot while development teaching flag is enabled")
    dev_engine=create_db_engine(str(settings.active_database_url))
    with create_session_factory(dev_engine)() as db:
        db.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"))
        before=fingerprints(db); db.rollback()
    dev_engine.dispose()
    if before != diagnosis["protection"]["after"]:
        raise ValueError("live development fingerprint differs from frozen diagnosis")
    test_url=(str(settings.test_database_url) if settings.test_database_url else
        make_url(str(settings.database_url)).set(database="kaoyan_test").render_as_string(hide_password=False))
    if (make_url(test_url).host not in {"127.0.0.1","localhost"}
            or not (make_url(test_url).database or "").endswith("_test")):
        raise ValueError("only explicit local _test database is accepted")

    node_codes={item["code"] for item in NODES}
    spec_rows=[row for row in diagnosis["questions"] if row["node_code"] in node_codes
        and row["automatic_answer_proof_available"] and row.get("pack_link",{}).get("usable")
        and not row["production_eligibility"]["practice_eligible"]]
    repair_registry=None
    previous_flag=settings.teaching_practice_enabled
    pilot_result=None
    try:
        with isolated_factory(test_url) as (factory,schema):
            clone_inventory(factory,raw)
            settings.teaching_practice_enabled=True
            with factory() as db:
                node_by_code={node.code:node for node in db.scalars(select(KnowledgePoint).where(KnowledgePoint.code.in_(node_codes)))}
                if set(node_by_code)!=node_codes: raise ValueError("selected node inventory mismatch")
                selected_questions=list(db.scalars(select(Question).where(Question.kp_id.in_([n.id for n in node_by_code.values()]))))
                before_policies={code:_policy_dict(db.get(KpMasteryPolicy,node.id)) for code,node in node_by_code.items()}
                before_question_ids={str(q.id) for q in selected_questions}
                pre_repair={}
                for item in NODES:
                    code=item["code"]; node=node_by_code[code]
                    selected=[q for q in selected_questions if q.kp_id==node.id and q.is_active]
                    live_eligible=sum(question_eligibility(q,node,teaching_enabled=False).practice_eligible for q in selected)
                    flag_on_eligible=[q for q in selected if question_eligibility(q,node,teaching_enabled=True).practice_eligible]
                    passed=[]
                    for q in flag_on_eligible:
                        ok,_=qualified(q,node,teaching_enabled=True)
                        if ok: passed.append(q)
                    dup=duplicates(passed)
                    passed=[q for q in passed if not dup[str(q.id)]["exact"]]
                    pre_repair[code]={"active_questions":len(selected),
                        "live_feature_off_practice_eligible":live_eligible,
                        "feature_on_practice_eligible_before_repair":len(flag_on_eligible),
                        "independently_qualified_before_repair":len(passed),
                        "qualified_types_before_repair":_counts(q.question_type for q in passed),
                        "strict_verified_objective_before_repair":sum(question_eligibility(q,node,teaching_enabled=True).evidence_capability=="verified_objective" for q in selected)}
                parent_by_family={}
                for qid, family in (("ab961f2c-8e24-4068-9bfc-effc9ea876e9","improper_integral_parameter"),
                                    ("e4225412-c705-4439-97b0-593278e28da3","full_tree_count")):
                    q=db.get(Question,__import__("uuid").UUID(qid))
                    if q and has_current_source_attestation(q) and q.source_status in {"traceable","verified"}:
                        parent_by_family[family]=q

            # Phase 1: only source-pack links with exact native fingerprints,
            # current source pack metadata and independently derived answers.
            from backend.services.question_repair import local_pack_registry, identity_counts, restore_pack_binding
            repair_registry,_=local_pack_registry(ROOT)
            repair_receipts=[]
            for plan in spec_rows:
                with factory.begin() as db:
                    q=db.get(Question,__import__("uuid").UUID(plan["question_id"]))
                    node=db.get(KnowledgePoint,q.kp_id)
                    all_q=list(db.scalars(select(Question)))
                    result=restore_pack_binding(db,q,node,plan,repair_registry,identity_counts(all_q),)
                    replay=restore_pack_binding(db,q,node,plan,repair_registry,identity_counts(all_q))
                    if replay["status"]!="NOOP": raise ValueError("source-binding replay was not idempotent")
                    repair_receipts.append({"question_id":str(q.id),"node_code":node.code,
                        "status":result["status"],"replay":replay["status"],
                        "source_attestation_created":result["status"]=="APPLIED_IN_ISOLATION",
                        "question_content_changed":False,"answer_changed":False,"human_verified_created":False})

            with factory() as db:
                nodes={n.code:n for n in db.scalars(select(KnowledgePoint).where(KnowledgePoint.code.in_(node_codes)))}
                all_questions=list(db.scalars(select(Question)))
                baseline={}
                qualified_by_node={}
                for item in NODES:
                    node=nodes[item["code"]]
                    selected=[q for q in all_questions if q.kp_id==node.id and q.is_active]
                    eligible=[q for q in selected if question_eligibility(q,node,teaching_enabled=True).practice_eligible]
                    passed=[]; checks={}
                    for q in eligible:
                        ok,check=qualified(q,node,teaching_enabled=True)
                        if ok: passed.append(q); checks[str(q.id)]=check
                    dup=duplicates(passed)
                    unique=[q for q in passed if not dup[str(q.id)]["exact"]]
                    qualified_by_node[item["code"]]={str(q.id):checks[str(q.id)] for q in unique}
                    baseline[item["code"]]={"active_questions":len(selected),"practice_eligible_after_source_repair_before_generation":len(eligible),
                        "independently_qualified_after_source_repair":len(unique),"qualified_question_types":_counts(q.question_type for q in unique),
                        "strict_verified_objective_existing":sum(question_eligibility(q,node,teaching_enabled=True).evidence_capability=="verified_objective" for q in selected),
                        "policy":before_policies[item["code"]],"excluded_eligible_not_qualified":len(eligible)-len(unique)}

            candidates=[]; selected_candidate_ids={}; promoted_questions_by_node={}
            from backend.services.answer_grading import available_practice_grading_method
            for item in NODES:
                code=item["code"]; node=nodes[code]; target=item["target"]
                existing_count=len(qualified_by_node[code])
                need=max(0,target-existing_count)
                specs=specs_for(code,parent_by_family)
                accepted=0; seen_parameters=set()
                with factory() as db:
                    existing_for_node=list(db.scalars(select(Question).where(Question.kp_id==node.id)))
                for ordinal,spec in enumerate(specs):
                    if accepted>=need: break
                    request_id=f"phase45d-v3:{code}:{spec['family']}:{ordinal}"
                    parent=spec.get("parent")
                    trace={"mode":"codex_assisted","model":"Codex-assisted deterministic content registry; no external model",
                        "prompt_version":"phase45d-codex-assisted-v3","model_calls":0,"usage":None}
                    candidate=assess_output(spec["output"],node,request_id=request_id,mode=spec["mode"],
                        family=spec["family"],parent=parent,trace=trace,skill_tags=[node.name])
                    candidate["parameters_sha256"]=digest(candidate["record"]["independent_verification"].get("proof",{}))
                    if candidate["parameters_sha256"] in seen_parameters:
                        candidate["status"]="REJECTED"; candidate["errors"].append("duplicate_independent_proof_parameters")
                    seen_parameters.add(candidate["parameters_sha256"])
                    if candidate["status"]=="AUTO_PASS":
                        q=candidate["question"]
                        all_for_dedup=[*existing_for_node,*promoted_questions_by_node.get(code,[])]
                        dup=duplicates([*all_for_dedup,q])[str(q.id)]
                        if dup["exact"]:
                            candidate["status"]="REJECTED"; candidate["errors"].append("exact_duplicate_content_or_source_identity")
                    promoted=False; check={}
                    if candidate["status"]=="AUTO_PASS":
                        with factory.begin() as db:
                            promoted_q,promote_status=promote(db,candidate,db.get(KnowledgePoint,node.id))
                        with factory.begin() as db:
                            replay_q,replay_status=promote(db,candidate,db.get(KnowledgePoint,node.id))
                            if replay_status!="NOOP" or str(replay_q.id)!=str(promoted_q.id):
                                raise ValueError("generation replay failed idempotency")
                        with factory() as db:
                            saved=db.get(Question,promoted_q.id); live_node=db.get(KnowledgePoint,node.id)
                            ok,check=qualified(saved,live_node,teaching_enabled=True)
                            if not ok: raise ValueError(f"promoted candidate failed current eligibility: {code}:{check.get('reason')}")
                            e=question_eligibility(saved,live_node,teaching_enabled=True)
                            if e.evidence_capability=="verified_objective" or e.verified_grading_method is not None:
                                raise ValueError("ordinary Codex question acquired strict verification capability")
                        promoted=True; accepted+=1; selected_candidate_ids.setdefault(code,str(promoted_q.id))
                        promoted_questions_by_node.setdefault(code,[]).append(candidate["question"])
                    candidates.append({"node_code":code,"node_name":node.name,"family":spec["family"],
                        "mode":spec["mode"],"candidate_id":candidate["candidate_id"],"status":candidate["status"],
                        "errors":candidate["errors"],"promoted_in_isolation":promoted,
                        "promotion_status":promote_status if promoted else None,"idempotent_replay":replay_status if promoted else None,
                        "question_content_sha256":candidate["question_content_sha256"],
                        "generation_hash":candidate["generation_hash"],"parameters_sha256":candidate["parameters_sha256"],
                        "verifier":candidate["record"]["independent_verification"],
                        "grader":check.get("grader"),"teaching_quality":candidate["quality"],
                        "strict_evidence_capability":"not_verified_objective","real_model_called":False,"model_calls":0,
                        "question":candidate["question"]})

            # Verify every final item and compute target counts over a unique,
            # independently verified, supported-answer subset.
            final_nodes={}; final_rows=[]; strict_gap={}
            with factory() as db:
                policies={code:_policy_dict(db.get(KpMasteryPolicy,nodes[code].id)) for code in nodes}
                for item in NODES:
                    code=item["code"]; node=db.get(KnowledgePoint,nodes[code].id)
                    rows=list(db.scalars(select(Question).where(Question.kp_id==node.id,Question.is_active.is_(True))))
                    qualified_rows=[]; all_eligible=sum(question_eligibility(q,node,teaching_enabled=True).practice_eligible for q in rows)
                    strict_rows=[]
                    for q in rows:
                        if question_eligibility(q,node,teaching_enabled=True).evidence_capability=="verified_objective": strict_rows.append(q)
                        ok,check=qualified(q,node,teaching_enabled=True)
                        if ok: qualified_rows.append((q,check))
                    dup=duplicates([q for q,_ in qualified_rows])
                    qualified_rows=[(q,c) for q,c in qualified_rows if not dup[str(q.id)]["exact"]]
                    final_nodes[code]={"node_name":node.name,"subject":node.subject,"reference_only":node.is_reference_only,
                        "target_qualified_questions":item["target"],"active_questions_before":pre_repair[code]["active_questions"],
                        "currently_practice_eligible_live_feature_off":pre_repair[code]["live_feature_off_practice_eligible"],
                        "practice_eligible_feature_on_before_repair":pre_repair[code]["feature_on_practice_eligible_before_repair"],
                        "independently_qualified_existing_before_repair":pre_repair[code]["independently_qualified_before_repair"],
                        "qualified_after_source_repair_before_generation":baseline[code]["independently_qualified_after_source_repair"],
                        "repair_restored_in_isolation":sum(r["node_code"]==code and r["status"]=="APPLIED_IN_ISOLATION" for r in repair_receipts),
                        "qualified_after_isolated_pilot":len(qualified_rows),
                        "target_met":len(qualified_rows)>=item["target"],
                        "question_type_mix":_counts(q.question_type for q,_ in qualified_rows),
                        "currently_practice_eligible_after":all_eligible,
                        "reliable_strict_objective_questions":len(strict_rows),
                        "real_exam_questions_in_pool":sum(q.question_provenance=="real_exam" for q,_ in qualified_rows),
                        "graduation_policy":policies[code],
                        "strict_policy_reachable_from_live_verified_inventory":len(strict_rows)>=3,
                        "strict_policy_note":"policy requires 3 distinct real_exam confirmations, >=2 days, and required skill tag; generated practice is excluded"}
                    for q,check in qualified_rows:
                        candidate_id=next((r["candidate_id"] for r in candidates if r["candidate_id"]==str(q.id)),None)
                        final_rows.append(_question_row(q,node,check,candidate_id))
                    strict_gap[code]={"required_real_exam":3,"available_verified_objective":len(strict_rows),
                        "minimum_confirmations":int(policies[code]["min_confirmations"]),
                        "minimum_day_span":int(policies[code]["min_day_span"]),
                        "effective_graduation_evidence_count":0}
                original_policies={code:_policy_dict(db.get(KpMasteryPolicy,nodes[code].id)) for code in nodes}
                if original_policies!=before_policies: raise ValueError("policy changed inside isolated pilot")
                candidate_qids={r["candidate_id"] for r in candidates if r["promoted_in_isolation"]}
                if len(candidate_qids)!=sum(r["promoted_in_isolation"] for r in candidates): raise ValueError("duplicate candidate IDs")
                if any((q.grading_config or {}).get("generation",{}).get("real_model_called") for q in db.scalars(select(Question))):
                    raise ValueError("unexpected external model metadata in isolated inventory")

            exercise_ids=[]
            for code in final_nodes:
                qid=selected_candidate_ids.get(code)
                if qid is None:
                    with factory() as db:
                        node=nodes[code]
                        q=next((q for q in db.scalars(select(Question).where(Question.kp_id==node.id))
                            if q.id in [__import__("uuid").UUID(x) for x in before_question_ids]
                            and qualified(q,node,teaching_enabled=True)[0]),None)
                        if qid is None and q: qid=str(q.id)
                if qid: exercise_ids.append(qid)
            business=business_check(factory,exercise_ids,None)

            with factory() as db:
                policies_after={code:_policy_dict(db.get(KpMasteryPolicy,nodes[code].id)) for code in nodes}
                if policies_after!=before_policies: raise ValueError("policy changed after business rehearsal")
                if any(question_eligibility(q,db.get(KnowledgePoint,q.kp_id),teaching_enabled=True).evidence_capability=="verified_objective"
                    for q in db.scalars(select(Question).where(Question.question_provenance=="ai_generated_practice"))):
                    raise ValueError("AI-origin questions unexpectedly supplied strict evidence")

            target_total=sum(item["target"] for item in NODES)
            qualified_total=sum(row["qualified_after_isolated_pilot"] for row in final_nodes.values())
            passed=sum(row["target_met"] for row in final_nodes.values())
            pilot_result={"status":"PHASE45D_COMPLETED" if passed==len(NODES) and business.get("status")=="PASS" else "PHASE45D_PARTIAL",
                "schema":schema,"environment":"marked_local_test_schema_created_from_read_only_live_snapshot",
                "nodes_selected":len(NODES),"math_nodes":sum(code.startswith("math.") for code in node_codes),
                "408_nodes":sum(code.startswith("cs408.") for code in node_codes),"target_qualified_questions_total":target_total,
                "qualified_question_count_after_pilot":qualified_total,"nodes_meeting_target":passed,
                "repairs_applied_only_in_isolation":sum(r["status"]=="APPLIED_IN_ISOLATION" for r in repair_receipts),
                "adapted_question_count":sum(r["promoted_in_isolation"] and r["mode"]=="adapted" for r in candidates),
                "codex_original_question_count":sum(r["promoted_in_isolation"] and r["mode"]=="original" for r in candidates),
                "candidate_count":len(candidates),"candidate_pass_count":sum(r["promoted_in_isolation"] for r in candidates),
                "current_generation_version":GENERATION_VERSION,"verifier_version":VERIFIER_VERSION,
                "real_model_calls":0,"real_model_usage":None,"paid_cost":0,
                "human_verified_created":0,"production_database_writes":0,
                "development_feature_flag_before":previous_flag,"development_feature_flag_after":settings.teaching_practice_enabled,
                "policy_unchanged":True,"selected_nodes":final_nodes,"strict_graduation_gaps":strict_gap,
                "practice_retest_and_progress_closure":business,
                "real_graduation_mechanics_test":{"status":"PASS_TEST_FIXTURE_ONLY",
                    "test_id":"tests/integration/test_policy_origin_semantics.py::test_three_future_verified_real_exam_answers_graduate_with_exact_receipt_snapshots",
                    "scope":"synthetic TEST_FIXTURE policy mechanics only; no pilot candidate or real learner was graduated"},
                "dedup":{"exact_duplicate_candidates_accepted":0,
                    "near_template_flags_reported":sum(bool(duplicates([r["question"] for r in candidates if r["promoted_in_isolation"]])[r["candidate_id"]]["near"])
                        for r in candidates if r["promoted_in_isolation"]),
                    "method":"source-identity and normalized exact-stem/options duplicate rejection; bounded families have unique verifier-proof parameter hashes; semantic embedding dedup is not claimed"},
                "candidates":[{k:v for k,v in row.items() if k!="question"} for row in candidates],
                "qualified_questions_private":final_rows,
                "repair_receipts":repair_receipts,
                "question_bank_artifact":"bank-candidates.json",
                "limitations":["strict real_exam quota remains unreachable from this trial bank because generated practice never becomes real_exam or verified_objective",
                    "AUTO_PASS proves only an allowlisted stored form and answer; it is not human verification or syllabus completeness",
                    "near-template checks are parameterized practice variants, not semantic deduplication",
                    "no redistribution/license audit was performed; private storage artifact is not authorization to publish question content"]}
    finally:
        settings.teaching_practice_enabled=previous_flag

    pilot_result["development_feature_flag_after"]=settings.teaching_practice_enabled

    # Verify the original development database remained byte-for-byte stable at
    # the existing table-fingerprint boundary after the isolated schema cleanup.
    dev_engine=create_db_engine(str(settings.active_database_url))
    with create_session_factory(dev_engine)() as db:
        db.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"))
        after=fingerprints(db); db.rollback()
    dev_engine.dispose()
    if before!=after: raise ValueError("development DB fingerprint drift")
    if settings.teaching_practice_enabled!=previous_flag: raise ValueError("production feature flag was not restored")
    pilot_result["protection"]={"development_fingerprint_before":before,"development_fingerprint_after":after,
        "equal":before==after,"isolated_schema_removed":True,"development_feature_flag_restored":True}

    output.mkdir(parents=True,exist_ok=False)
    # Full exercise text stays under ignored local storage. The report itself
    # contains node-level summaries and candidate identifiers, not exam text.
    bank={"format":"phase45d-private-candidate-bank-v1","version":GENERATION_VERSION,
        "created_from_live_snapshot_sha256":diagnosis["inventory_snapshot_sha256"],
        "authoring_mode":"codex_assisted_deterministic_templates","real_model_calls":0,
        "human_verification":False,"strict_graduation_eligible":False,
        "questions":pilot_result["qualified_questions_private"]}
    (output/"bank-candidates.json").write_text(json.dumps(bank,ensure_ascii=False,indent=2),encoding="utf-8")
    (output/"report.json").write_text(json.dumps(pilot_result,ensure_ascii=False,indent=2,default=str),encoding="utf-8")
    report_lines=["# Phase 4.5D 小范围公共基础题库试点","",
        f"状态：`{pilot_result['status']}`；节点{len(NODES)}个（数学{pilot_result['math_nodes']}，408 {pilot_result['408_nodes']}）；合格储备目标{target_total}题，隔离结果{qualified_total}题。",
        "本报告中的‘合格’表示：当前隔离版教学资格、结构完整、允许列表独立答案验证 PASS、真实练习比较器边界测试 PASS、知识节点绑定有效；不代表 HUMAN_VERIFIED、官方答案或真题版权许可。",
        "", "| 科目 | 节点 | 当前开关下可练 | 现有合格（修复前） | 来源绑定恢复后 | 本轮合格总量 | 目标题量 | 题型结构 | 严格客观证据 | 现行毕业门槛可达 |",
        "|---|---|---:|---:|---:|---:|---:|---|---:|---|"]
    for code,row in final_nodes.items():
        subject="数学二范围" if code.startswith("math.") else "408"
        types=", ".join(f"{k}:{v}" for k,v in sorted(row["question_type_mix"].items())) or "无"
        report_lines.append(f"| {subject} | {row['node_name']} | {row['currently_practice_eligible_live_feature_off']} | {row['independently_qualified_existing_before_repair']} | {row['qualified_after_source_repair_before_generation']} | {row['qualified_after_isolated_pilot']} | {row['target_qualified_questions']} | {types} | {row['reliable_strict_objective_questions']} | {'是' if row['strict_policy_reachable_from_live_verified_inventory'] else '否'} |")
    report_lines.extend(["", "## 重要限制", "",
        "- 题目在临时隔离 schema 中实际通过今日卷生成/追加、错误/空/非法/正确答案提交、自我纠错、学习进展读取和 Agent 工具事实读取；不写入开发库。",
        "- 生成题的来源身份始终是 AI/Codex 辅助练习或真题改编练习，不获得 real_exam、HUMAN_VERIFIED、verified_reference 或 verified_objective。",
        "- 当前 12 个节点策略均要求至少 3 道 real_exam 客观确认，至少 3 次确认、跨天不少于 2 天，并覆盖节点规定技能标签。新增的公共基础练习不会改变或满足 real_exam 配额。",
        "- 对练习试点可判性和复测闭环的结论不等于毕业闭环真实通过。当前真实可信毕业库存为零时，严格毕业在这些节点仍不可达；毕业算法正向成功路径使用单独 TEST_FIXTURE 测试。",
        "- 检测到的近模板相似仅在私有 JSON 中保留并按唯一参数/独立 proof 作为参数变式解释；本轮未进行向量语义去重，也不宣称题库在概念层完全无重复。",
        "- “数学二范围”是按项目数学知识树中常规数二内容选择；数据库 subject 标签为项目内部“考研数学”，不将其伪称为官方考试目录证明。",
        "- 题库工件保存在 ignored 私有目录，不是公开发布或再分发许可。", "",
        "完整题干、选项、答案及解析仅保存于同目录 `bank-candidates.json`；不要直接复制到公开 GitHub。"])
    (output/"report.md").write_text("\n".join(report_lines)+"\n",encoding="utf-8")
    print(json.dumps({k:v for k,v in pilot_result.items() if k not in {"candidates","qualified_questions_private","practice_retest_and_progress_closure","repair_receipts","protection","selected_nodes","strict_graduation_gaps"}},ensure_ascii=False,indent=2))
    return pilot_result


def _counts(values):
    result={}
    for value in values: result[value]=result.get(value,0)+1
    return result


if __name__=="__main__":
    if hasattr(sys.stdout,"reconfigure"): sys.stdout.reconfigure(encoding="utf-8")
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--diagnosis",type=Path,required=True)
    parser.add_argument("--output-dir",type=Path,required=True)
    parser.add_argument("--isolated-pilot",action="store_true",required=True)
    run(parser.parse_args())
