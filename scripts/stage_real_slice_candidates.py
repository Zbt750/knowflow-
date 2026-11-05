"""Stage bounded third-party text candidates locally; never import or verify.

Pinned sources, explicit existing node pointers, immutable intake outputs. Public
availability does not establish redistribution permission or answer correctness.
"""
import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
import sys
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.audit_real_learning_slices import SLICE_SCOPES

CS_URL = "https://raw.githubusercontent.com/Become-ILLUSORY/408-quiz/81329e467a29043f4357b439e22bc2930132fea1/questions.json"
MATH_URL = "https://raw.githubusercontent.com/TsekaLuk/Kaoyan-Math2-Papers/fd42c56eed412cce0cb97d6bd688f314c78e542e/solutions/2024/math2_2024.md"


def scoped_refs(references, subject):
    scope = SLICE_SCOPES["binary_tree" if subject == "408" else "integral"]
    codes = {scope["primary"], *scope["related"]}
    indexed = {}
    for r in references:
        if r["knowledge_point_code"] in codes:
            indexed.setdefault((r["year"], r["question_number"]), set()).add(r["knowledge_point_code"])
    return indexed


def wrap(subject, year, number, text, mappings, url, digest, issues, **fields):
    return {"subject": subject, "year": year, "question_number": number,
        "source_url": url, "source_payload_sha256": digest,
        "text_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(), "raw_text": text,
        "candidate_node_codes": sorted(mappings), "primary_kp_code": None,
        "content_status": "UNVERIFIED", "source_kind": "public_third_party_pending_permission",
        "rights_status": "UNCONFIRMED", "mapping_status": "UNVERIFIED", "answer_status": "UNVERIFIED",
        "grading_status": "UNSUPPORTED", "can_import": False, "verified": False,
        "issues": sorted(set(issues + ["rights_not_confirmed", "source_comparison_pending",
                                      "answer_review_pending", "primary_mapping_review_pending"])), **fields}


def stage_cs(rows, references, review, digest):
    pointers = scoped_refs(references, "408")
    blocked = {(o.get("year", 2026), o["question_number"]) for o in review.get("observations", [])
               if o["subject"] in {"408", "cs408"}}
    staged, seen = [], set()
    for row in rows:
        key = (row["year"], row["num"])
        if key not in pointers:
            continue
        if key in seen:
            raise ValueError("Duplicate source question identity; do not silently overwrite")
        seen.add(key)
        options = row.get("options", [])
        issues = []
        if row.get("subject") != "数据结构":
            issues.append("source_subject_conflict")
        if not re.search(r"树|遍历", row.get("tags", "")):
            issues.append("source_tag_scope_needs_manual_review")
        if row.get("svg_count", 0) or row.get("options_in_svg") or re.search(
                r"<(?:svg|img)\b", row.get("stem_html", ""), re.I):
            issues.append("diagram_requires_original_comparison")
        if [o.get("label") for o in options] != list("ABCD") or any(not o.get("text", "").strip() for o in options):
            issues.append("choice_options_incomplete")
        if any(re.search(r"<(?:svg|img)\b", o.get("html", ""), re.I) for o in options):
            issues.append("diagram_requires_original_comparison")
        option_texts = [re.sub(r"\s+", "", o.get("text", "")) for o in options]
        if len(option_texts) != len(set(option_texts)):
            issues.append("option_text_collision_requires_formula_preservation")
        markup = " ".join([row.get("stem_html", ""), row.get("explanation_html", ""),
                           *(o.get("html", "") for o in options)])
        if re.search(r"<(?:math|sup|sub)\b|katex|mjx-", markup, re.I):
            issues.append("formula_markup_requires_preservation")
        if row.get("answer") not in list("ABCD"):
            issues.append("reference_answer_invalid_or_missing")
        if key in blocked:
            issues.append("known_source_problem_requires_independent_resolution")
        text = row.get("stem_text", "")
        if len(text.strip()) < 5:
            issues.append("stem_missing")
        if re.search(r"[\uE000-\uF8FF\uFFFD]", text):
            issues.append("suspicious_glyph")
        staged.append(wrap("408", *key, text, pointers[key], CS_URL, digest, issues,
            source_question_url=row.get("url"), question_type="single_choice",
            options=options, printed_reference_answer=row.get("answer"),
            raw_explanation=row.get("explanation_text", ""),
            raw_explanation_html=row.get("explanation_html", ""), source_tags=row.get("tags", "")))
    return sorted(staged, key=lambda q: (q["year"], q["question_number"]))


