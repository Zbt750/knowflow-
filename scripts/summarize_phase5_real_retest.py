"""Offline evidence aggregation; no network, database or model calls."""
import hashlib
import json
from collections import Counter
from pathlib import Path
import statistics
import struct
import sympy as sp

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/"storage/quality-audits/phase5-ai-real-retest-20261015-v1"


def load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def main():
    run=load(OUT/"case-results.json")
    ledger=load(OUT/"provider-ledger.json")
    original=load(ROOT/"storage/quality-audits/phase5-closeout-execution-20261015/final-ai-eval-scores.json")
    old={r["id"]:r for r in original["cases"]}
    # Explicit semantic review against the unchanged rubric, not keyword scoring.
    reviewed={
        "Q01":("PASS","极限1/3；有限泰勒余项、定义域与收敛级数的使用条件正确。"),
        "Q02":("PASS","分部积分与多项式除法正确，积分1/4。"),
        "Q03":("PASS","p>1收敛且1/(p-1)^2；p=1及p<1发散论证正确。"),
        "Q04":("PASS","行列式(a-1)^2、秩1/3、无秩2，以及方程组解分类正确。"),
        "Q05":("PASS","n0=5,n=13推出n2=4,n1=4，未添加满树条件。"),
        "Q06":("PASS","无符号128、原码负零、补码-128及对应表示范围正确。"),
        "Q07":("PASS","完整输出binary32=1.5，字段划分、指数偏置与隐含首位适用条件正确；无截断。"),
        "Q13":("PASS","A=I+N,N^2=0，A^n=I+nN，归纳验证正确。"),
        "Q14":("PASS","正确沿用同会话A；det=1，特征值1二重，特征空间维数1；无库存误路由。"),
        "Q15":("PASS","沿用Q13/Q14，正确区别A和I的几何重数与可对角化性。"),
        "A03":("PASS","真实工具核验无学习历史、目标范围库存0；提供讲解建议，未自动出题或写卷。"),
        "A06":("PASS","工具确认无客观作答历史，区分自述与证据，并按真实库存给出起步练习建议。"),
        "A04":("FAIL","未再次声称全库AI，但真实verified_objective错误被learning_progress及回答降为不可靠参考比对；核心证据可靠性错误。"),
        "A09":("FAIL","三次作答/一道题计数和11<=20分钟约束已修复；仍把三次verified_objective错误说成不可靠参考答案观察，证据分类错误。"),
        "A10":("PARTIAL","正常规划，无生题误判；承认后续独立正确及1次verified_objective确认，草案11<=15且未写卷；同时使用矛盾的参考答案/可靠性措辞。"),
        "A12":("PARTIAL","调用学习证据工具，正确识别hint_1辅助且独立答对0；最终仍对AUTO_VERIFIED公共题使用AI参考题说明，可靠性表达不一致。"),
        "A13":("FAIL","识别先错/解析后正确/后来独立正确，但读模型把已记录verified_objective完成仍降成参考观察，未可靠呈现该题真正完成；草案时间及确认边界正常。"),
        "A18":("PARTIAL","服务端拦截了原始模型全部AI来源断言，最终来源样本分类正确、无写卷；替代回复丢失用户要求的填空、20分钟与具体已校验安排。"),
    }
    scored=[]
    for row in run["results"]:
        cid=row["id"]
        outcome={"id":cid,"track":row["track"],"original_score":old[cid]["score"],"original_reason":old[cid]["reason"],
            "generation_status":row["status"],"quality_score":None,"physical_requests":row.get("provider_requests",0),
            "evidence_directory":str((OUT/cid).relative_to(ROOT)),"model_called":row.get("provider_requests",0)>0}
        if row["status"]=="COMPLETED":
            outcome["quality_score"],outcome["reason"]=reviewed[cid]
        elif row["status"]=="FIXTURE_BLOCKED":
            outcome["reason"]=row["reason"]
        elif row["status"]=="BUDGET_STOPPED":
            outcome.update(generation_status="NOT_EXECUTED_AFTER_SAFETY_STOP",reason=row["reason"])
        elif cid=="Q08":
            outcome.update(generation_status="PROVIDER_ERROR_USAGE_UNKNOWN",reason="第61次物理请求ConnectError，未返回HTTP状态或usage；全局停止，恢复请求未发送。")
        else:
            task=load(OUT/cid/"agent-task.json")
            last=task["metrics"]["calls"][-1]
            assert last.get("exception_type")=="BudgetStop"
            outcome.update(generation_status="BUDGET_STOPPED_SINGLE_REQUEST_INPUT",reason="工具上下文超过单请求64000保守输入预留，下一轮发送前被阻止；页面仍呈通用generation_failed。",blocked_prompt_chars=last.get("prompt_chars"))
        if row["track"]=="agent" and (OUT/cid/"truth-before.json").exists():
            before=load(OUT/cid/"truth-before.json");after=load(OUT/cid/"truth-after.json")
            outcome["history_protection"]={"state_equal":before["state"]==after["state"],"counts_equal":before["counts"]==after["counts"],"attempts_equal":before["attempts"]==after["attempts"]}
            assert all(outcome["history_protection"].values())
        scored.append(outcome)
    assert len(scored)==40 and len({r["id"] for r in scored})==40
    assert len(ledger["requests"])==61==sum(r["physical_requests"] for r in scored)
    assert [r["number"] for r in ledger["requests"]]==list(range(1,62))
    assert all(r["request_model"]=="deepseek-flash" for r in ledger["requests"])
    for r in ledger["requests"]:
        assert "authorization" not in r.get("request",{})
    tracks={}
    for track in ("qa","agent"):
        rows=[r for r in scored if r["track"]==track]
        counts=Counter(r["quality_score"] or "UNRATED" for r in rows)
        calls=[r for r in ledger["requests"] if r["case_id"].startswith("Q" if track=="qa" else "A")]
        tracks[track]={"cases":20,"completed_answers":sum(r["generation_status"]=="COMPLETED" for r in rows),
            "pass":counts["PASS"],"partial":counts["PARTIAL"],"fail":counts["FAIL"],"unrated":counts["UNRATED"],
            "pass_rate_all":counts["PASS"]/20,"pass_or_partial_rate_all":(counts["PASS"]+counts["PARTIAL"])/20,
            "physical_requests":len(calls),"input_tokens_observed":sum(r.get("usage",{}).get("prompt_tokens",0) for r in calls),
            "output_tokens_observed":sum(r.get("usage",{}).get("completion_tokens",0) for r in calls),
            "mean_physical_request_latency_seconds":round(statistics.mean(r["latency_seconds"] for r in calls),3)}
    x,p,a=sp.symbols("x p a", real=True)
    matrix=sp.Matrix([[1,1,1],[1,a,1],[1,1,a]])
    oracle={"method":"local symbolic/exact calculation + semantic review, no paid judge; not human_verified",
        "Q01":str(sp.limit((sp.log(1+x)-x+x*x/2)/(x**3),x,0)),
        "Q02":str(sp.integrate(x*sp.log(1+x),(x,0,1))),
        "Q03_p2":str(sp.integrate(sp.log(x)/(x*x),(x,1,sp.oo))),
        "Q04_determinant":str(sp.factor(matrix.det())),
        "Q05": {"n2":5-1,"n1":13-5-(5-1)},
        "Q06":{"unsigned":int("10000000",2),"twos_complement":int("10000000",2)-256,"sign_magnitude":"negative zero"},
        "Q07":struct.unpack(">f",bytes.fromhex("3fc00000"))[0],
        "Q14":{"determinant":sp.Matrix([[1,1],[0,1]]).det().__str__(),"eigenspace_dimension":len((sp.Matrix([[1,1],[0,1]])-sp.eye(2)).nullspace())}}
    known=ledger["summary"]
    unknown=[r for r in ledger["requests"] if r["state"]!="COMPLETED_USAGE_OBSERVED"]
    observed_peak=sum((r.get("usage",{}).get("prompt_tokens",0)*2+r.get("usage",{}).get("completion_tokens",0)*8)/1000000 for r in ledger["requests"])
    result={"status":"PHASE5_AI_REAL_RETEST_INCOMPLETE_NOT_ACCEPTED","source_dataset":"phase5-closeout-v1",
        "original_scores_unchanged":True,"runtime_sha256":load(OUT/"runtime-version.json")["runtime_sha256"],
        "tracks":tracks,"case_ids_with_real_requests":sum(r["model_called"] for r in scored),
        "usage":{**known,"observed_total_tokens":known["input_tokens"]+known["output_tokens"],
            "observed_peak_uncached_estimate_cny":round(observed_peak,6),"unknown_usage_reservation_cny":round(sum(r["conservative_cny"] for r in unknown),6),
            "peak_cache_aware_observed_estimate_cny":round(sum(r.get("peak_cache_aware_estimate_cny",0) for r in ledger["requests"]),6)},
        "stop_reason":run["stop_reason"],"finish_reason_counts":dict(Counter(r.get("finish_reason") or "UNKNOWN" for r in ledger["requests"])),
        "serious_content_issues":["A04/A09/A13: AUTO_VERIFIED verified_objective evidence downgraded to reference-only by learning_progress projection; no historical records changed"],
        "intercepted_raw_model_issues":["A18: all-AI source claim corrected before display; replacement response lost actionable detail"],
        "unconfirmed_plan_writes":0,"cases":scored,"oracle":oracle,
        "frozen_files_sha256":{str(f.relative_to(ROOT)):hashlib.sha256(f.read_bytes()).hexdigest() for f in (ROOT/"eval/phase5-closeout-v1").rglob("*") if f.is_file()}}
    (OUT/"retest-scores.json").write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps({"tracks":tracks,"usage":result["usage"],"stop":result["stop_reason"],"finish_reasons":result["finish_reason_counts"]},ensure_ascii=False,indent=2))


if __name__=="__main__":main()
