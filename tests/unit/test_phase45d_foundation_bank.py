"""Synthetic tests for the bounded Phase 4.5D candidate registry."""
from types import SimpleNamespace

from backend.services.question_generation import assess_output, current_generation_binding
from backend.services.question_quality import duplicates
from scripts.run_phase45d_foundation_pilot import NODES, specs_for


NODE_NAMES = {
    "math.exam.de439863790e":"导数与微分的计算",
    "math.exam.c431f98f817c":"定积分的计算",
    "math.exam.c5c672022b7f":"函数极限的计算",
    "math.exam.fd2f9e3739d9":"反常积分的计算与敛散性",
    "math.exam.f4e5ed0360ea":"行列式",
    "math.exam.c106a40cda48":"线性方程组",
    "cs408.co.topic.324b03e7b481":"定点数编码（原/反/补/移）",
    "cs408.ds.topic.1efaf3d00b50":"二叉树基础（性质+存储）",
    "cs408.ds.topic.8b04b55a0408":"折半/二分查找",
    "cs408.os.topic.006da51a6b0f":"页面置换算法",
    "cs408.cn.topic.7789c3d9d6f7":"子网划分 / 子网掩码 / CIDR / NAT",
    "cs408.os.topic.bc235cd7a2fb":"CPU调度算法",
}


def test_all_bounded_foundation_specs_pass_independent_verifier_and_generation_binding():
    counts={}
    type_mixes={}
    for item in NODES:
        code=item["code"]
        node=SimpleNamespace(id=code,code=code,name=NODE_NAMES[code],
            subject="408" if code.startswith("cs408.") else "考研数学",
            is_active=True,is_assessable=True,is_reference_only=True)
        built=[]
        for index,spec in enumerate(specs_for(code,{})):
            candidate=assess_output(spec["output"],node,request_id=f"TEST_FIXTURE:{code}:{index}",
                mode=spec["mode"],family=spec["family"],parent=spec.get("parent"),
                trace={"mode":"codex_assisted","model":"TEST_FIXTURE deterministic authoring","model_calls":0})
            assert candidate["status"]=="AUTO_PASS", (code,spec["family"],candidate["errors"],candidate["record"]["independent_verification"])
            assert current_generation_binding(candidate["question"],node)
            assert candidate["question"].answer_verification_event_id is None
            assert candidate["record"]["real_model_called"] is False
            assert candidate["record"]["model_calls"]==0
            built.append(candidate["question"])
        assert len(built)>=item["target"]
        duplicate_index=duplicates(built)
        assert all(not entry["exact"] for entry in duplicate_index.values())
        counts[code]=len(built)
        type_mixes[code]={kind:sum(q.question_type==kind for q in built)
            for kind in {q.question_type for q in built}}
    assert len(counts)==12
    assert type_mixes["cs408.co.topic.324b03e7b481"].get("fill_blank",0)>=5
    assert type_mixes["cs408.ds.topic.1efaf3d00b50"].get("fill_blank",0)>=5
