"""Pure computation caching must not cache mutable content or trust decisions."""
from types import SimpleNamespace
from uuid import uuid4

from backend.services import constant_expression as arithmetic
from backend.services import question_production_pipeline as pipeline


def test_option_cache_reuses_identical_inputs_but_not_changed_options(monkeypatch):
    pipeline._cached_option_pairs.cache_clear()
    calls = []
    original = pipeline._compute_option_pairs
    def counted(options):
        calls.append(dict(options))
        return original(options)
    monkeypatch.setattr(pipeline, '_compute_option_pairs', counted)
    options = {'A': '1/2', 'B': '0.5', 'C': '2'}
    result = pipeline.duplicate_choice_option_pairs(options)
    assert result == [('A', 'B')]
    result.clear()
    assert pipeline.duplicate_choice_option_pairs(dict(options)) == [('A', 'B')]
    assert len(calls) == 1, 'caller mutation must not corrupt cached immutable result'
    options['B'] = '3/4'
    assert pipeline.duplicate_choice_option_pairs(options) == []
    assert len(calls) == 2
    reordered = {'C': '2', 'B': '3/4', 'A': '1/2'}
    assert pipeline.duplicate_choice_option_pairs(reordered) == []
    assert len(calls) == 3
    pipeline._cached_option_pairs.cache_clear()


def test_symbolic_unsupported_and_nonstring_options_keep_existing_semantics():
    assert pipeline.duplicate_choice_option_pairs({'A': 'x', 'B': '2*x'}) == []
    assert pipeline.duplicate_choice_option_pairs({'A': None, 'B': '1'}) == []
    assert pipeline.duplicate_choice_option_pairs(None) == []


def test_exact_fast_comparison_matches_previous_simplify_predicate():
    from sympy import simplify
    values = ['0', '1/2', '0.5', '-3/4', 'sqrt(2)', '2**(1/2)',
              'sqrt(8)/2', 'pi', '2*pi', 'e', 'sqrt(2)+sqrt(3)',
              'sqrt(6)', '(1+sqrt(5))/2']
    expressions = [arithmetic.constant_expression(value) for value in values]
    expressions = [value for value in expressions if value is not None]
    for left in expressions:
        for right in expressions:
            assert pipeline._constant_options_equal(left, right) == (simplify(left-right) == 0)


def test_constant_cache_keys_full_expression_and_remains_bounded(monkeypatch):
    arithmetic._cached_constant_expression.cache_clear()
    original = arithmetic._compute_constant_expression
    calls = []
    def counted(value):
        calls.append(value)
        return original(value)
    monkeypatch.setattr(arithmetic, '_compute_constant_expression', counted)
    assert arithmetic.constant_expression('1/2') == arithmetic.constant_expression('1/2')
    assert calls == ['1/2']
    assert arithmetic.constant_expression('3/4') != arithmetic.constant_expression('1/2')
    assert arithmetic.constant_expression('__import__("os")') is None
    assert arithmetic._cached_constant_expression.cache_info().maxsize == 8192
    assert pipeline._cached_option_pairs.cache_info().maxsize == 2048
    arithmetic._cached_constant_expression.cache_clear()


def _review_receipt_fixture(review_version="public-question-auto-review-v8"):
    from backend.services.answer_verification import answer_version_sha256
    from backend.services.auto_question_review import digest, question_snapshot_sha256

    node_id, question_id, event_id = uuid4(), uuid4(), uuid4()
    question = SimpleNamespace(
        id=question_id, current_version_id=uuid4(), updated_at=None,
        kp_id=node_id, question_type="single_choice",
        stem="已审核的完整选择题题干", options={"A": "1", "B": "2"},
        correct_answer="A", explanation="先按条件计算，再逐项核验选项。",
        skill_tags=["计算"], question_role="typical", is_variant=False,
        question_provenance="real_exam", content_trust="auto_verified",
        source_status="verified", answer_provenance="auto_verified",
        answer_reliability="verified", grading_mode="auto",
        grading_config={"verified": True, "method": "single_choice"},
        bank_scope="public", generation_batch_id=None,
        source_attestation_key=None, source_attestation_sha256=None,
        auto_review_event_id=event_id,
    )
    node = SimpleNamespace(id=node_id, code="math.test.leaf", subject="math2",
                           is_active=True, is_assessable=True, is_reference_only=False,
                           children=[])
    snapshot_hash = question_snapshot_sha256(question)
    audit_snapshot = {
        "version": review_version,
        "bound_question_snapshot_sha256": snapshot_hash,
        "stages": {
            "structure": {"status": "PASS",
                           "option_content_rule_version": "distinct-choice-content-v1"},
            "independent_answer": {"status": "PASS"},
            "mapping": {"status": "PASS", "node_id": str(node_id),
                        "node_code": "math.test.leaf", "node_subject": "math2"},
        },
    }
    event = SimpleNamespace(
        id=event_id, question_id=question_id, event_type="qualified",
        review_version=review_version, question_snapshot_sha256=snapshot_hash,
        answer_sha256=answer_version_sha256(question),
        audit_sha256=digest(audit_snapshot), audit_snapshot=audit_snapshot,
        qualification_class="exam_curated",
    )
    question.current_auto_review = event
    return question, node, event


