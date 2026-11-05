"""Offline observable answer-contract checks, not semantic grading or rewriting."""
import re

VERSION = "observable-answer-contract-v1"


def audit_answer_contract(question, answer, blocks):
    issues = []
    sources = {str(b.get("material_title")) for b in blocks if b.get("material_title")}
    labels = {str(b.get("label")): str(b["material_title"]) for b in blocks
              if b.get("label") and b.get("material_title")}
    comparison = len(sources) > 1 and bool(re.search(r"共同|共有|相同", question)) and bool(re.search(r"独有|特有|各自", question))
    rows_checked = 0
    common_facts = set()
    unique_facts = set()
    if comparison:
        fence = None
        for line_number, line in enumerate(answer.splitlines(), 1):
            marker = re.match(r"^\s*(`{3,}|~{3,})", line)
            if marker:
                kind = marker.group(1)[0]
                fence = None if fence == kind else kind if fence is None else fence
                continue
            if fence:
                continue
            # Code/ordinary prose are not interpreted as a factual table.
            if not line.strip().startswith("|"):
                continue
            cells = [c.strip() for c in re.split(r"(?<!\\)\|", line.strip())[1:-1]]
            if len(cells) != 3:
                continue
            fact, owner, references = cells
            owner = re.sub(r"[*_`\s]", "", owner)
            common = owner in {"共同", "共同点", "共有", "相同", "两份共有", "两份都有"}
            unique = "独有" in owner or "特有" in owner or owner in sources
            if not (common or unique):
                continue
            rows_checked += 1
            cited = re.findall(r"\[C(\d+)\]", references)
            observed = {labels["C" + c] for c in cited if "C" + c in labels}
            if any("C" + c not in labels for c in cited):
                issues.append({"code": "unknown_citation", "line": line_number})
            if common and not sources.issubset(observed):
                issues.append({"code": "common_fact_missing_source", "line": line_number})
            normalized = re.sub(r"[\s*_`，。；、：:,.!！?？]", "", fact)
            (common_facts if common else unique_facts).add(normalized)
        if common_facts & unique_facts:
            issues.append({"code": "identical_fact_common_and_unique"})
    if re.search(r"反例|反过来|逆命题|逆推|反推", question):
        # Flag only the observed heading/list anti-pattern. Do not infer truth of
        # arbitrary mathematical claims or reject quoted text automatically.
        for match in re.finditer(r"(?m)^(?:#{1,6}\s*)?(?:它|这个反例)?否定的是[^\n]*[：:]\s*\n((?:\s*\n|\s*[-*].*\n?)+)", answer):
            if re.search(r"(?<!不)成立", match.group(1)):
                issues.append({"code": "negation_heading_lists_true_statement"})
    return {"version": VERSION, "status": "checked" if rows_checked or issues else "unobserved",
            "comparison_rows_checked": rows_checked, "issues": issues,
            "observable_checks_passed": not issues if rows_checked or issues else None,
            "semantic_correctness_proven": False, "manual_review_required": True,
            "source_identity": "material_title", "output_modified": False}