def stage_math(text, references, digest):
    pointers = scoped_refs(references, "math2")
    markers = list(re.finditer(r"(?m)^(\d{1,2})[.．][ \t]*(?=\S)", text))
    staged, seen = [], set()
    for i, marker in enumerate(markers):
        key = (2024, int(marker.group(1)))
        if key not in pointers:
            continue
        if key in seen:
            raise ValueError("Duplicate math source marker requires manual boundary review")
        seen.add(key)
        raw = text[marker.start():markers[i+1].start() if i+1 < len(markers) else len(text)].strip()
        issues = ["question_boundary_review_pending", "printed_answer_not_extracted",
                  "mathematical_conditions_and_formulas_review_pending"]
        if re.search(r"!\[|<img\b", raw, re.I):
            issues.append("diagram_requires_original_comparison")
        staged.append(wrap("math2", *key, raw, pointers[key], MATH_URL, digest, issues,
            question_type=None, printed_reference_answer=None,
            type_basis="Original demand must be compared; never inferred from year/number"))
    return staged


def download(url):
    import requests
    with requests.get(url, stream=True, timeout=(10, 30)) as response:
        response.raise_for_status()
        data = bytearray()
        for chunk in response.iter_content(65536):
            data.extend(chunk)
            if len(data) > 12 * 1024 * 1024:
                raise ValueError("Source exceeds bounded intake size")
    return bytes(data)


def review_sheet(report):
    lines = ["# 真实题切片待核验清单", "", "这是第三方候选转录，不是已核验题库；未入库、未自动判题。",
             "原始 HTML 仅用于源稿对照，不直接作为可信页面渲染。图片/公式警告未消除前不得批准入库。", ""]
    for q in report["questions"]:
        lines += [f"## {q['subject']} · {q['year']} · 第{q['question_number']}题", "",
            f"来源：{q['source_url']}", f"候选节点：{', '.join(q['candidate_node_codes'])}",
            f"第三方标签：{q.get('source_tags', '未提供')}",
            f"问题：{', '.join(q['issues'])}", "", "### 源稿文字", "", q["raw_text"], ""]
        lines += [f"{o.get('label')}. {o.get('text')}" for o in q.get("options", [])]
        lines += ["", f"源稿参考答案（未核验）：{q.get('printed_reference_answer') or '未提取'}", "",
            "- 来源与复用范围：待确认", "- 完整题干/图示/公式/题号：待核对", "- 答案和解析：待核验",
            "- 主知识点与关联知识点：待核对", "- 判题适用边界：待核验", "- 真实审核人、日期与证据：未填写", ""]
    lines += ["## 未匹配的原卷题号", "", json.dumps(report["unmatched_source_pointers"], ensure_ascii=False), ""]
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--review", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    if not any(output.is_relative_to(ROOT / folder) for folder in ("storage", "eval/reports")):
        parser.error("Third-party question text must remain in ignored local intake directories")
    sheet = output.with_suffix(".review.md")
    if output.exists() or sheet.exists():
        parser.error("Refuse to overwrite existing intake evidence")
    from backend.services.exam_reference_service import build_exam_reference_seed
    references = build_exam_reference_seed()[1]
    cs_raw, math_raw = download(CS_URL), download(MATH_URL)
    cs_digest, math_digest = (hashlib.sha256(b).hexdigest() for b in (cs_raw, math_raw))
    candidates = stage_cs(json.loads(cs_raw), references, json.loads(args.review.read_text(encoding="utf-8")), cs_digest)
    candidates += stage_math(math_raw.decode("utf-8-sig"), references, math_digest)
    found = {(q["subject"], q["year"], q["question_number"]) for q in candidates}
    expected = {(subject, *key) for subject in ("408", "math2") for key in scoped_refs(references, subject)
                if subject == "408" or key[0] == 2024}
    report = {"version": "structured-real-slice-intake-v1",
        "created_at": datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(), "questions": candidates,
        "sources": [{"url": CS_URL, "sha256": cs_digest}, {"url": MATH_URL, "sha256": math_digest}],
        "questions_imported": 0, "verified_questions": 0, "model_calls": 0,
        "unmatched_source_pointers": [{"subject": s, "year": y, "question_number": n}
                                      for s, y, n in sorted(expected - found)],
        "limitations": ["not_official_papers_or_answers", "no_rights_certificate", "no_database_writes"]}
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    sheet.write_text(review_sheet(report), encoding="utf-8")
    print(json.dumps({"staged": len(candidates), "by_subject": {s: sum(q["subject"] == s for q in candidates)
        for s in ("408", "math2")}, "imported": 0, "verified": 0, "model_calls": 0}, indent=2))


if __name__ == "__main__":
    main()
