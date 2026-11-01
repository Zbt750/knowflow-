"""Strict automatic question qualification; learner graduation rules stay intact."""
from copy import deepcopy
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import select

from backend.models.learning import DailyPlan, KnowledgePoint, KpMasteryPolicy, PracticeItem, Question
from backend.services.auto_question_review import (
    assess_auto_qualification, attach_codex_independent_review, qualify_public_question,
    question_snapshot_sha256,
)
from backend.services.question_eligibility import question_eligibility
from backend.services.question_generation import assess_output, Output, prepare_codex_public_original, current_generation_binding
from scripts.public_bank_originals import originals
from tests.integration.test_learning_loop import clean_database, client, clock, session_factory


def _candidate(db, *, family="determinant_2x2"):
    selected = next(row for row in originals() if row[0] == family)
    _, keyword, output = selected
    nodes = list(db.scalars(select(KnowledgePoint).where(
        KnowledgePoint.is_active.is_(True), KnowledgePoint.is_assessable.is_(True))))
    matches = [node for node in nodes if keyword in node.name and ".family." not in node.code]
    matches.sort(key=lambda node: (node.name != keyword, len(node.name), node.code))
    assert matches, f"no assessable node for {family}"
    node = matches[0]
    request_id = f"test-auto-review:{uuid4()}"
    candidate = assess_output(output, node, request_id=request_id, mode="original", family=family,
        trace={"model": "codex_offline_authoring", "prompt_version": "test-v1",
               "mode": "codex_offline", "model_calls": 0})
    assert candidate["status"] == "AUTO_PASS", candidate["errors"]
    return candidate["question"], node


def test_development_original_gets_question_qualification_but_does_not_graduate_from_one_attempt(
        session_factory, clean_database, client):
    from backend.mastery.storage import policy_from_storage
    from backend.models.learning import KpState, QuestionAttempt
    from sqlalchemy import func

    with session_factory() as db:
        question, node = _candidate(db)
        policy_row = db.get(KpMasteryPolicy, node.id)
        assert policy_row is not None
        policy_before = {column.name: deepcopy(getattr(policy_row, column.name))
                         for column in KpMasteryPolicy.__table__.columns}
        db.add(question)
        db.flush()
        before_hash = question_snapshot_sha256(question)
        event, result = qualify_public_question(db, question_id=question.id, node_id=node.id,
            expected_snapshot_sha256=before_hash,
            idempotency_key=f"auto-qualify:{question.id}")
        assert event is not None and result["status"] == "AUTO_VERIFIED"
        assert event.qualification_class == "development_original"
        assert result["human_verified"] is False and result["learner_graduated"] is False
        eligible = question_eligibility(question, node)
        assert eligible.practice_eligible
        assert eligible.evidence_capability == "verified_objective"
        assert eligible.auto_review_current and eligible.auto_review_event_id == str(event.id)
        assert question.content_reviewed_by is None and question.answer_reviewed_by is None
        assert question.answer_verification_event_id is None
        assert question.content_trust == "auto_verified"
        assert question.answer_provenance == "auto_verified"
        from backend.schemas.question_trust import QuestionTrustView
        trust_view = QuestionTrustView(**eligible.public_dict())
        assert trust_view.auto_review_current and trust_view.auto_review_event_id == str(event.id)
        db.add(DailyPlan(study_date="2026-01-01", status="active"))
        db.flush()
        plan = db.scalar(select(DailyPlan).where(DailyPlan.study_date == "2026-01-01"))
        item = PracticeItem(plan_id=plan.id, question_id=question.id, kp_id=node.id, ordinal=1)
        db.add(item)
        db.flush()
        item_id = str(item.id)
        correct_answer = question.correct_answer
        db.commit()

    response = client.post(f"/api/practice-items/{item_id}/answer-submissions", json={
        "idempotency_key": f"auto-question-answer:{uuid4()}", "raw_answer": correct_answer,
    })
    assert response.status_code == 200, response.text
    assert response.json()["result"] == "right"
    with session_factory() as db:
        state = db.get(KpState, node.id)
        # KpState.state is persisted as a plain string, not a Python enum.
        assert state is not None and state.state != "mastered"
        attempt = db.scalar(select(QuestionAttempt).where(QuestionAttempt.practice_item_id == item_id))
        assert attempt is not None
        receipt = attempt.grading_evidence
        assert receipt["version"] == 5
        assert receipt["evidence_reliability"] == "verified_objective"
        assert receipt["auto_review_event_id"]
        assert receipt["auto_review_snapshot_sha256"]
        updated_policy = db.get(KpMasteryPolicy, node.id)
        assert {column.name: getattr(updated_policy, column.name)
                for column in KpMasteryPolicy.__table__.columns} == policy_before
        question = db.get(Question, attempt.question_id)
        assert question_eligibility(question, db.get(KnowledgePoint, node.id)).auto_review_current
        # Existing policy is evaluated with its original quotas and cross-day gate.
        assert policy_from_storage(updated_policy).min_day_span == policy_from_storage(policy_row).min_day_span

        question.explanation = question.explanation + " 内容版本已变化。"
        db.flush()
        stale = question_eligibility(question, db.get(KnowledgePoint, node.id))
        assert not stale.auto_review_current
        assert stale.evidence_capability != "verified_objective"
        db.rollback()


