import hashlib
import json
from types import SimpleNamespace

import pytest

from scripts import stage_exam_text_pages as staging


def source(tmp_path):
    root = tmp_path / "source"
    root.mkdir()
    paper = root / "paper.pdf"
    paper.write_bytes(b"isolated fixture, not a real paper")
    return root, {"records": [{"file": "paper.pdf", "sha256": hashlib.sha256(paper.read_bytes()).hexdigest(),
                              "subject": "408", "year": 2026}]}


def test_text_and_glyph_pages_are_evidence_not_verified_questions(tmp_path, monkeypatch):
    root, manifest = source(tmp_path)
    monkeypatch.setattr(staging, "PdfReader", lambda _: SimpleNamespace(pages=[
        SimpleNamespace(extract_text=lambda: "1. 隔离合成样例，仅供页面文本证据测试。" * 3),
        SimpleNamespace(extract_text=lambda: "坏公式\ue000"),
    ]))
    output = tmp_path / "result"
    result = staging.stage(root, manifest, output)
    assert result["pages"] == 2 and result["ocr_or_manual_pages"] == 1
    evidence = json.loads(next((output / "408/2026").glob("*.json")).read_text(encoding="utf-8"))
    assert evidence["verified"] is False
    assert evidence["online_questions_imported"] == 0
    assert all(p["can_import"] is False and p["question_type"] is None and p["primary_kp_code"] is None
               for p in evidence["pages"])


@pytest.mark.parametrize("failure", ["changed", "traversal", "overwrite"])
def test_source_identity_and_no_overwrite(tmp_path, failure):
    root, manifest = source(tmp_path)
    output = tmp_path / "result"
    if failure == "changed":
        manifest["records"][0]["sha256"] = "0" * 64
    elif failure == "traversal":
        manifest["records"][0]["file"] = "../other.pdf"
    else:
        output.mkdir()
    with pytest.raises(ValueError):
        staging.stage(root, manifest, output)
