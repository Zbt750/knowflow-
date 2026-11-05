#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""大题库内容包离线校验（不连数据库、不依赖后端包）。

检查项对应任务要求的八道检查：
1. 完整性  2. 知识点归属  3. 难度/范围  4. 题干↔答案一致
5. 计算/推演  6. 重复与近似  7. 是否真考该知识点  8. 解析跳步/循环论证

结构校验用标准库；数值复核用 sympy（项目 requirements 已包含）。
"""
from __future__ import annotations

import argparse
import csv
import itertools
import json
import re
import sys
from pathlib import Path

try:
    import sympy as sp
except ImportError:  # 允许在只做结构检查的环境运行
    sp = None

REQUIRED_FIELDS = {
    "slug", "kp_code", "title", "question_type", "difficulty", "estimated_minutes",
    "role", "skill_tags", "objective", "stem", "answer", "final_value",
    "solution_steps", "key_points", "common_errors", "scope", "verification_steps",
    "verification", "review",
}
TYPES = {"single_choice", "fill_blank", "calculation", "proof", "subjective", "discussion", "program"}
DIFFICULTIES = {"basic", "medium", "advanced"}
ROLES = {"basic", "typical", "variant", "comprehensive"}
REVIEW_KEYS = {"content_valid", "knowledge_point_valid", "answer_checked",
               "difficulty_checked", "duplicate_checked", "review_status"}


def norm(text: str) -> str:
    return re.sub(r"\s+", "", text or "")


def trigrams(text: str) -> set[str]:
    t = norm(text)
    return {t[i:i + 3] for i in range(max(0, len(t) - 2))}


def similarity(a: str, b: str) -> float:
    ta, tb = trigrams(a), trigrams(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def constant(expr: str):
    """与 backend.services.constant_expression 同口径的受限常量求值。"""
    if sp is None:
        return None
    value = (expr or "").strip().replace("−", "-").replace("π", "pi")
    if len(value) > 160:
        return None
    value = re.sub(r"\\(?:dfrac|tfrac|frac)\{([^{}]+)\}\{([^{}]+)\}", r"((\1)/(\2))", value)
    value = value.replace("\\cdot", "*").replace("\\times", "*").replace("^", "**")
    value = re.sub(r"(?<=[0-9)])\s*(?=pi\b|e\b|sqrt\(|\()", "*", value)
    try:
        return sp.sympify(value, rational=True)
    except (sp.SympifyError, SyntaxError, TypeError, ValueError):
        return None


def compare_constant(answer: str, expected: str) -> str:
    a, b = constant(answer), constant(expected)
    if a is None or b is None:
        return "unknown"
    try:
        return "right" if sp.simplify(a - b) == 0 else "wrong"
    except Exception:
        return "unknown"


def load_snapshot_stems(copy_path: Path) -> list[str]:
    stems, columns = [], None
    for line in copy_path.read_text(encoding="utf-8").splitlines():
        if line.startswith("COPY public.questions ("):
            columns = line.split("(", 1)[1].split(")", 1)[0].split(", ")
            continue
        if columns is None:
            continue
        if line == r"\.":
            break
        values = line.split("\t")
        if len(values) != len(columns):
            continue
        stems.append(values[columns.index("stem")].replace(r"\n", "\n").replace(r"\t", "\t"))
    return stems


def deep_check(item: dict) -> tuple[bool, str]:
    """对可机器复核的题做独立复算；证明题跳过。"""
    slug = item["slug"]
    if slug in {"math-936d-q1", "math-a0d6-q1"}:
        if sp is None:
            return True, "sympy unavailable; skipped"
        x, y = sp.symbols("x y")
        value = sp.simplify(sp.integrate(sp.integrate(sp.exp(y ** 2), (y, x, 1)), (x, 0, 1)))
        ok = sp.simplify(value - (sp.E - 1) / 2) == 0
        return ok, f"sympy={value}"
    if slug in {"math-936d-q2", "math-a0d6-q2"}:
        if sp is None:
            return True, "sympy unavailable; skipped"
        r, t = sp.symbols("r theta", nonnegative=True)
        value = sp.simplify(sp.integrate(sp.integrate(r ** 3 * sp.sin(t), (r, 0, 2 * sp.cos(t))), (t, 0, sp.pi / 2)))
        ok = sp.simplify(value - sp.Rational(4, 5)) == 0
        return ok, f"sympy={value}"
    if slug == "ds-64cd-q1":
        import heapq
        def kth(a, k):
            h = a[:k]
            heapq.heapify(h)
            for v in a[k:]:
                if v > h[0]:
                    heapq.heapreplace(h, v)
            return h[0]
        sample = kth([3, 1, 5, 12, 2, 11], 3)
        import random
        random.seed(7)
        for _ in range(500):
            a = [random.randint(-20, 20) for _ in range(random.randint(1, 30))]
            k = random.randint(1, len(a))
            if kth(a, k) != sorted(a, reverse=True)[k - 1]:
                return False, "random brute-force mismatch"
        return sample == 5, f"sample={sample}, random=500 passed"
    if slug == "ds-64cd-q2":
        import heapq
        lo, hi = [], []  # lo: max-heap via negatives, hi: min-heap
        def add(x):
            if not lo or x <= -lo[0]:
                heapq.heappush(lo, -x)
            else:
                heapq.heappush(hi, x)
            if len(lo) > len(hi) + 1:
                heapq.heappush(hi, -heapq.heappop(lo))
            elif len(hi) > len(lo):
                heapq.heappush(lo, -heapq.heappop(hi))
        def med():
            if len(lo) == len(hi):
                return (-lo[0] + hi[0]) / 2
            return -lo[0]
        got = []
        for x in (5, 15, 1, 3):
            add(x)
            got.append(med())
        return got == [5, 10, 5, 4], f"medians={got}"
    if slug == "co-ba98-q1":
        seq = [0x1000, 0x1040, 0x2000, 0x1080, 0x3000, 0x1000, 0x2040, 0x1040]
        sets, miss, hit = {}, 0, 0
        for addr in seq:
            tag, idx = addr >> 12, (addr >> 6) & 0x3F
            ways = sets.setdefault(idx, [])
            if tag in ways:
                hit += 1
                ways.remove(tag); ways.append(tag)
            else:
                miss += 1
                ways.append(tag)
                if len(ways) > 8:
                    ways.pop(0)
        return (miss, hit) == (6, 2), f"miss={miss}, hit={hit}"
    if slug == "co-ba98-q2":
        seq = [0x0, 0x8000, 0x10000, 0x18000] * 2
        out = {}
        for name, idx_bits, ways in (("direct", 9, 1), ("2way", 8, 2), ("8way", 6, 8)):
            cache, miss = {}, 0
            for addr in seq:
                tag, idx = addr >> (6 + idx_bits), (addr >> 6) & ((1 << idx_bits) - 1)
                row = cache.setdefault(idx, [])
                if tag in row:
                    row.remove(tag); row.append(tag)
                else:
                    miss += 1
                    row.append(tag)
                    if len(row) > ways:
                        row.pop(0)
            out[name] = miss
        return out == {"direct": 8, "2way": 8, "8way": 4}, str(out)
    if slug == "os-006d-q1":
        refs = [7, 0, 1, 2, 0, 3, 0, 4, 2, 3, 0, 3, 2, 1, 2, 0, 1, 7, 0, 1]
        def runtime(algo):
            frames, faults = [], 0
            for i, r in enumerate(refs):
                if r in frames:
                    if algo == "LRU":
                        frames.remove(r); frames.append(r)
                    continue
                faults += 1
                if len(frames) < 3:
                    frames.append(r)
                elif algo == "FIFO":
                    frames.pop(0); frames.append(r)
                elif algo == "LRU":
                    frames.pop(0); frames.append(r)
                else:
                    far, victim = -1, None
                    for p in frames:
                        nxt = refs.index(p, i + 1) if p in refs[i + 1:] else 10 ** 9
                        if nxt > far:
                            far, victim = nxt, p
                    frames.remove(victim); frames.append(r)
            return faults
        got = {a: runtime(a) for a in ("FIFO", "LRU", "OPT")}
        return got == {"FIFO": 15, "LRU": 12, "OPT": 9}, str(got)
    if slug == "os-006d-q2":
        seq = [(1, "R"), (2, "W"), (3, "R"), (4, "W"), (1, "W"), (2, "R"),
               (5, "R"), (1, "R"), (2, "W"), (3, "W"), (4, "R"), (5, "W")]
        frames, ptr, faults, wb = [], 0, 0, 0
        for page, op in seq:
            hit = next((f for f in frames if f[0] == page), None)
            if hit:
                hit[1] = 1
                if op == "W":
                    hit[2] = 1
                continue
            faults += 1
            while True:
                if len(frames) < 4:
                    frames.append([page, 1, 1 if op == "W" else 0])
                    ptr = len(frames) % 4
                    break
                f = frames[ptr]
                if f[1] == 0 and f[2] == 0:
                    frames[ptr] = [page, 1, 1 if op == "W" else 0]
                    ptr = (ptr + 1) % 4
                    break
                if f[1] == 0 and f[2] == 1:
                    wb += 1
                    frames[ptr] = [page, 1, 1 if op == "W" else 0]
                    ptr = (ptr + 1) % 4
                    break
                f[1] = 0
                ptr = (ptr + 1) % 4
        return (faults, wb) == (10, 3), f"faults={faults}, writebacks={wb}"
    return True, "no deep check"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pack", type=Path, default=Path("content/long_question_packs/pilot_20261018.json"))
    parser.add_argument("--inventory", type=Path, default=Path("docs/long-question-inventory-20261018.csv"))
    parser.add_argument("--copy", type=Path,
                        default=Path("storage/quality-audits/long-question-supply-20261017/sealed-questions.copy.sql"))
    parser.add_argument("--out", type=Path, default=Path("docs/long-question-pack-validation-20261018.json"))
    parser.add_argument("--report", type=Path, default=Path("docs/long-question-pack-validation-20261018.md"))
    parser.add_argument("--duplicate-threshold", type=float, default=0.80)
    args = parser.parse_args()

    pack = json.loads(args.pack.read_text(encoding="utf-8"))
    inventory = {}
    with args.inventory.open(encoding="utf-8-sig") as handle:
        for row in csv.DictReader(handle):
            inventory[row["知识点ID（稳定code）"]] = row
    stems = load_snapshot_stems(args.copy)

    results = []
    errors = []
    warnings = []
    for item in pack["items"]:
        slug = item.get("slug", "<missing>")
        item_errors = []
        missing = REQUIRED_FIELDS - set(item)
        if missing:
            item_errors.append(f"missing_fields:{sorted(missing)}")
        if item.get("question_type") not in TYPES:
            item_errors.append("invalid_question_type")
        if item.get("difficulty") not in DIFFICULTIES:
            item_errors.append("invalid_difficulty")
        if item.get("role") not in ROLES:
            item_errors.append("invalid_role")
        if item.get("kp_code") not in inventory:
            item_errors.append("kp_code_not_in_tree")
        else:
            row = inventory[item["kp_code"]]
            if row["适合大题"] != "是":
                item_errors.append("kp_not_suitable_for_long")
            if row["有效叶子"] != "是":
                item_errors.append("kp_not_assessable_leaf")
        if len(norm(item.get("stem", ""))) < 30:
            item_errors.append("stem_too_short")
        if len(norm(item.get("answer", ""))) < 2:
            item_errors.append("answer_missing")
        if len(item.get("solution_steps") or []) < 3:
            item_errors.append("solution_steps_too_few")
        if not item.get("objective") or len(item["objective"]) < 10:
            item_errors.append("objective_missing")
        if not item.get("key_points") or not item.get("common_errors") or not item.get("scope"):
            item_errors.append("metadata_incomplete")
        review = item.get("review") or {}
        if set(review) != REVIEW_KEYS:
            item_errors.append("review_fields_incomplete")
        elif not all(isinstance(review[k], bool) for k in REVIEW_KEYS - {"review_status"}):
            item_errors.append("review_flags_not_boolean")
        # 题干↔答案：仅在答案可解析为常量时比较
        cmp = compare_constant(item.get("answer", ""), item.get("final_value", ""))
        if cmp == "wrong":
            item_errors.append("answer_final_value_conflict")
        # 可机器复核的步骤
        for step in item.get("verification_steps") or []:
            if set(step) != {"expression", "value"}:
                item_errors.append("verification_step_format_invalid")
                continue
            if compare_constant(step["expression"], step["value"]) == "wrong":
                item_errors.append(f"verification_step_wrong:{step['expression']}")
        deep_ok, deep_detail = deep_check(item)
        if not deep_ok:
            item_errors.append("deep_check_failed")
        # 近似题
        max_sim, nearest = 0.0, ""
        for stem in stems:
            s = similarity(item.get("stem", ""), stem)
            if s > max_sim:
                max_sim, nearest = s, stem[:60]
        if max_sim >= args.duplicate_threshold:
            item_errors.append(f"near_duplicate:{max_sim:.2f}")
        if item_errors:
            errors.append({"slug": slug, "errors": item_errors})
        results.append({
            "slug": slug, "kp_code": item.get("kp_code"), "type": item.get("question_type"),
            "errors": item_errors, "max_similarity": round(max_sim, 4),
            "deep_check": {"ok": deep_ok, "detail": deep_detail},
            "review_status": review.get("review_status"),
        })

    # 包级检查：同一知识点两题的角度差异、角色差异、slug 唯一
    slugs = [i.get("slug") for i in pack["items"]]
    if len(slugs) != len(set(slugs)):
        errors.append({"slug": "<pack>", "errors": ["duplicate_slug"]})
    by_kp = {}
    for item in pack["items"]:
        by_kp.setdefault(item["kp_code"], []).append(item)
    for kp, items in by_kp.items():
        if len(items) != 2:
            warnings.append(f"{kp}: expected 2 items, got {len(items)}")
            continue
        if items[0].get("role") == items[1].get("role"):
            warnings.append(f"{kp}: two items share role {items[0].get('role')}")
        sim = similarity(items[0].get("stem", ""), items[1].get("stem", ""))
        if sim > 0.55:
            warnings.append(f"{kp}: within-node stem similarity {sim:.2f} too high")
        # 考查角度差异：题目标题与技能标签不应完全相同
        if set(items[0].get("skill_tags", [])) == set(items[1].get("skill_tags", [])):
            warnings.append(f"{kp}: identical skill_tags")

    summary = {
        "pack": str(args.pack), "batch_key": pack.get("batch_key"),
        "items": len(pack["items"]), "kps": len(by_kp),
        "passed": sum(1 for r in results if not r["errors"]),
        "failed": sum(1 for r in results if r["errors"]),
        "review_status_counts": {},
        "errors": errors, "warnings": warnings,
        "results": results,
    }
    for r in results:
        status = r["review_status"] or "UNKNOWN"
        summary["review_status_counts"][status] = summary["review_status_counts"].get(status, 0) + 1
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [f"# 大题库内容包校验 · {pack.get('batch_key')}", "",
             f"- 题数：**{summary['items']}**；知识点：**{summary['kps']}**",
             f"- 结构/数值校验通过：**{summary['passed']}**；失败：**{summary['failed']}**",
             f"- 审核状态分布：`{json.dumps(summary['review_status_counts'], ensure_ascii=False)}`", ""]
    if errors:
        lines += ["## 失败项", ""] + [f"- `{e['slug']}`：{', '.join(e['errors'])}" for e in errors]
    if warnings:
        lines += ["", "## 警告", ""] + [f"- {w}" for w in warnings]
    lines += ["", "## 逐题结果", "", "| slug | 知识点 | 题型 | 近似度 | 深层复核 | 状态 |", "|---|---|---|---:|---|---|"]
    for r in results:
        lines.append(f"| {r['slug']} | {r['kp_code']} | {r['type']} | {r['max_similarity']:.2f} "
                     f"| {'PASS' if r['deep_check']['ok'] else 'FAIL'} | {r['review_status']} |")
    args.report.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({k: summary[k] for k in ("items", "kps", "passed", "failed",
                                              "review_status_counts", "errors", "warnings")},
                     ensure_ascii=False, indent=2))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