def test_hash_bound_codex_review_can_replace_missing_solver_without_claiming_machine_proof(
        session_factory, clean_database, monkeypatch):
    """A content-specific independent review may qualify; the solver allowlist is not the only path."""
    with session_factory() as db:
        # The determinant fixture is fill-blank; this case tests the generic
        # answer/explanation fallback, not the separate choice uniqueness path.
        question, node = _candidate(db, family="determinant_2x2")
        monkeypatch.setattr("backend.services.auto_question_review.verify_problem",
            lambda _question: {"status": "UNSUPPORTED", "reason": "fixture_unseen_expression"})
        answer = str(question.correct_answer).strip().upper()
        receipt = attach_codex_independent_review(question, node,
            derived_answer=answer,
            method_evidence=[
                {"method": "direct_algebraic_derivation", "result": "按行列式定义展开，并逐项计算，得到存储答案。"},
                {"method": "symbolic_cross_check", "result": "独立展开矩阵行列式并化简，结果与直接展开一致。"},
            ],
            explanation_key_steps=[
                "按二阶行列式 ad−bc 展开题目给定矩阵。",
                "代入各矩阵元并化简，与保存答案逐项核对。",
            ])
        db.add(question)
        db.flush()
        result = assess_auto_qualification(db, question, node, all_questions=[question])
        assert result["status"] == "AUTO_VERIFIED", result
        assert result["stages"]["independent_answer"]["adapter"] == "codex_independent_review_v1"
        assert result["stages"]["explanation"]["reason"] == "hash_bound_codex_independent_explanation_review"
        assert result["stages"]["uniqueness"]["status"] in {"PASS", "NOT_APPLICABLE"}
        assert receipt["human_verified"] is False
        before = question_snapshot_sha256(question)
        event, qualified = qualify_public_question(db, question_id=question.id, node_id=node.id,
            expected_snapshot_sha256=before, idempotency_key=f"codex-independent:{question.id}")
        assert event is not None and qualified["status"] == "AUTO_VERIFIED"
        assert event.review_version == "public-question-auto-review-v8"
        assert qualified["human_verified"] is False
        assert qualified["learner_graduated"] is False
        db.rollback()


def test_open_quality_hold_blocks_public_auto_qualification_until_resolved(session_factory, clean_database):
    with session_factory() as db:
        question, node = _candidate(db)
        question.grading_config = {
            **question.grading_config,
            "quality_holds": [{"id": "risk:source-assumption", "status": "OPEN",
                               "reason": "题目依赖尚未确认的来源假设。"}],
        }
        db.add(question)
        db.flush()
        snapshot = question_snapshot_sha256(question)
        event, result = qualify_public_question(db, question_id=question.id, node_id=node.id,
            expected_snapshot_sha256=snapshot, idempotency_key=f"open-risk-hold:{question.id}")
        assert event is None
        assert result["status"] == "QUARANTINED"
        assert result["reason"] == "open_quality_hold_requires_resolution"
        assert result["open_quality_hold_ids"] == ["risk:source-assumption"]
        db.rollback()


def test_version_bound_development_original_can_qualify_on_reference_topic_leaf(
        session_factory, clean_database):
    """A generated public item may be mapped exactly without claiming exam origin."""
    with session_factory() as db:
        question, node = _candidate(db, family="determinant_2x2")
        node.is_reference_only = True
        db.add(question)
        db.flush()
        assert question.grading_config["generation"]["node_code"] == node.code
        before = question_snapshot_sha256(question)
        event, result = qualify_public_question(db, question_id=question.id, node_id=node.id,
            expected_snapshot_sha256=before,
            idempotency_key=f"generated-reference-leaf:{question.id}")
        assert event is not None, result
        assert event.qualification_class == "development_original"
        assert result["stages"]["mapping"]["generated_node_mapping"] is True
        from backend.services.question_eligibility import question_eligibility
        eligibility = question_eligibility(question, node)
        assert eligibility.practice_eligible
        assert eligibility.mapping_status == "auto_reviewed_reference_topic"
        assert eligibility.evidence_capability == "verified_objective"
        assert eligibility.auto_review_current
        # Qualification of an original is a source class, not an exam claim.
        assert question.question_provenance == "ai_generated_practice"
        assert "real_exam" not in (question.grading_config or {}).get("provenance", {}).get("source", {}).values()
        db.rollback()


