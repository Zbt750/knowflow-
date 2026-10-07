from types import SimpleNamespace
from uuid import uuid4
from pathlib import Path
import json

import pytest

from backend.chat import service
from backend.chat.evidence import evidence_snapshot
from backend.ingestion.chunker import build_chunk_drafts
from backend.ingestion.title_tree import source_blocks_from_title_tree


@pytest.mark.parametrize("question, expected", [
    ("它后半部分的E、F、G具体要求什么？", ("E", "F", "G")),
    ("只概述这份文件的阶段 A", ("A",)),
    ("《阶段A验收笔记》讲什么？", ()),
    ("阶段A验收笔记.md讲什么？", ()),
    ("阶段A验收笔记主要讲什么？", ()),
    ("这份文件所有阶段，包括阶段 A", ()),
    ("这份文件从阶段 A 到阶段 C", ()),
    ("阶段 A 不要讲", ()),
    ("TCP、BFS 有什么区别", ()),
    ("它后半部分讲什么", ()),
])
def test_stage_scope_is_explicit_not_filename_or_implicit_half(question, expected):
    assert service._requested_stage_scope(question) == expected


def setup_rows(monkeypatch, stages="ABCDEFG", row_count=None):
    material = SimpleNamespace(id=uuid4(), title="合成项目阶段说明", original_filename=None,
                               active_index_version="v1", source_type="user")
    rows = [(SimpleNamespace(id=uuid4(), material_id=material.id, index_version="v1", ordinal=i,
                             content=f"{stage} 的要求", heading_path=[f"阶段 {stage} · 要求"]), material)
            for i, stage in enumerate(stages)]
    if row_count:
        rows = (rows * row_count)[:row_count]
    monkeypatch.setattr(service, "_ready_materials", lambda *_: [material])
    db = SimpleNamespace(execute=lambda *_: SimpleNamespace(all=lambda: rows),
                         scalars=lambda *_: SimpleNamespace(all=lambda: []))
    return db, material


def test_selected_chapters_only_and_actual_snapshot(monkeypatch):
    db, material = setup_rows(monkeypatch)
    root = Path(__file__).resolve().parents[2]
    fixture = (root / "eval/fixtures/baseline_user_v3.md").read_text(encoding="utf-8")
    case = next(json.loads(line) for line in (root / "eval/dataset/chat_baseline_v3_1.jsonl").read_text(encoding="utf-8").splitlines()
                if json.loads(line)["id"] == "file-alias")
    drafts = build_chunk_drafts(fixture, source_blocks_from_title_tree(fixture))
    rows = [(SimpleNamespace(id=uuid4(), index_version="v1", ordinal=d.ordinal,
                             content=d.content, heading_path=d.heading_path), material) for d in drafts]
    db.execute = lambda *_: SimpleNamespace(all=lambda: rows)
    monkeypatch.setattr(service, "_recent_user_context", lambda *_, **__: case["setup_questions"])
    def unexpected_search(*_, **__):
        raise AssertionError("Explicit indexed sections must not fall back to top-k")
    monkeypatch.setattr(service, "search_chunks", unexpected_search)
    prepared = service._search_pending(db, session_id=uuid4(), question=case["question"],
                                      assistant_id=uuid4(), mode="user", stack=None, history_token_budget=0)
    snapshot = evidence_snapshot(prepared)
    assert len(snapshot["contexts"]) == 3
    assert [service._stage_heading(b["heading_path"]) for b in snapshot["blocks"]] == list("EFG")
    assert "SYNTHETIC-USER-47" not in str(snapshot)
    assert all(phrase in str(snapshot) for phrase in ("窄屏", "重启", "证据"))
    assert "所选资料全部可读取" not in prepared.prompt[0]["content"]


def test_whole_file_overview_still_has_all_sections(monkeypatch):
    db, _ = setup_rows(monkeypatch)
    result = service._overview_hits(db, question="阶段说明这份文件主要讲什么？", mode="user")
    assert len(result.hits) == 7 and result.full_document


def test_missing_requested_section_does_not_substitute_other_sections(monkeypatch):
    db, _ = setup_rows(monkeypatch, "ABCDEF")
    result = service._overview_hits(db, question="这份文件的E、F、G具体要求什么？", mode="user")
    assert not result.hits and "阶段 G" in result.direct_response


def test_scan_over_limit_is_not_silently_reduced_to_found_chapters(monkeypatch):
    db, _ = setup_rows(monkeypatch, row_count=51)
    result = service._overview_hits(db, question="这份文件的E、F、G具体要求什么？", mode="user")
    assert not result.hits and "较长" in result.direct_response


def test_unknown_heading_convention_falls_back_without_claiming_coverage(monkeypatch):
    db, _ = setup_rows(monkeypatch, "XYZ")
    assert service._overview_hits(db, question="这份文件的E、F、G具体要求什么？", mode="user") is None


def test_stage_concept_question_does_not_read_entire_library(monkeypatch):
    db, _ = setup_rows(monkeypatch)
    assert service._overview_hits(db, question="阶段 A 是什么？", mode="user") is None


def test_nested_heading_uses_specific_section_not_parent_range():
    assert service._stage_heading(["阶段 A–G", "阶段 E · 窄屏"]) == "E"
    assert service._stage_heading(["阶段 A–G"]) is None
