from scripts.build_exam_transcription_candidates import build


def page(n, text, subject="cs408"):
    return {"subject": subject, "page": n, "success": True, "source_file": "synthetic.pdf",
            "source_sha256": "a" * 64, "response": {"text": text}}


def test_cross_page_options_preserve_both_source_pages_without_certifying():
    result = build({"records": [page(1, "5. 合成题干\nA.甲\nB.乙"), page(2, "C.丙\nD.丁\n6.另一题\nA.甲") ]})
    q5, q6 = result["questions"]
    assert q5["pages"] == [1, 2]
    assert q5["option_letters_detected"] == list("ABCD")
    assert "missing_choice_options" not in q5["issues"]
    assert "missing_choice_options" in q6["issues"]
    assert "last_page_boundary_requires_next_page" in q6["issues"]
    assert result["online_questions_imported"] == 0
    assert all(not q["verified"] and not q["can_import"] for q in result["questions"])


def test_failed_pages_are_not_invented_and_math_fill_is_not_missing_options():
    report = {"records": [{"subject": "math2", "page": 1, "success": False},
        page(3, "11.合成填空题\n【答案】1", "math2")]}
    result = build(report)
    assert result["candidate_count"] == 1
    q = result["questions"][0]
    assert q["question_number"] == 11
    assert "missing_choice_options" not in q["issues"]
    assert "answer_not_reviewed" in q["issues"]
