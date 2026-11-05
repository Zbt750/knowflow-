"""Public question provenance, without answers or private reviewer information."""
from typing import Literal
from pydantic import BaseModel


class QuestionSourceView(BaseModel):
    source_type: Literal["exam", "mock", "original", "unknown"] = "unknown"
    year: int | None = None
    question_number: int | None = None
    paper_title: str | None = None
    subject: str | None = None
    content_status: Literal["reviewed", "source_transcribed", "unknown"] = "unknown"
    edition: str | None = None


def public_question_source(config: dict | None) -> QuestionSourceView:
    """Never infer exam year/type from a citation or a publication date."""
    if not isinstance(config, dict):
        return QuestionSourceView()
    provenance = config.get("provenance")
    source = provenance.get("source") if isinstance(provenance, dict) else None
    if not isinstance(source, dict):
        return QuestionSourceView()
    kind = source.get("source_type", "unknown")
    if kind not in ("exam", "mock", "original", "unknown"):
        return QuestionSourceView()
    year, number = source.get("year"), source.get("question_number")
    title, subject = source.get("paper_title"), source.get("subject")
    year = year if type(year) is int and 2000 <= year <= 2100 else None
    number = number if type(number) is int and 1 <= number <= 200 else None
    title = title.strip()[:300] if isinstance(title, str) and title.strip() else None
    subject = subject.strip()[:100] if isinstance(subject, str) and subject.strip() else None
    status = provenance.get("content_status", "unknown")
    if status not in ("reviewed", "source_transcribed", "unknown"):
        status = "unknown"
    edition = source.get("edition")
    edition = edition.strip()[:100] if isinstance(edition, str) and edition.strip() else None
    if kind in ("exam", "mock") and not all((year, number, title, subject)):
        return QuestionSourceView()
    return QuestionSourceView(source_type=kind, year=year, question_number=number,
                              paper_title=title, subject=subject, content_status=status, edition=edition)