def test_codex_public_original_review_qualifies_without_family_solver_and_excludes_personal_copy(
        session_factory, clean_database, client):
    """Public originals can qualify and be used in Today; personal copies stay excluded."""
    from backend.services.auto_question_review import infer_qualification_class
    with session_factory() as db:
        node=db.scalar(select(KnowledgePoint).where(
            KnowledgePoint.code=="math.linear-algebra.determinant.properties"))
        assert node is not None and node.is_active and node.is_assessable and not node.children
        output=Output(stem="设矩阵 A=[[1,2],[3,4]]，求 det(Aᵀ)。",
            question_type="fill_blank",correct_answer="-2",final_value="-2",
            explanation="利用转置不改变行列式的性质，det(Aᵀ)=det(A)。按二阶行列式定义计算 1×4−2×3=−2。",
            steps=[{"expression":"1*4-2*3","value":"-2"}])
        question=prepare_codex_public_original(output,node,request_id=f"hx-public-determinant:{uuid4()}",
            derived_answer="-2",
            method_evidence=[
                {"method":"transpose-invariance-and-definition","result":"det(Aᵀ)=det(A)=1×4−2×3=−2，转置不改变行列式。"},
                {"method":"direct-transposed-matrix-expansion","result":"Aᵀ=[[1,3],[2,4]]，直接按 ad−bc 展开为1×4−3×2=−2。"},
            ],
            explanation_key_steps=[
                "先用 det(Aᵀ)=det(A) 将转置行列式化为原矩阵行列式。",
                "代入二阶行列式定义 ad−bc，得到4−6=−2。",
            ], difficulty_reason={
                "knowledge_depth": "考查转置不变量与二阶行列式定义之间的联系。",
                "reasoning_steps": "先识别转置性质，再展开行列式并核对符号。",
                "trap_design": "容易把转置误认为改变行列式符号，或在ad-bc中颠倒乘积。",
                "application_value": "训练在矩阵变换表达与直接计算之间选择更简洁的方法。"})
        assert question.bank_scope=="public" and question.generation_batch_id is None
        assert current_generation_binding(question,node)
        db.add(question); db.flush()
        assessment=assess_auto_qualification(db,question,node,all_questions=[question])
        assert assessment["status"]=="AUTO_VERIFIED", assessment
        assert assessment["stages"]["difficulty"]["status"]=="PASS"
        before=question_snapshot_sha256(question)
        event,result=qualify_public_question(db,question_id=question.id,node_id=node.id,
            expected_snapshot_sha256=before,idempotency_key=f"hx-codex-original:{question.id}")
        assert event is not None and result["status"]=="AUTO_VERIFIED"
        assert event.qualification_class=="development_original"
        assert result["human_verified"] is False and result["learner_graduated"] is False
        # Defense in depth: a hand-assembled v2 public-original record without
        # the four bound rationale fields cannot obtain a fresh AUTO_VERIFIED event.
        from backend.services.question_generation import generation_hash
        qualified_config=deepcopy(question.grading_config)
        prior_review=deepcopy(qualified_config["codex_independent_review"])
        config=deepcopy(question.grading_config)
        config["generation"].pop("difficulty_reason",None)
        config["generation"].pop("difficulty_reason_version",None)
        question.grading_config=config
        attach_codex_independent_review(question,node,
            derived_answer=prior_review["derived_answer"],
            method_evidence=prior_review["method_evidence"],
            explanation_key_steps=prior_review["explanation_check"]["key_steps"],
            option_truth_table=prior_review.get("option_truth_table"))
        config=deepcopy(question.grading_config)
        config["generation"]["verified_content_hash"]=generation_hash(question)
        question.grading_config=config
        missing_reason=assess_auto_qualification(db,question,node,all_questions=[question])
        assert missing_reason["status"]=="REJECTED", missing_reason
        assert missing_reason["stages"]["difficulty"]["status"]=="FAIL"
        # Restore the qualified content after the negative tamper check; the
        # rest of this test exercises the same question through Today/grading.
        question.grading_config=qualified_config
        personal=deepcopy(question)
        personal.id=uuid4(); personal.bank_scope="personal"; personal.generation_batch_id=uuid4()
        assert infer_qualification_class(personal) is None
        assert not current_generation_binding(personal,node)

        # The isolated test database deliberately seeds only a small subset of
        # the production knowledge tree. Create a synthetic 408 leaf here so
        # this end-to-end regression never depends on a particular seed dump.
        deque_node=KnowledgePoint(code=f"test-hx-deque-{uuid4().hex[:8]}",
            name="双端队列",subject="408",is_active=True,is_assessable=True,
            is_reference_only=True)
        db.add(deque_node);db.flush()
        deque_output=Output(stem="哪一种线性数据结构允许在其两端分别进行插入和删除？",
            question_type="single_choice",options={"A":"普通循环队列","B":"栈","C":"双端队列","D":"按优先级取出的优先队列"},
            correct_answer="C",final_value="C",
            explanation="双端队列允许在队头和队尾插入、删除。普通队列受先进先出端点规则约束，栈仅在栈顶操作，优先队列按优先级取元素。",
            steps=[])
        deque_question=prepare_codex_public_original(deque_output,deque_node,
            request_id=f"hx-public-deque:{uuid4()}",derived_answer="C",
            method_evidence=[
                {"method":"operation-definition","result":"双端队列的定义允许两端插入和两端删除，题干描述与其直接对应。"},
                {"method":"alternative-structure-elimination","result":"普通队列、栈、优先队列分别受端点、单端或优先级规则约束，均不满足两端均可插删。"},
            ],
            explanation_key_steps=[
                "双端队列的操作端点包括队头和队尾。",
                "逐一比较其余结构的操作规则，只有双端队列符合题目条件。",
            ],option_truth_table={"A":False,"B":False,"C":True,"D":False},
            skill_tags=["双端队列定义","线性结构操作"], difficulty_reason={
                "knowledge_depth": "同时区分队列、栈、优先队列和双端队列的端点操作约束。",
                "reasoning_steps": "逐项检查插入与删除端点，最后与双端队列接口条件匹配。",
                "trap_design": "把可从两端取元素误当作两端都能插入和删除会选错结构。",
                "application_value": "训练根据数据结构操作语义而非名称关键词选择结构。"})
        db.add(deque_question);db.flush()
        deque_before=question_snapshot_sha256(deque_question)
        deque_event,deque_result=qualify_public_question(db,question_id=deque_question.id,
            node_id=deque_node.id,expected_snapshot_sha256=deque_before,
            idempotency_key=f"hx-codex-original:{deque_question.id}")
        assert deque_event is not None and deque_result["status"]=="AUTO_VERIFIED",deque_result
        assert deque_event.qualification_class=="development_original"

        from backend.models.learning import DailyPlan, PracticeItem, QuestionAttempt, KpState
        plan=DailyPlan(study_date="2026-10-11",status="active")
        db.add(plan);db.flush()
        # Answer submission projects learning state only for nodes seeded by
        # the compact fixture. Give the synthetic 408 node an initial state.
        db.add(KpState(kp_id=deque_node.id,state="unseen"))
        determinant_item=PracticeItem(plan_id=plan.id,question_id=question.id,kp_id=node.id,ordinal=1)
        deque_item=PracticeItem(plan_id=plan.id,question_id=deque_question.id,kp_id=deque_node.id,ordinal=2)
        db.add_all([determinant_item,deque_item]);db.commit()
        determinant_response=client.post(f"/api/practice-items/{determinant_item.id}/answer-submissions",json={
            "idempotency_key":f"hx-original-answer:{uuid4()}","raw_answer":"-2"})
        deque_response=client.post(f"/api/practice-items/{deque_item.id}/answer-submissions",json={
            "idempotency_key":f"hx-original-answer:{uuid4()}","selected_option":"C"})
        assert determinant_response.status_code==200,determinant_response.text
        assert deque_response.status_code==200,deque_response.text
        assert determinant_response.json()["result"]=="right", determinant_response.text
        assert deque_response.json()["result"]=="right"
        # These are public originals with current AUTO_VERIFIED qualification,
        # so an independent correct answer is eligible learning evidence.
        # It is only one confirmation and must not mark either node mastered.
        assert determinant_response.json()["effective_confirmation_count"]==1
        assert deque_response.json()["effective_confirmation_count"]==1
        with session_factory() as verify_db:
            attempts=list(verify_db.scalars(select(QuestionAttempt).where(
                QuestionAttempt.practice_item_id.in_([determinant_item.id,deque_item.id]))))
            assert len(attempts)==2 and all(attempt.grading_evidence for attempt in attempts)
            states=[verify_db.get(KpState,kp_id) for kp_id in (node.id,deque_node.id)]
            assert all(state is not None and state.state!="mastered" for state in states)


