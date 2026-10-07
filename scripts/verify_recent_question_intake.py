"""Read-only development intake checks; report metadata only, never private stems."""
import json
import sys
from collections import Counter
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import requests
from sqlalchemy import select
from backend.config import get_settings
from backend.db import create_db_engine, create_session_factory
from backend.models.learning import Question, KnowledgePoint


def main():
    engine = create_db_engine(str(get_settings().active_database_url))
    try:
        with create_session_factory(engine)() as db:
            rows = db.execute(select(Question, KnowledgePoint.code).join(KnowledgePoint, Question.kp_id == KnowledgePoint.id)
                              .where(Question.is_active.is_(True))).all()
            grouped = Counter()
            checks = []
            for q, code in rows:
                source = (q.grading_config or {}).get("provenance", {}).get("source", {})
                if source.get("year") not in (2025, 2026):
                    continue
                grouped[(source["subject"], source["year"])] += 1
                checks.append({"id": str(q.id), "kp_code": code, "type": q.question_type,
                               "has_answer": bool(q.correct_answer), "detailed_explanation": "## 解题过程" in q.explanation,
                               "has_choice_options": q.question_type != "single_choice" or bool(q.options),
                               "verified": bool((q.grading_config or {}).get("verified"))})
            failures = [c for c in checks if not all(c[k] for k in ("has_answer", "detailed_explanation", "has_choice_options"))]
            if failures:
                raise ValueError(f"Incomplete rows: {failures}")
            api_checks = []
            for kp_id in {q.kp_id for q, _ in rows}:
                response = requests.get(f"http://127.0.0.1:8000/api/knowledge/{kp_id}", timeout=10)
                response.raise_for_status()
                questions = response.json()["questions"]
                if any("options" not in q or "correct_answer" in q or "explanation" in q for q in questions):
                    raise ValueError("Knowledge question contract mismatch")
                api_checks.append(str(kp_id))
            report = {"scope": "active recent-year online questions only; not all-paper completeness certification",
                      "counts": [{"subject": s, "year": y, "count": n} for (s, y), n in sorted(grouped.items())],
                      "questions": checks, "verified_count": sum(c["verified"] for c in checks),
                      "api_nodes_checked": len(api_checks), "failures": []}
            output = Path("storage/question-intake/recent-two-years-20261003/verification-v2.json")
            output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"{len(checks)} active questions complete structurally; {len(api_checks)} live node endpoints checked; zero verified upgrades")
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