def test_v8_hash_bound_structure_receipt_avoids_revalidating_same_content(monkeypatch):
    from backend.services import auto_question_review as review

    question, node, event = _review_receipt_fixture()
    monkeypatch.setattr(review, "validate_question_content",
                        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("unexpected revalidation")))
    assert review.current_auto_review(question, node) is event

    # A content change invalidates the receipt before the shortcut can apply.
    question.correct_answer = "B"
    question.current_version_id = uuid4()
    assert review.current_auto_review(question, node) is None


def test_v8_match_cache_is_bounded_by_question_version_and_node_state(monkeypatch):
    from backend.services import auto_question_review as review

    review._AUTO_REVIEW_MATCH_CACHE.clear()
    question, node, event = _review_receipt_fixture()
    original = review._current_event_matches
    calls = []

    def counted(*args, **kwargs):
        calls.append(True)
        return original(*args, **kwargs)

    monkeypatch.setattr(review, "_current_event_matches", counted)
    assert review.current_auto_review(question, node) is event
    assert review.current_auto_review(question, node) is event
    assert len(calls) == 1

    question.current_version_id = uuid4()
    assert review.current_auto_review(question, node) is event
    assert len(calls) == 2, "a new immutable question version must miss the old cache entry"

    node.is_assessable = False
    assert review.current_auto_review(question, node) is None
    assert len(calls) == 3, "a mapping-state change must be revalidated"
    review._AUTO_REVIEW_MATCH_CACHE.clear()


def test_legacy_auto_review_receipt_keeps_live_structure_validation(monkeypatch):
    from backend.services import auto_question_review as review

    review._AUTO_REVIEW_MATCH_CACHE.clear()
    question, node, event = _review_receipt_fixture("public-question-auto-review-v7")
    event.audit_snapshot["version"] = event.review_version
    event.audit_sha256 = review.digest(event.audit_snapshot)
    calls = []
    monkeypatch.setattr(review, "validate_question_content", lambda *_args, **_kwargs: (
        calls.append(True) or SimpleNamespace(completeness="complete")))
    assert review.current_auto_review(question, node) is event
    assert calls == [True]
    assert review.current_auto_review(question, node) is event
    assert calls == [True], "a successful immutable legacy receipt can reuse its full check"

    question.current_version_id = uuid4()
    assert review.current_auto_review(question, node) is event
    assert calls == [True, True], "a new QuestionVersion must run legacy validation again"

    event.audit_snapshot['stages']['structure']['status'] = 'FAIL'
    assert review.current_auto_review(question, node) is None
    review._AUTO_REVIEW_MATCH_CACHE.clear()