@pytest.mark.parametrize("family", ["signed_range", "fcfs_waiting_time", "complete_tree",
    "huffman_wpl", "cache_tag", "ipv4_fragment", "stack_operations", "huffman_nodes",
    "huffman_decode", "stack_arithmetic", "cache_tag_variant", "ipv4_fragment_last",
    "limit_parameters", "span_intersection", "matrix_rank_relation", "span_intersection_diagonal",
    "span_intersection_oblique"])
def test_hs_supported_public_solvers_are_accepted_by_auto_review_allowlist(
        family, session_factory, clean_database):
    """Freshly supported exact solvers may qualify; unsupported ones stay blocked."""
    with session_factory() as db:
        _, keyword, output = next(row for row in originals() if row[0] == family)
        subject = "考研数学" if family in {"limit_parameters", "span_intersection", "matrix_rank_relation",
                                          "span_intersection_diagonal", "span_intersection_oblique"} else "408"
        node = KnowledgePoint(code=f"test-auto-review-{family}-{uuid4().hex[:8]}",
            name=keyword, subject=subject, is_active=True, is_assessable=True,
            is_reference_only=True)
        db.add(node)
        db.flush()
        candidate = assess_output(output, node, request_id=f"test-auto-review:{uuid4()}",
            mode="original", family=family,
            trace={"model": "codex_offline_authoring", "prompt_version": "test-v1",
                   "mode": "codex_offline", "model_calls": 0})
        assert candidate["status"] == "AUTO_PASS", candidate["errors"]
        question = candidate["question"]
        from backend.services.auto_question_review import bind_solver_rendered_generation_explanation
        independent = question.grading_config["generation"]["independent_verification"]
        rendered = bind_solver_rendered_generation_explanation(question, independent)
        if family in {"huffman_wpl", "cache_tag", "ipv4_fragment", "stack_operations",
                      "huffman_nodes", "huffman_decode", "stack_arithmetic",
                      "cache_tag_variant", "ipv4_fragment_last", "limit_parameters",
                      "span_intersection", "matrix_rank_relation", "span_intersection_diagonal",
                      "span_intersection_oblique"}:
            assert rendered is not None and rendered["human_verified"] is False
        db.add(question)
        db.flush()
        result = assess_auto_qualification(db, question, node, all_questions=[question])
        assert result["status"] == "AUTO_VERIFIED", [
            (key, stage.get("status"), stage.get("reason"))
            for key, stage in result["stages"].items() if stage.get("status") != "PASS"
        ]
        assert result["stages"]["independent_answer"]["status"] == "PASS"
        assert result["stages"]["answer_consistency"]["status"] == "PASS"
        assert result["stages"]["explanation"]["status"] == "PASS", result["stages"]["explanation"]
        assert result["stages"]["grading"]["status"] == "PASS"
        db.rollback()


