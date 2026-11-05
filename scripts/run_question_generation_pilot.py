"""C1 offline simulation by default. Actual paid generation is not authorized here."""
import argparse
from copy import deepcopy
from pathlib import Path
from uuid import UUID
from fractions import Fraction
from datetime import datetime,timezone
import json
import sys
ROOT=Path(__file__).resolve().parents[1]; sys.path.insert(0,str(ROOT))
from sqlalchemy import select,text
from backend.config import get_settings
from backend.db import create_db_engine,create_session_factory
from backend.models.learning import Question,KnowledgePoint,KpMasteryPolicy,QuestionAttempt
from backend.services.question_generation import Budget,generate,assess_output,promote,GENERATION_VERSION
from backend.services.question_eligibility import question_eligibility
from backend.services.golden_learning_slice import digest
from backend.services.question_verification_upgrade import snapshot
from scripts.run_question_repair_pilot import isolated_factory,clone_inventory,business_check
from scripts.audit_question_quality import json_input,safe_output
from scripts.review_golden_slice import fingerprints
from sqlalchemy.engine import make_url


class FixtureModel:
    simulation=True
    model="C1_SIMULATED_FIXTURE_NOT_LLM"
    def complete(self,messages,*,attempt=1):
        request=json.loads(messages[-1]["content"]); family=request["family"]; j=request.get("sample",0)
        qt=request.get("question_type","single_choice"); n=j%5+1; t=j%4+1
        if request.get("family_contract"):
            if family=="power_derivative":
                if qt=="fill_blank":
                    coefficient=j%7+1; stem=f"已知函数f(x)=x^3+{coefficient}x+1，求f'(2)的值。"; value=str(14+coefficient)
                    explanation=f"逐项求导得f'(x)=3x^2+{coefficient}，代入2后结果为{value}。"
                else:
                    coefficient=j%7+1; stem=f"设函数f(x)=x^3+{coefficient}x^2+2x，求f'(x)。"
                    value=f"3x^2+{2*coefficient}x+2"; explanation=f"用幂函数求导法则逐项求导，得到{value}。"
            elif family=="power_integral":
                b=j%5+2; degree=(j*2)%5+1; value=str(Fraction(b**(degree+1),degree+1))
                stem=f"计算定积分：∫_0^{b} x^{degree} dx = ______。"
                explanation=f"原函数为x^{degree+1}/{degree+1}，代入上下限后结果为{value}。"
            elif family=="improper_integral_parameter":
                qt="single_choice"
                stem="关于含参数p的反常积分I(p)=∫_e^{+∞} dx/[x(ln x)^p]，下列结论正确的是（ ）。"
                value="p>1"; explanation="令t=ln x后化为p积分，收敛当且仅当p>1。"
            elif family=="exp_limit":
                a=j%5+1; value=str(Fraction(a*a,2))
                stem=rf"计算极限：\lim_{{x\to 0}}\frac{{e^{{{a}x}}-1-{a}x}}{{x^2}}=____。"
                explanation=f"二阶展开中二次项系数为{value}，故极限为{value}。"
            elif family=="determinant_2x2":
                a=3+j%5; b=2+j%4; c=1+j%3; d=5+j%6; value=str(a*d-b*c)
                stem=f"计算二阶行列式，其中第一行是{a}、{b}，第二行是{c}、{d}。"
                explanation=f"按ad-bc计算，结果为{value}。"
            elif family=="complete_tree":
                count=101+j*17; target=(count+1)//2; value=str(target)
                stem=f"一棵完全二叉树共有{count}个结点，则其叶子结点数为（ ）。"
                explanation=f"叶结点数为n-floor(n/2)，代入得到{value}。"
            elif family=="signed_range":
                bits=8+j%9; lo=-(1<<(bits-1)); hi=(1<<(bits-1))-1; value=f"[{lo}, {hi}]"
                stem=f"设机器字长为{bits}位，采用补码表示定点整数，则可表示的十进制整数范围是____（用闭区间表示）。"
                explanation=f"n位补码范围为[-2^(n-1),2^(n-1)-1]，因此区间为{value}。"
            elif family=="binary_float":
                value="-21"; stem="某 IEEE 754 单精度浮点数的 32 位十六进制表示为 C1A80000，求其表示的十进制真值。"
                explanation="符号位为1，指数为4，有效数为1.3125，故真值为-21。"
            elif family=="binary_search_steps":
                length=11+j*3; value=str(length.bit_length())
                stem=f"对长度为{length}的升序有序表进行折半查找，若所有查找均成功，则查找成功时最多需要比较的关键字个数是（ ）。"
                explanation=f"成功查找判定树最大层数为{value}，故最多比较{value}次。"
            elif family=="page_replacement_faults":
                seq="1,2,1,3,1,4" if j%2 else "1,2,3,4,1,2,5,1,2,3,4,5"
                value="4" if j%2 else "10"
                stem=f"采用LRU页面置换算法，内存有3个页框且初始为空，访问序列为{seq}，求缺页次数？"
                explanation=f"按LRU逐次更新最近访问顺序，累计缺页{value}次。"
            else:
                raise ValueError("TEST_FIXTURE unsupported registered family")
            options=None; key=value
            if qt=="single_choice":
                if family=="improper_integral_parameter":
                    options={"A":"p>1时收敛，p≤1时发散","B":"p≥1时收敛，p<1时发散",
                             "C":"对所有实数p都收敛","D":"对所有实数p都发散"}
                elif family=="signed_range":
                    lo,hi=map(int,value.strip("[]").split(","))
                    options={"A":f"[{lo},{hi}]","B":f"[{lo},{hi+1}]","C":f"[{lo+1},{hi}]","D":f"({lo},{hi}]"}
                else:
                    if family=="power_derivative":
                        options={"A":value,"B":f"{value}+1","C":f"{value}-1","D":f"{value}+2"}
                    else:
                        try:
                            exact=Fraction(value)
                            options={"A":value,"B":str(exact+1),"C":str(exact-1),"D":str(exact+2)}
                        except (ValueError,ZeroDivisionError):
                            options={"A":value,"B":"99991","C":"-99991","D":"0"}
                key="A"
            if request.get("fault")=="unsupported_proof":
                qt="proof"; options=None; key="参考证明未经过形式验证"; value=key
                stem="证明任意连续函数均存在原函数，并讨论全部边界情况。"
                explanation="本题需要一般性证明，当前注册题族不支持。"
            if request.get("fault")=="missing_condition":
                stem="计算一个未指定函数在未知区间上的定积分。"
            steps=[]
            if request.get("fault")=="wrong_answer": key="B" if key=="A" else "A"
            if request.get("fault")=="duplicate_options" and options: options["B"]=options["A"]
            if request.get("fault")=="bad_explanation": steps=[{"expression":"1+1","value":"3"}]
            return json.dumps({"stem":stem,"question_type":qt,"options":options,"correct_answer":key,
                "explanation":explanation,"final_value":value,"steps":steps},ensure_ascii=False),None
        if family=="power_derivative": stem=f"求函数 f(x)=x^{n} 在 x={t} 处的导数。"; value=str(n*t**(n-1)); explanation=f"先用幂函数求导规则得到 {n}x^{n-1}，再代入 x={t}，得到 {value}。不要把函数值误当导数值。"
        elif family=="power_integral":
            b=j%4+1; n=j%5+1; v=Fraction(b**(n+1),n+1); value=str(v)
            stem=f"计算 ∫_0^{b} x^{n} dx。"; explanation=f"原函数为 x^{n+1}/({n+1})。在上限 {b} 和下限0代入相减，结果为 {value}；不要遗漏分母 {n+1}。"
        elif family=="exp_limit": stem=f"求极限 lim(x→0) (e^({n}*x)-1)/x。"; value=str(n); explanation=f"在0的邻域内，分子等价于 {n}x，因此比值的极限是 {n}。指数中的系数不能遗漏。"
        elif family=="historic_fifth_derivative": stem=request["parent"]["stem"]; value="31e"; explanation="用莱布尼茨公式，五阶导数为 (x^2+10x+20)e^x；x=1时结果为31e。多项式的高阶导数为零，但乘积的导数不为零。"
        elif family=="complete_tree":
            count=5+j*3; stem=f"一棵有{count}个结点的完全二叉树，其叶结点数为多少？"; value=str((count+1)//2); explanation=f"按1开始编号，编号大于 floor({count}/2) 的结点没有孩子，所以叶结点数为 {value}。"
        elif family=="binary_float":
            stem="下列数中不能由 IEEE754 二进制浮点格式精确表示的是？"; value=["0.1","0.2","0.3","0.4","0.6"][j%5]; explanation=f"{value} 化成最简分数后分母含5，二进制展开不终止。其余选项的分母是2的幂且在精度范围内。"
        elif family=="signed_range":
            bits=8+j; stem=f"{bits} 位补码所能表示的整数范围是（ ）。"; value=f"−2^{bits-1} ～ 2^{bits-1}−1"; explanation=f"最高位权值为负的2^{bits-1}，其余位覆盖0到2^{bits-1}−1。因此上下限为所列范围，正负端点不对称。"
        else:
            x=0xA3+j; y=0x75; signed=x-256; delta=signed-y; wrapped=delta%256; wrapped=wrapped-256 if wrapped>=128 else wrapped
            overflow=int(not -128<=delta<=127); value=f"{wrapped}，{overflow}"
            stem=f"假设 8 位字长计算机中，带符号整数 x、y 的补码分别为 `[x]补={x:02X}H`、`[y]补=75H`，通过补码加减运算器得到 x−y 的值及 OF 标志分别为："
            explanation=f"将输入解码为带符号整数，精确差为 {delta}。按8位取模的结果为 {wrapped}，超出[-128,127]时 OF=1。"
        options=None; key=value
        if qt=="single_choice":
            if family=="binary_float": options={"A":value,"B":"1.25","C":"2.0","D":"2.5"}
            elif family=="signed_range": options={"A":f"−2^{bits} ～ 2^{bits-1}−1","B":value,"C":f"−2^{bits} ～ 2^{bits}−1","D":f"−2^{bits-1} ～ 2^{bits}−1"}
            elif family=="signed_subtract": options={"A":"24，0","B":"24，1","C":f"{wrapped}，0","D":value}
            elif family=="historic_fifth_derivative": options={"A":"31e","B":"30e","C":"29e","D":"32e"}
            else:
                v=Fraction(value); options={"A":value,"B":str(v+1),"C":str(v-1),"D":str(v+2)}
            key="B" if family=="signed_range" else "D" if family=="signed_subtract" else "A"
        fault=request.get("fault")
        if fault=="wrong_answer": key="B" if key=="A" else "A"
        if fault=="duplicate_options": options["B"]=options["A"]
        steps=[]
        if fault=="bad_explanation": steps=[{"expression":"1+1","value":"3"}]
        if fault=="unsupported_proof": qt="proof"; options=None; key="参考证明尚无独立验证"; value=key; stem="证明这个一般函数结论，并讨论成立条件。"; explanation="模拟开放题参考证明，本次没有独立证明，不应自动获得可靠判题资格。"
        return json.dumps({"stem":stem,"question_type":qt,"options":options,"correct_answer":key,"explanation":explanation,"final_value":value,"steps":steps},ensure_ascii=False),None


def run(args):
    output=safe_output(args.output_dir); source=json_input(args.inventory/"report.json"); raw=json_input(args.inventory/"inventory-snapshot.json")
    if digest(raw)!=source["inventory_snapshot_sha256"]: raise ValueError("Inventory snapshot changed")
    settings=get_settings(); engine=create_db_engine(str(settings.active_database_url))
    with create_session_factory(engine)() as db:
        db.execute(text("SET TRANSACTION READ ONLY")); before=fingerprints(db); db.rollback()
    engine.dispose()
    if before!=source["protection"]["after"] or settings.teaching_practice_enabled: raise ValueError("Development changed or feature flag is enabled")
    url=str(settings.test_database_url) if settings.test_database_url else make_url(str(settings.database_url)).set(database="kaoyan_test").render_as_string(hide_password=False)
    provider=FixtureModel(); budget=Budget(max_calls=40,max_reserved_tokens=400000)
    candidates=[]; promoted=[]; previous=settings.teaching_practice_enabled
    node_names={"power_derivative":"导数与微分的计算","power_integral":"定积分的计算","exp_limit":"函数极限的计算",
        "complete_tree":"二叉树基础","binary_float":"IEEE754 浮点表示","signed_range":"定点数编码","signed_subtract":"整数加减运算"}
    try:
        with isolated_factory(url) as (factory,schema):
            clone_inventory(factory,raw); settings.teaching_practice_enabled=True
            with factory() as db:
                nodes=list(db.scalars(select(KnowledgePoint))); qs=list(db.scalars(select(Question)))
                mapped={f:next(n for n in nodes if n.is_assessable and name in n.name) for f,name in node_names.items()}
                parents={f:next(q for q in qs if q.kp_id==n.id) for f,n in mapped.items()}
                historic=db.get(Question,UUID("e7d11002-551f-4ec5-8e2f-1a90d325bad5"))
                parent_original={q.id:snapshot(q) for q in qs}
            requests=[]
            # All 35 are explicit fixture responses, not real AI outputs.
            for family,node in mapped.items():
                for j in range(5):
                    mode="adapted" if j%2==0 else "original"
                    qt="fill_blank" if family.startswith("power") or family=="exp_limit" else "single_choice"
                    if j%2==0: qt="single_choice"
                    fault="wrong_answer" if family=="power_derivative" and j==4 else "duplicate_options" if family=="binary_float" and j==4 else "bad_explanation" if family=="signed_range" and j==4 else None
                    requests.append((node,parents[family] if mode=="adapted" else None,{"family":family,"sample":j,"mode":mode,"question_type":qt,"fault":fault}))
            requests.append((mapped["power_derivative"],historic,{"family":"historic_fifth_derivative","sample":0,"mode":"completion","question_type":"fill_blank"}))
            requests.append((mapped["power_derivative"],historic,{"family":"historic_fifth_derivative","sample":0,"mode":"adapted","question_type":"single_choice"}))
            requests.append((mapped["power_derivative"],None,{"family":"power_derivative","sample":0,"mode":"original","question_type":"proof","fault":"unsupported_proof"}))
            for number,(node,parent,request) in enumerate(requests):
                if parent: request["parent"]={"stem":parent.stem,"question_type":parent.question_type,"options":parent.options,"knowledge_point":node.name}
                response,trace=generate(provider,request,budget,max_retries=0)
                candidate=assess_output(response,node,request_id=f"C1_SIMULATED_FIXTURE-{number}",mode=request["mode"],family=request["family"],parent=parent,trace=trace)
                candidates.append(candidate)
                if candidate["status"]=="AUTO_PASS":
                    with factory.begin() as db:
                        q,status=promote(db,candidate,db.get(KnowledgePoint,node.id)); promoted.append({"id":str(q.id),"status":status})
                        _,replay=promote(db,candidate,db.get(KnowledgePoint,node.id))
                        if replay!="NOOP": raise ValueError("Question idempotency failed")
            with factory() as db:
                baseline_eligible=sum(question_eligibility(q,db.get(KnowledgePoint,q.kp_id),teaching_enabled=False).practice_eligible for q in db.scalars(select(Question)))
                on_eligible=sum(question_eligibility(q,db.get(KnowledgePoint,q.kp_id),teaching_enabled=True).practice_eligible for q in db.scalars(select(Question)))
                from backend.services.question_generation import generation_hash
                actual_ids=[r["id"] for r in promoted]
            # Shared actual REST/Attempt/progress/Agent tool regression from B3.
            business=business_check(factory,actual_ids,None)
            with factory() as db:
                assert len(list(db.scalars(select(KpMasteryPolicy))))==284
                assert all(question_eligibility(q,db.get(KnowledgePoint,q.kp_id),teaching_enabled=True).evidence_capability!="verified_objective" for q in db.scalars(select(Question)))
                assert all(snapshot(db.get(Question,k))==v for k,v in parent_original.items() if str(k) not in actual_ids)
            result={"status":"PHASE45C1_SIMULATION_ONLY","generation_version":GENERATION_VERSION,"schema":schema,
                "simulated_candidates":len(candidates),"real_model_candidates":0,"real_model_calls":0,"observed_real_usage":None,"model_cost":0,
                "status_counts":{s:sum(c["status"]==s for c in candidates) for s in ("AUTO_PASS","REJECTED","NEEDS_EVIDENCE")},
                "path_counts":{s:sum(c["mode"]==s for c in candidates) for s in ("completion","adapted","original")},
                "promoted_in_isolation":len(promoted),"isolated_flag_off_eligible":baseline_eligible,"isolated_flag_on_eligible":on_eligible,
                "development_activated":0,"budget":{"calls":budget.calls,"reserved_token_ceiling":budget.reserved_tokens,"records":budget.records},
                "candidates":[{k:v for k,v in c.items() if k!="question"} for c in candidates],"promoted":promoted,"business":business,
                "history":"Only new test attempts; no development learner history copied","strict_policy_changed":False,
                "remaining_limits":"Narrative explanation is reference; unsupported proofs withheld; no true model quality evidence"}
            result["idempotency_verified"]=True
    finally: settings.teaching_practice_enabled=previous
    engine=create_db_engine(str(settings.active_database_url))
    with create_session_factory(engine)() as db:
        db.execute(text("SET TRANSACTION READ ONLY")); after=fingerprints(db); db.rollback()
    engine.dispose()
    if before!=after: raise ValueError("Development fingerprint drift")
    result["protection"]={"before":before,"after":after,"equal":True,"schema_removed":True,"production_flag":settings.teaching_practice_enabled}
    output.mkdir(parents=True,exist_ok=False)
    (output/"report.json").write_text(json.dumps(result,ensure_ascii=False,indent=2,default=str),encoding="utf-8")
    lines=["# C1模拟候选试点（不是实际AI生成）","",f"候选{len(candidates)}，隔离晋级{len(promoted)}，真实模型调用0，开发库写入0。", "", "| 候选ID | 路径 | 结果 | 错误 | 用途 |","|---|---|---|---|---|"]
    for c in candidates: lines.append(f"| {c['candidate_id']} | {c['mode']} | {c['status']} | {', '.join(c['errors'])} | {c['quality']['primary_use']} |")
    (output/"report.md").write_text("\n".join(lines)+"\n",encoding="utf-8")
    print(json.dumps({k:v for k,v in result.items() if k not in {"candidates","budget","business","protection","promoted"}},ensure_ascii=False,indent=2)); return result


if __name__=="__main__":
    if hasattr(sys.stdout,"reconfigure"):sys.stdout.reconfigure(encoding="utf-8")
    p=argparse.ArgumentParser(description=__doc__); p.add_argument("--inventory",type=Path); p.add_argument("--output-dir",type=Path)
    p.add_argument("--inspect-report",type=Path);p.add_argument("--kp-code")
    args=p.parse_args()
    if args.inspect_report:
        report=json_input(args.inspect_report)
        selected=[c for c in report["candidates"] if not args.kp_code or c["record"]["node_code"]==args.kp_code]
        print(json.dumps(selected,ensure_ascii=False,indent=2))
    else:
        if not args.inventory or not args.output_dir:p.error("--inventory and --output-dir required for isolated simulation")
        run(args)
