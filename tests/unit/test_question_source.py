from copy import deepcopy
import pytest
from pydantic import ValidationError
from backend.schemas.question_source import public_question_source
from backend.services.question_pack import QuestionPack
from tests.unit.test_question_pack import payload


def exam_payload():
    data = deepcopy(payload())
    data["questions"][0]["source"].update(kind="user_provided", source_type="exam", year=2024,
        question_number=8, paper_title="2024 数学二", subject="数学二")
    return data


@pytest.mark.parametrize("field", ["year", "question_number", "paper_title", "subject"])
def test_exam_requires_complete_identity(field):
    data = exam_payload()
    del data["questions"][0]["source"][field]
    with pytest.raises(ValidationError):
        QuestionPack.model_validate(data)


def test_original_cannot_become_mock_by_label():
    data = exam_payload()
    data["questions"][0]["source"].update(kind="original", source_type="mock")
    with pytest.raises(ValidationError):
        QuestionPack.model_validate(data)


def test_public_view_only_exposes_identity():
    source = QuestionPack.model_validate(exam_payload()).questions[0].source.model_dump(mode="json")
    view = public_question_source({"provenance": {"source": source}}).model_dump()
    assert view == {"source_type": "exam", "year": 2024, "question_number": 8,
                    "paper_title": "2024 数学二", "subject": "数学二", "content_status": "unknown", "edition": None}


def test_transcribed_real_source_never_enables_automatic_grading():
    data = exam_payload()
    q = data["questions"][0]
    q.update(content_status="source_transcribed", answer_reviewed_by=None, grading_method=None)
    assert QuestionPack.model_validate(data).questions[0].content_status == "source_transcribed"
    q["grading_method"] = "single_choice"
    with pytest.raises(ValidationError):
        QuestionPack.model_validate(data)


def test_transcribed_does_not_admit_generated_originals():
    data = payload()
    data["questions"][0].update(content_status="source_transcribed", answer_reviewed_by=None, grading_method=None)
    with pytest.raises(ValidationError):
        QuestionPack.model_validate(data)


@pytest.mark.parametrize("config", [None, [], {"provenance": []}, {"provenance": {"source": []}},
    {"provenance": {"source": {"year": 2024, "citation": "2024 真题"}}},
    {"provenance": {"source": {"source_type": "exam", "year": True}}}])
def test_legacy_or_malformed_sources_never_fabricate_provenance(config):
    assert public_question_source(config).source_type == "unknown"