def test_automatic_review_assessment_is_read_only_when_explanation_steps_are_missing(
        session_factory, clean_database):
    with session_factory() as db:
        question, node = _candidate(db, family="determinant_2x2")
        # The qualification service audits persisted public questions. Flush
        # before the read-only assessment so SQLAlchemy applies the public-bank
        # and generation-batch column defaults exactly as production does.
        db.add(question)
        db.flush()
        question.grading_config["generation"]["explanation_steps"] = []
        original_config = deepcopy(question.grading_config)
        result = assess_auto_qualification(db, question, node, all_questions=[question])
        assert result["status"] == "NEEDS_REVIEW", result
        assert result["stages"]["explanation"]["status"] == "UNKNOWN"
        assert question.grading_config == original_config
        assert question.auto_review_event_id is None


def test_personal_ai_question_cannot_receive_public_auto_qualification(session_factory, clean_database):
    with session_factory() as db:
        question, node = _candidate(db)
        question.bank_scope = "personal"
        result = assess_auto_qualification(db, question, node, all_questions=[question])
        assert result["status"] == "QUARANTINED"
        assert result["reason"] == "unsupported_or_personal_production_origin"
        assert question.auto_review_event_id is None


def test_inactive_public_duplicate_blocks_new_formal_question(session_factory, clean_database):
    """An archived public row remains part of global identity checks."""
    with session_factory() as db:
        candidate, node = _candidate(db)
        archived = Question(
            kp_id=node.id,
            question_type=candidate.question_type,
            grading_mode=candidate.grading_mode,
            grading_config=deepcopy(candidate.grading_config),
            stem=candidate.stem,
            options=deepcopy(candidate.options),
            correct_answer=candidate.correct_answer,
            explanation=candidate.explanation,
            question_role=candidate.question_role,
            skill_tags=list(candidate.skill_tags or []),
            estimated_minutes=candidate.estimated_minutes,
            is_variant=candidate.is_variant,
            is_active=False,
            bank_scope="public",
            is_hidden=True,
            question_provenance="legacy_unknown",
            content_trust="unreviewed",
            source_status="unknown",
            answer_provenance="unknown",
            answer_reliability="unknown",
            created_at=datetime(2020, 1, 1, tzinfo=timezone.utc),
            updated_at=datetime(2020, 1, 1, tzinfo=timezone.utc),
        )
        db.add(archived)
        db.flush()
        db.add(candidate)
        db.flush()

        before_hash = question_snapshot_sha256(candidate)
        event, result = qualify_public_question(
            db,
            question_id=candidate.id,
            node_id=node.id,
            expected_snapshot_sha256=before_hash,
            idempotency_key=f"inactive-duplicate:{candidate.id}",
        )

        assert event is None
        assert result["status"] == "NEEDS_REVIEW"
        assert result["stages"]["duplicates"]["status"] == "UNKNOWN"
        assert result["stages"]["duplicates"]["reason"] == "duplicate_canonical_exists"
        assert result["stages"]["duplicates"]["canonical_question_id"] == str(archived.id)
        assert candidate.auto_review_event_id is None
        assert archived.is_active is False and archived.is_hidden is True
        db.rollback()


