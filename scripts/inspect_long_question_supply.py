"""Offline sealed-dump inventory; never opens a database or changes qualification."""
import argparse
from collections import Counter
import csv
import json
from pathlib import Path
import re

LONG_TYPES = {"calculation", "proof", "subjective", "discussion", "program"}


def uncopy(value):
    if value == r"\N": return None
    escapes = {"t": "\t", "n": "\n", "r": "\r", "b": "\b", "f": "\f", "v": "\v", "\\": "\\"}
    return re.sub(r"\\([0-7]{1,3}|.)", lambda m: chr(int(m[1], 8)) if m[1][0] in "01234567" else escapes.get(m[1], m[1]), value)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--copy", type=Path, required=True)
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    formal = {row["id"] for row in json.loads(args.snapshot.read_text(encoding="utf-8"))}
    rows = []; columns = None
    for line in args.copy.read_text(encoding="utf-8").splitlines():
        if line.startswith("COPY public.questions ("):
            columns = line.split("(", 1)[1].split(")", 1)[0].split(", "); continue
        if columns is None: continue
        if line == r"\.": break
        values = [uncopy(v) for v in line.split("\t")]
        if len(values) != len(columns): raise ValueError("COPY field mismatch")
        row = dict(zip(columns, values))
        row["current_formal"] = row["id"] in formal
        for key in ("grading_config", "options"):
            row[key] = json.loads(row[key]) if row[key] is not None else None
        rows.append(row)
    approved = [q for q in rows if q["current_formal"]]
    if len(approved) != len(formal): raise ValueError("sealed snapshot identity mismatch")
    long_rows = [q for q in rows if q["question_type"] in LONG_TYPES]
    summary = {"source": str(args.copy), "source_scope": "sealed_dump_not_live_database",
        "all_records": len(rows), "formal_records": len(approved),
        "formal_type_counts": dict(Counter(q["question_type"] for q in approved)),
        "all_long_records": len(long_rows), "formal_long_records": sum(q["current_formal"] for q in long_rows),
        "nonformal_long_records": sum(not q["current_formal"] for q in long_rows),
        "database_connected": False, "qualification_changed": False}
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "inventory.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    with (args.output / "existing-long-questions.csv").open("w", encoding="utf-8-sig", newline="") as file:
        fields = ["id", "kp_id", "question_type", "current_formal", "stem", "correct_answer", "explanation"]
        writer = csv.DictWriter(file, fieldnames=fields, extrasaction="ignore"); writer.writeheader(); writer.writerows(long_rows)
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__": main()