def test_public_eligibility_cache_is_version_bound_and_fails_closed_while_dirty(monkeypatch):
    from sqlalchemy import Boolean, Column, DateTime, String, create_engine
    from sqlalchemy.orm import DeclarativeBase, Session
    from backend.services import question_eligibility as eligibility

    class Base(DeclarativeBase):
        pass

    class BoundQuestion(Base):
        __tablename__ = "eligibility_cache_questions"
        id = Column(String, primary_key=True)
        current_version_id = Column(String, nullable=False)
        updated_at = Column(DateTime, nullable=True)
        kp_id = Column(String, nullable=False)
        question_type = Column(String, nullable=False)
        question_provenance = Column(String, nullable=False)
        content_trust = Column(String, nullable=False)
        source_status = Column(String, nullable=False)
        answer_provenance = Column(String, nullable=False)
        answer_reliability = Column(String, nullable=False)
        content_reviewed_by = Column(String, nullable=True)
        content_reviewed_at = Column(DateTime, nullable=True)
        answer_reviewed_by = Column(String, nullable=True)
        answer_reviewed_at = Column(DateTime, nullable=True)
        source_attestation_key = Column(String, nullable=True)
        source_attestation_sha256 = Column(String, nullable=True)
        answer_attestation_key = Column(String, nullable=True)
        answer_attestation_sha256 = Column(String, nullable=True)
        answer_verification_event_id = Column(String, nullable=True)
        auto_review_event_id = Column(String, nullable=True)
        is_active = Column(Boolean, nullable=False)
        is_hidden = Column(Boolean, nullable=False)
        bank_scope = Column(String, nullable=False)
        generation_batch_id = Column(String, nullable=True)

    class BoundNode(Base):
        __tablename__ = "eligibility_cache_nodes"
        id = Column(String, primary_key=True)
        code = Column(String, nullable=False)
        subject = Column(String, nullable=False)
        is_active = Column(Boolean, nullable=False)
        is_assessable = Column(Boolean, nullable=False)
        is_reference_only = Column(Boolean, nullable=False)

    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    calls = []
    marker = object()
    monkeypatch.setattr(eligibility, "_question_eligibility_uncached",
        lambda *_args, **_kwargs: (calls.append(True) or marker))
    try:
        with Session(engine) as session:
            question = BoundQuestion(id="q-cache", current_version_id="v1", updated_at=None,
                kp_id="node-cache", question_type="single_choice", question_provenance="real_exam",
                content_trust="auto_verified", source_status="verified", answer_provenance="auto_verified",
                answer_reliability="verified", is_active=True, is_hidden=False, bank_scope="public")
            node = BoundNode(id="node-cache", code="cache.leaf", subject="math2",
                is_active=True, is_assessable=True, is_reference_only=False)
            node.children = []
            session.add_all([question, node])
            session.flush()

            first = eligibility.question_eligibility(question, node)
            assert eligibility.question_eligibility(question, node) is first is marker
            assert len(calls) == 1
            assert eligibility.cached_question_eligibility(question, node) is marker
            assert len(calls) == 1, "warm lookup must not run the content validator again"

            question.current_version_id = "v2"
            assert eligibility._eligibility_cache_key(question, node, None, None) is None
            assert eligibility.cached_question_eligibility(question, node) is None
            session.flush()
            second = eligibility.question_eligibility(question, node)
            assert second is marker and len(calls) == 2

            node.is_reference_only = True
            assert eligibility._eligibility_cache_key(question, node, None, None) is None
            session.flush()
            third = eligibility.question_eligibility(question, node)
            assert third is marker and len(calls) == 3
    finally:
        engine.dispose()


def test_knowledge_tree_cache_returns_defensive_copy_and_is_invalidated_after_commit():
    from sqlalchemy import Column, Integer, MetaData, Table, create_engine, insert
    from sqlalchemy.orm import Session

    from backend.schemas.knowledge import KnowledgeTreeResponse
    from backend.services import knowledge_tree_cache as cache

    cache._reset_knowledge_tree_cache_for_tests()
    bind = object()
    value = KnowledgeTreeResponse(nodes=[])
    generation = cache.cache_generation()
    cache.cache_knowledge_tree(
        bind=bind, day_bucket="2026-10-16", generation=generation, value=value
    )

    cached = cache.get_cached_knowledge_tree(bind=bind, day_bucket="2026-10-16")
    assert cached is not None and cached is not value
    cached.nodes.append("caller mutation must not touch cached response")
    assert cache.get_cached_knowledge_tree(bind=bind, day_bucket="2026-10-16").nodes == []

    # 资料worker空轮询时也会提交；与树无关的提交不应让缓存每秒失效。
    engine = create_engine("sqlite+pysqlite:///:memory:")
    try:
        metadata = MetaData()
        unrelated = Table("material_processing_jobs", metadata,
                          Column("id", Integer, primary_key=True))
        relevant = Table("questions", metadata,
                         Column("id", Integer, primary_key=True))
        metadata.create_all(engine)
        with Session(engine) as session:
            session.execute(insert(unrelated).values(id=1))
            session.commit()
        assert cache.get_cached_knowledge_tree(bind=bind, day_bucket="2026-10-16") is not None

        with Session(engine) as session:
            session.execute(insert(relevant).values(id=1))
            session.commit()
        assert cache.get_cached_knowledge_tree(bind=bind, day_bucket="2026-10-16") is None
    finally:
        engine.dispose()