def test_v2_curated_source_trace_keeps_reconstruction_uncertainty_explicit(
        session_factory, clean_database, monkeypatch, tmp_path):
    import backend.services.auto_question_review as review
    from backend.services.question_attestation import question_content_sha256

    with session_factory() as db:
        question, node = _candidate(db)
        question.question_provenance = "real_exam"
        question.content_trust = "needs_review"
        question.source_status = "traceable"
        question.grading_config = {
            **question.grading_config,
            "provenance": {"source": {"source_type": "exam", "subject": node.subject,
                "year": 2023, "question_number": 6, "citation": "本地来源索引"}},
        }
        monkeypatch.setattr(review, "QUESTION_INTAKE_ROOT", tmp_path)
        asset = tmp_path / "source-pack.json"
        asset.write_text("local hashed source placeholder", encoding="utf-8")
        asset_hash = sha256(asset.read_bytes()).hexdigest()
        evidence = {
            "status": "TRACEABLE", "method": "curated_source_trace_v1",
            "question_content_sha256": question_content_sha256(question),
            "source_archive_sha256": asset_hash, "source_asset_path": "source-pack.json",
            "source_locator": "本地来源索引 / 数学二 / 2023 / Q6",
            "source_identity": {"subject": node.subject, "year": 2023, "question_number": 6},
            "verbatim_verified": False,
            "uncertainties": ["整理表述未与原卷逐字核对"],
            "reconstruction_notes": "整理了公式排版，核心条件与设问仍需按来源索引追溯。",
        }
        valid, record = review._source_trace_matches(question, evidence)
        assert valid is True
        assert record["traceability"] == "TRACEABLE"
        assert record["authenticity"] == "NOT_INDEPENDENTLY_AUTHENTICATED"
        assert record["verbatim_concordance"] == "NOT_CLAIMED"

        incomplete = {**evidence, "uncertainties": [], "reconstruction_notes": ""}
        valid, rejected = review._source_trace_matches(question, incomplete)
        assert valid is False
        assert rejected["status"] == "UNKNOWN"


def test_v1_auto_review_version_remains_supported_without_reinterpretation():
    from backend.services.auto_question_review import AUTO_REVIEW_VERSION, SUPPORTED_AUTO_REVIEW_VERSIONS

    assert AUTO_REVIEW_VERSION == "public-question-auto-review-v8"
    assert "public-question-auto-review-v5" in SUPPORTED_AUTO_REVIEW_VERSIONS
    assert "public-question-auto-review-v4" in SUPPORTED_AUTO_REVIEW_VERSIONS
    assert "public-question-auto-review-v1" in SUPPORTED_AUTO_REVIEW_VERSIONS
    assert "public-question-auto-review-v2" in SUPPORTED_AUTO_REVIEW_VERSIONS
    assert "public-question-auto-review-v6" in SUPPORTED_AUTO_REVIEW_VERSIONS
    assert AUTO_REVIEW_VERSION in SUPPORTED_AUTO_REVIEW_VERSIONS


