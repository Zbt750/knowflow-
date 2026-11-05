"""Build a references-only index of historical long-question sources.

The output intentionally excludes full question statements and answers. It is
an intake/review list, not a qualification or database import tool.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = ROOT / "storage/quality-audits/long-question-supply-20261017"
MATH_METADATA_URL = (
    "https://raw.githubusercontent.com/lx-ruc/kaoyanshuxue/main/"
    "kaoyan_math_images/%E6%95%B0%E5%AD%A6%E4%BA%8C/answers.json"
)
MATH_REPO_URL = "https://github.com/lx-ruc/kaoyanshuxue"
MATH_ARCHIVE_URL = "https://github.com/swjtuhub/SWJTU-Courses/tree/main/考研资料/数学/真题/数二真题及解析1989-2019"
MATH_INSTITUTION_ARCHIVE_URL = "https://www.guit.edu.cn/sx/info/1037/1660.htm"
CS408_PAPERS_URL = "https://www.xit.edu.cn/yjsfk/kyzykwtkw/list.htm"
CS408_TOPICS_URL = "https://codebrick.tech/exam-408/"


def math_rows() -> list[dict[str, str]]:
    request = urllib.request.Request(
        MATH_METADATA_URL,
        headers={"User-Agent": "long-question-source-index/1.0"},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        metadata = json.load(response)

    rows: list[dict[str, str]] = []
    for key, item in metadata.items():
        if item.get("group") != "数学二" or item.get("type") != 3:
            continue
        year = str(item.get("paper", ""))
        question_number = int(item.get("index", 0))
        question_id = str(item.get("question_id", ""))
        if not (2009 <= int(year) <= 2025 and question_number and question_id):
            continue
        paper_locator = (
            MATH_ARCHIVE_URL if int(year) <= 2019 else MATH_INSTITUTION_ARCHIVE_URL
        )
        rows.append({
            "candidate_id": f"M2-{year}-Q{question_number:02d}",
            "subject": "数学二",
            "year": year,
            "exam_question_number": str(question_number),
            "question_form": "主观解答题（第三方索引标记type=3）",
            "knowledge_point_index": str(item.get("knowledge_point", "")),
            "source_record_id": question_id,
            "question_source_locator": paper_locator,
            "metadata_evidence": f"{MATH_METADATA_URL}#{key}",
            "review_status": "SOURCE_INDEXED_CONTENT_UNREVIEWED",
            "notes": "仅题号/考点元数据；需从原卷恢复完整题干、图表与答案后再核验。",
        })
    rows.sort(key=lambda row: (row["year"], int(row["exam_question_number"])))
    return rows


def computer_rows() -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for year in range(2009, 2027):
        topic_path = ROOT / f"seed/materials/builtin/exam_408_{year}_topics.md"
        topic_map: dict[int, tuple[str, str]] = {}
        if topic_path.exists():
            text = topic_path.read_text(encoding="utf-8")
            for line in text.splitlines():
                match = re.search(r"\|\s*第\s*(4[1-7])\s*题\s*\|\s*([^|]+?)\s*\|", line)
                if not match:
                    continue
                qnum = int(match.group(1))
                topic = match.group(2).strip()
                link_match = re.search(r"\[查看\]\(<([^>]+)>\)", line)
                topic_map[qnum] = (topic, link_match.group(1) if link_match else "")

        for qnum in range(41, 48):
            topic, topic_url = topic_map.get(qnum, ("", ""))
            paper_locator = CS408_PAPERS_URL if year <= 2025 else CS408_TOPICS_URL
            rows.append({
                "candidate_id": f"CS408-{year}-Q{qnum}",
                "subject": "计算机408",
                "year": str(year),
                "exam_question_number": str(qnum),
                "question_form": "综合应用题（统考卷末7题索引范围）",
                "knowledge_point_index": topic,
                "source_record_id": "",
                "question_source_locator": paper_locator,
                "metadata_evidence": topic_url or CS408_TOPICS_URL,
                "review_status": (
                    "SOURCE_INDEXED_CONTENT_UNREVIEWED"
                    if topic_url
                    else "PAPER_LISTED_QUESTION_CONTENT_UNVERIFIED"
                ),
                "notes": "来源页列有该年度试卷；题干/考点仍需逐份原卷核对。",
            })
    return rows


def math_2026_rows() -> list[dict[str, str]]:
    topic_path = ROOT / "seed/materials/builtin/exam_math2_2026_topics.md"
    if not topic_path.exists():
        return []
    rows: list[dict[str, str]] = []
    for line in topic_path.read_text(encoding="utf-8").splitlines():
        match = re.search(r"\|\s*第\s*(\d+)\s*题\s*\|\s*([^|]+?)\s*\|", line)
        if not match or not 17 <= int(match.group(1)) <= 22:
            continue
        number = int(match.group(1))
        rows.append({
            "candidate_id": f"M2-2026-Q{number:02d}",
            "subject": "数学二",
            "year": "2026",
            "exam_question_number": str(number),
            "question_form": "解答题（本地2026索引第17-22题）",
            "knowledge_point_index": match.group(2).strip(),
            "source_record_id": "",
            "question_source_locator": "seed/materials/builtin/exam_math2_2026_topics.md",
            "metadata_evidence": "seed/materials/builtin/exam_math2_2026_topics.md",
            "review_status": "LOCAL_INDEX_ONLY_CONTENT_UNREVIEWED",
            "notes": "本地索引称标签来自2026数学二试题PDF与解析；本清单未复核原卷内容。",
        })
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()
    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)

    rows = math_rows() + math_2026_rows() + computer_rows()
    rows.sort(key=lambda row: (row["subject"], row["year"], int(row["exam_question_number"])))
    math_count = sum(row["subject"] == "数学二" for row in rows)
    computer_count = sum(row["subject"] == "计算机408" for row in rows)
    csv_path = output / "long-question-source-candidates.csv"
    summary_path = output / "long-question-source-candidates.json"
    if csv_path.exists() or summary_path.exists():
        raise FileExistsError("Refusing to overwrite a previous source-index snapshot")
    fields = list(rows[0]) if rows else []
    with csv_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)

    counts = {
        "candidate_source_records": len(rows),
        "mathematics_ii": math_count,
        "computer_408": computer_count,
        "years": "2009-2026",
        "review_status": "REFERENCE_INDEX_ONLY_NOT_IMPORTED_OR_QUALIFIED",
        "question_texts_copied": False,
        "real_database_connected_or_changed": False,
        "source_records": [
            {"name": "数学二题号/考点元数据（第三方整理）", "url": MATH_METADATA_URL,
             "rows": sum(row["subject"] == "数学二" and int(row["year"]) <= 2025 for row in rows)},
            {"name": "数学二逐年试题公开索引", "url": MATH_ARCHIVE_URL, "years": "2009-2019"},
            {"name": "数学二高校资料页（1987-2022归档索引）", "url": MATH_INSTITUTION_ARCHIVE_URL},
            {"name": "408逐年试题与参考解析（高校页面）", "url": CS408_PAPERS_URL,
             "rows": sum(row["subject"] == "计算机408" and int(row["year"]) <= 2025 for row in rows)},
            {"name": "2026年数学二本地逐题索引（非官方标签）", "url": "seed/materials/builtin/exam_math2_2026_topics.md",
             "rows": sum(row["subject"] == "数学二" and row["year"] == "2026" for row in rows)},
            {"name": "2026年408逐题标签索引（第三方）", "url": "seed/materials/builtin/exam_408_2026_topics.md",
             "rows": sum(row["subject"] == "计算机408" and row["year"] == "2026" for row in rows)},
        ],
        "limitations": [
            "CSV仅列来源索引、题号与少量考点元数据，不含题干或答案。",
            "公开可访问不代表题目内容许可复制或再发布；正式入库前仍需来源与使用权核对。",
            "逐题内容恢复、图片完整性、答案核对、判题器验证、去重及节点映射均未在本脚本中完成。",
        ],
    }
    summary_path.write_text(json.dumps(counts, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"csv": str(csv_path), "summary": str(summary_path), **counts}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
