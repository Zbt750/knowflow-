"""意图冲突诊断（R22）。

只读诊断：不改变 route_message 的业务结果，仅记录候选规则、最终规则、
被否决的候选与原因，供测试与排查使用。输入不落库、不写日志正文。
"""

from __future__ import annotations

import re

from backend.services.assistant_router import assistance_action, route_message

# (规则 ID, 优先级, 命中正则, 目标意图, 是否写操作)
_CANDIDATES = [
    ("negation", 1, r"不要|别|先不|暂不|不用|无需", "qa / data_query(只读)", False),
    ("cancel", 2, r"(?:取消|撤回).{0,12}(?:安排|方案|需求|刚才|上次|这个操作|操作)", "qa/practice_request_cancel", False),
    ("append_generated", 3, r"(?:把|将)?刚才(?:生成的|那道|这)(?:道)?(?:题|练习).{0,10}(?:加入|放进|加到)", "planner/plan", False),
    ("compound_retrieve", 4, r"先.{0,8}(?:检索|找|查).{0,14}(?:再|然后).{0,8}(?:加|追|补|来)", "data_query/find", False),
    ("continue_scope", 5, r"(?:继续|沿用|按照|按).{0,10}(?:刚才的|当前|今天的)?.{0,6}(?:推荐范围|推荐)", "planner/plan", False),
    ("material_generation", 6, r"(?:根据|按照|用).{0,8}(?:这份|这篇|该)?.{0,6}(?:资料|笔记|PDF|文档|材料).{0,10}(?:出|生成|出题)", "generation/generate", True),
    ("bank_query", 7, r"题库|查(?:一下|查).{0,14}题|找(?:一|几)?道.{0,6}(?:类似|同类型)?的?题", "data_query", False),
    ("generation", 8, r"生成|出一道|出题|新编|变式|再来一道|编一道", "generation/generate", True),
    ("explain", 9, r"解释|讲解|怎么做|为什么|讲讲|解析", "qa", False),
    ("today_progress", 10, r"今天.{0,8}(?:学了|完成|做了|进度)|今日.{0,6}进度", "data_query/today_summary", False),
    ("evidence", 11, r"掌握度|毕业|凭什么|判断依据|证据", "qa / data_query/evidence_basis", False),
    ("deferral", 12, r"明天|改天|先不做|先不学|休息", "qa/deferral_request_not_supported", False),
    ("workload", 13, r"减少|少一点|太多|降低题量|时间不够", "planner/modify", False),
]


def diagnose_route(message: str, ctx) -> dict:
    """返回真实路由结果 + 命中候选与被否决候选。"""
    route = route_message(message, ctx)
    action = assistance_action(message, explicit="auto", question_present=True)
    hits = []
    for rule_id, priority, pattern, intent, writes in _CANDIDATES:
        if re.search(pattern, message):
            hits.append({"rule": rule_id, "priority": priority, "intent": intent, "writes": writes})
    final = f"{route.capability}/{route.intent}"
    excluded = [
        {"rule": h["rule"], "reason": "优先级低于最终规则" if h["priority"] > (hits[-1]["priority"] if hits else 99) else "与最终规则同域但被否决"}
        for h in hits if not final.startswith(h["intent"].split("/")[0])
    ]
    has_negation = any(h["rule"] == "negation" for h in hits)
    conflicts = [
        {"rule": h["rule"], "intent": h["intent"], "reason": "候选被更高优先级规则覆盖"}
        for h in hits if h["rule"] != (hits[0]["rule"] if hits else "") and final != h["intent"]
    ]
    return {
        "final_intent": final,
        "final_rule": route.reason,
        "write_risk": route.write_risk,
        "action": action,
        "candidates": hits,
        "excluded": excluded,
        "has_negation": has_negation,
        "conflict": bool(conflicts),
        "conflicts": conflicts,
        "needs_confirmation": route.write_risk or action is not None,
    }