@pytest.mark.parametrize("saved_verifier", ["bounded-problem-verifiers-v12", "bounded-problem-verifiers-v13", "bounded-problem-verifiers-v14", "bounded-problem-verifiers-v15"])
def test_content_bound_previous_verifier_is_compatible_without_dropping_guards(
        session_factory, clean_database, saved_verifier):
    from backend.services.question_generation import generation_hash, current_generation_binding
    with session_factory() as db:
        question, node = _candidate(db)
        node.is_reference_only = True
        config = deepcopy(question.grading_config)
        config["generation"]["verifier_version"] = saved_verifier
        question.grading_config = config
        config["generation"]["verified_content_hash"] = generation_hash(question)
        question.grading_config = config
        assert current_generation_binding(question, node)
        db.add(question)
        db.flush()
        event, reviewed = qualify_public_question(db, question_id=question.id, node_id=node.id,
            expected_snapshot_sha256=question_snapshot_sha256(question),
            idempotency_key=f"TEST_FIXTURE-legacy-verifier:{question.id}")
        assert event is not None and reviewed["status"] == "AUTO_VERIFIED"
        assert question_eligibility(question, node).auto_review_current
        # A v7 event already binds the exact generated leaf mapping. Preserve
        # that guard for reference-only nodes rather than treating v7 as v1/v2.
        from backend.services.auto_question_review import digest, current_auto_review
        event.review_version = "public-question-auto-review-v7"
        legacy_snapshot = deepcopy(event.audit_snapshot)
        legacy_snapshot["version"] = event.review_version
        event.audit_snapshot = legacy_snapshot
        event.audit_sha256 = digest(legacy_snapshot)
        assert current_auto_review(question, node) is event
        question.stem += " 内容漂移。"
        assert not current_generation_binding(question, node)
        assert not question_eligibility(question, node).auto_review_current
        db.rollback()


@pytest.mark.parametrize("review_version", ["public-question-auto-review-v4", "public-question-auto-review-v5", "public-question-auto-review-v6", "public-question-auto-review-v7", "public-question-auto-review-v8"])
def test_exact_pack_mapped_reference_leaf_can_receive_exam_curated_qualification(
        session_factory, clean_database, monkeypatch, tmp_path, review_version):
    from hashlib import sha256
    from backend.services.question_attestation import question_content_sha256
    from backend.services.auto_question_review import QUESTION_INTAKE_ROOT

    with session_factory() as db:
        question, node = _candidate(db)
        assert not node.children
        asset = tmp_path / "exam-pack.json"
        asset.write_text("synthetic source-pack asset for isolated test", encoding="utf-8")
        monkeypatch.setattr("backend.services.auto_question_review.QUESTION_INTAKE_ROOT", tmp_path)
        node.is_reference_only = True
        question.question_provenance = "real_exam"
        question.content_trust = "needs_review"
        question.source_status = "traceable"
        question.grading_config = {
            **question.grading_config,
            "provenance": {"source": {"source_type": "exam", "subject": node.subject,
                "year": 2023, "question_number": 6, "citation": "本地来源索引"}},
        }
        db.add(question)
        db.flush()
        evidence = {
            "status": "TRACEABLE", "method": "curated_source_trace_v1",
            "question_content_sha256": question_content_sha256(question),
            "source_archive_sha256": sha256(asset.read_bytes()).hexdigest(),
            "source_asset_path": "exam-pack.json", "mapped_node_code": node.code,
            "source_locator": "本地来源索引 / 数学二 / 2023 / Q6",
            "source_identity": {"subject": node.subject, "year": 2023, "question_number": 6},
            "verbatim_verified": False, "uncertainties": ["未独立认证原卷真实性或逐字一致性"],
            "reconstruction_notes": "本地来源包身份和知识节点代码一致；未声称逐字核验。",
        }
        before = question_snapshot_sha256(question)
        event, result = qualify_public_question(db, question_id=question.id, node_id=node.id,
            expected_snapshot_sha256=before, idempotency_key=f"ref-topic-auto:{question.id}",
            source_evidence=evidence)
        assert event is not None, result
        assert event.qualification_class == "exam_curated"
        # TEST_FIXTURE: exercise the same historical mapping schema, without
        # reissuing or changing any real qualification/learner receipt.
        from backend.services.golden_learning_slice import digest
        event.review_version = review_version
        audit = deepcopy(event.audit_snapshot)
        audit["version"] = review_version
        event.audit_snapshot = audit
        event.audit_sha256 = digest(audit)
        eligibility = question_eligibility(question, node)
        assert eligibility.practice_eligible
        assert eligibility.evidence_capability == "verified_objective"
        assert eligibility.mapping_status == "source_attested_reference_topic"
        assert eligibility.auto_review_version == review_version

        wrong_audit = deepcopy(audit)
        wrong_audit["stages"]["mapping"]["source_pack_node_code"] = "cs408.fake.topic"
        event.audit_snapshot = wrong_audit
        event.audit_sha256 = digest(wrong_audit)
        assert not question_eligibility(question, node).auto_review_current
        event.audit_snapshot = audit
        event.audit_sha256 = digest(audit)

        wrong_mapping = {**evidence, "mapped_node_code": "cs408.fake.topic"}
        failed = assess_auto_qualification(db, question, node,
            source_evidence=wrong_mapping, all_questions=[question])
        assert failed["status"] != "AUTO_VERIFIED"
        assert "stages" not in failed or failed["stages"]["mapping"]["status"] != "PASS"


