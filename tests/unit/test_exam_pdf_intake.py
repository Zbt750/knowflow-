from scripts import audit_exam_pdf_intake as intake


def test_missing_years_are_not_hidden_by_folder_presence(tmp_path):
    (tmp_path / "数学" / "2010").mkdir(parents=True)
    result = intake.audit(tmp_path, first_year=2010, last_year=2010)
    assert result["missing_annual_pdf_folders"] == ["数学/2010", "408/2010"]
    assert result["files"] == 0 and result["rights_review_required"] is True


def test_text_layer_and_answer_marker_do_not_claim_verification(tmp_path, monkeypatch):
    class Page:
        def extract_text(self): return "1. 合成问题\n参考答案\n" + "合成正文" * 80
    class Reader:
        is_encrypted = False
        pages = [Page()]
    monkeypatch.setattr(intake, "PdfReader", lambda _: Reader())
    file = tmp_path / "synthetic.pdf"
    file.write_bytes(b"synthetic")
    result = intake.inspect_pdf(file)
    assert result["status"] == "text_candidate"
    assert result["answer_section_indicator"] is True
    assert result["ready_for_auto_grading"] is False