def test_codex_traceable_exam_variant_is_formal_only_with_current_full_review(
        session_factory, clean_database, monkeypatch, tmp_path):
    """TEST_FIXTURE only; source/hash/mapping/quality gates remain in use."""
    from hashlib import sha256
    from backend.services.question_generation import (
        Output, prepare_codex_public_original, generation_hash, CODEX_PUBLIC_VARIANT_VERSION,
    )
    from backend.services.auto_question_review import attach_codex_independent_review
    from backend.services.question_attestation import question_content_sha256
    asset=tmp_path/'parent-pack.json';asset.write_text('TEST_FIXTURE source pack',encoding='utf-8')
    monkeypatch.setattr('backend.services.auto_question_review.QUESTION_INTAKE_ROOT',tmp_path)
    with session_factory() as db:
        parent,node=_candidate(db)
        parent.question_provenance='real_exam';parent.source_status='traceable'
        parent.grading_config={**parent.grading_config,'provenance':{'source':{
            'source_type':'exam','subject':node.subject,'year':2023,'question_number':6,
            'citation':'TEST_FIXTURE 本地合成来源定位2023 Q6，仅用于隔离测试'}}}
        db.add(parent);db.flush()
        parent_trace=dict(status='TRACEABLE',method='curated_source_trace_v1',
            question_content_sha256=question_content_sha256(parent),source_archive_sha256=sha256(asset.read_bytes()).hexdigest(),
            source_asset_path='parent-pack.json',mapped_node_code=node.code,source_locator='TEST_FIXTURE 2023 Q6',
            source_identity={'subject':node.subject,'year':2023,'question_number':6},verbatim_verified=False,
            uncertainties=['TEST_FIXTURE'],reconstruction_notes='TEST_FIXTURE content bound local source trace')
        review=dict(derived_answer='B',method_evidence=[
            dict(method='independent_derivation',result='TEST_FIXTURE：三阶矩阵秩为2，核空间维度3减2等于1。'),
            dict(method='explicit_counterexample',result='TEST_FIXTURE：零空间生成元仅一个且另两列独立，排除维度0、2、3。')],
            explanation_key_steps=['TEST_FIXTURE：应用秩零度定理核维数等于列数减秩。','TEST_FIXTURE：用非零核向量及两列独立交叉确认。'],
            option_truth_table={'A':False,'B':True,'C':False,'D':False})
        q=prepare_codex_public_original(Output(stem='TEST_FIXTURE 三列矩阵秩2，其核空间维数是多少？',
            question_type='single_choice',options={'A':'0','B':'1','C':'2','D':'3'},correct_answer='B',
            explanation='列数3，秩2，所以零空间维数3-2=1。',final_value='1'),
            node,request_id='TEST_FIXTURE.exam-variant:'+str(parent.id),**review,
            difficulty_reason={
                'knowledge_depth':'TEST_FIXTURE：联系矩阵秩与零空间维数的结构关系。',
                'reasoning_steps':'TEST_FIXTURE：识别矩阵列数，再由秩零度定理求维数。',
                'trap_design':'TEST_FIXTURE：容易误用矩阵行数作为线性映射定义域维数。',
                'application_value':'TEST_FIXTURE：训练从秩约束推导线性方程组解空间维数。'})
        config=deepcopy(q.grading_config);config['generation'].update(version=CODEX_PUBLIC_VARIANT_VERSION,
            mode='adapted',parent_question_id=str(parent.id),transformation_summary='TEST_FIXTURE：从原题计算值改为带秩约束求零空间维数，求解任务不同。')
        q.grading_config=config;q.source_status='traceable';q.is_variant=True
        attach_codex_independent_review(q,node,**review)
        config=deepcopy(q.grading_config);config['generation']['verified_content_hash']=generation_hash(q);q.grading_config=config
        source=dict(status='TRACEABLE',method='exam_variant_lineage_v1',parent_question_id=str(parent.id),
            parent_snapshot_sha256=question_snapshot_sha256(parent),question_content_sha256=question_content_sha256(q),
            parent_source_evidence=parent_trace,transformation_summary=config['generation']['transformation_summary'],uncertainties=['TEST_FIXTURE'])
        assert not question_eligibility(q,node).practice_eligible
        db.add(q);db.flush()
        event,result=qualify_public_question(db,question_id=q.id,node_id=node.id,
            expected_snapshot_sha256=question_snapshot_sha256(q),idempotency_key='TEST_FIXTURE.variant:'+str(q.id),source_evidence=source)
        assert event is not None,{k:v for k,v in result.get('stages',{}).items() if v.get('status')!='PASS'}
        e=question_eligibility(q,node)
        assert e.practice_eligible and e.evidence_capability=='verified_objective'
        q.stem+=' 内容漂移。'
        assert not question_eligibility(q,node).practice_eligible
