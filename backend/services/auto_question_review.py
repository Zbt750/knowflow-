"""Hash-bound automatic qualification for a narrow set of public questions.

Automatic qualification is a content-admission decision. It is separate from
human review, never touches learner history, and leaves the graduation policy
thresholds to the existing policy engine.
"""
from __future__ import annotations

from collections import OrderedDict
from copy import deepcopy
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
from threading import RLock
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.models.learning import KnowledgePoint, Question, QuestionAutoReviewEvent
from backend.services.answer_verification import answer_version_sha256
from backend.services.golden_learning_slice import digest
from backend.services.question_attestation import has_current_source_attestation
from backend.services.question_attestation import _subject as canonical_subject
from backend.services.question_production_pipeline import validate_question_content, duplicate_choice_option_pairs
from backend.services.quality_verifiers import verify_problem, VERSION as VERIFIER_VERSION


AUTO_REVIEW_VERSION = "public-question-auto-review-v8"
SUPPORTED_AUTO_REVIEW_VERSIONS = frozenset({
    "public-question-auto-review-v1", "public-question-auto-review-v2", "public-question-auto-review-v3",
    "public-question-auto-review-v4", "public-question-auto-review-v5",
    "public-question-auto-review-v6", "public-question-auto-review-v7", AUTO_REVIEW_VERSION,
})
QUESTION_INTAKE_ROOT = Path(__file__).resolve().parents[2] / "storage" / "question-intake"
AUTO_AUDITOR = "question-quality-pipeline-with-content-bound-independent-review"
CODEX_REVIEW_VERSION = "codex-independent-content-review-v1"
QUALIFICATION_CLASSES = frozenset({"exam_curated", "exam_variant", "development_original"})
_AUTO_REVIEW_MATCH_CACHE_MAX = 8192
_AUTO_REVIEW_MATCH_CACHE: OrderedDict[tuple[Any, ...], bool] = OrderedDict()
_AUTO_REVIEW_MATCH_CACHE_LOCK = RLock()
ALLOWED_SOLVERS = frozenset({
    "phase45d_determinant_2x2_v1", "phase45d_linear_system_2x2_v1",
    "phase45d_binary_search_steps_v1", "phase45d_page_replacement_v1",
    "phase45d_subnet_host_count_v1", "phase45d_full_tree_count_v1",
    "phase45d_complete_tree_storage_index_v1", "phase45d_fixed_point_decode_v1",
    "phase45d_signed_subtract_value_v1", "twos_complement_range_v1",
    "twos_complement_subtract_v1", "complete_tree_index_v1", "binary_rational_v1",
    "polynomial_exponential_derivative_v1", "phase45d_improper_integral_parameter_v1",
    "teaching_family_v1", "chain_differential_v1", "rational_improper_parameter_v1",
    "log1p_improper_integral_v1", "full_binary_tree_edges_v1",
    "phase45i_twos_complement_range_v1", "phase45d_fcfs_waiting_time_v1",
    "phase45i_complete_tree_leaf_count_v1",
})
from backend.services.phase45hs_verifiers import SOLVERS as HS_SOLVERS
from backend.services.phase45hx_exam_verifiers import SOLVERS as HX_EXAM_SOLVERS
ALLOWED_SOLVERS=ALLOWED_SOLVERS|HS_SOLVERS|HX_EXAM_SOLVERS


def question_snapshot_payload(question: Question) -> dict[str, Any]:
    """All fields that can change meaning, qualification, or grading."""
    config = deepcopy(question.grading_config) if isinstance(question.grading_config, dict) else {}
    config.pop("public_practice_release", None)  # ordinary release is a separate use flag
    return {
        "id": str(question.id), "kp_id": str(question.kp_id),
        "question_type": question.question_type, "stem": question.stem,
        "options": question.options, "correct_answer": question.correct_answer,
        "explanation": question.explanation, "skill_tags": list(question.skill_tags or []),
        "question_role": question.question_role, "is_variant": bool(question.is_variant),
        "question_provenance": question.question_provenance,
        "content_trust": question.content_trust, "source_status": question.source_status,
        "answer_provenance": question.answer_provenance,
        "answer_reliability": question.answer_reliability,
        "grading_mode": question.grading_mode, "grading_config": config,
        "bank_scope": getattr(question, "bank_scope", "public"),
        "generation_batch_id": str(question.generation_batch_id) if question.generation_batch_id else None,
        "source_attestation_key": question.source_attestation_key,
        "source_attestation_sha256": question.source_attestation_sha256,
    }


def question_snapshot_sha256(question: Question) -> str:
    return digest(question_snapshot_payload(question))


def _current_event_matches(question: Question, event: QuestionAutoReviewEvent,
                           node: KnowledgePoint | None = None) -> bool:
    stages = (event.audit_snapshot or {}).get("stages", {})
    if (event.event_type != "qualified" or event.question_id != question.id
            or event.review_version not in SUPPORTED_AUTO_REVIEW_VERSIONS
            or (event.audit_snapshot or {}).get("version") != event.review_version
            or getattr(question, "auto_review_event_id", None) != event.id
            or event.question_snapshot_sha256 != question_snapshot_sha256(question)
            or event.answer_sha256 != answer_version_sha256(question)
            or event.audit_sha256 != digest(event.audit_snapshot)
            or (event.audit_snapshot or {}).get("bound_question_snapshot_sha256") != event.question_snapshot_sha256
            or not stages or any(item.get("status") != "PASS" for item in stages.values())):
        return False
    if event.review_version == AUTO_REVIEW_VERSION:
        # v8 qualification already stores the result of the full structural
        # validation (including the duplicate-choice check) inside the
        # hash-bound audit snapshot. Once the live Question snapshot matches
        # that immutable receipt and the receipt hash is valid, re-running the
        # same parser/option checks on every read is redundant. Keep the rule
        # version explicit so older or incomplete receipts do not inherit this
        # shortcut. Legacy receipt versions retain the live fail-closed check.
        structure = stages.get("structure")
        if (not isinstance(structure, dict)
                or structure.get("status") != "PASS"
                or structure.get("option_content_rule_version") != "distinct-choice-content-v1"):
            return False
    elif validate_question_content(question).completeness != "complete":
        return False
    if getattr(question, "bank_scope", "public") != "public" or question.generation_batch_id:
        return False
    expected_class = infer_qualification_class(question)
    if expected_class != event.qualification_class:
        return False
    if node is not None:
        mapping = stages.get("mapping", {})
        if (node.id != question.kp_id or not node.is_active or not node.is_assessable
                or bool(node.children)):
            return False
        if event.review_version in {'public-question-auto-review-v3', 'public-question-auto-review-v4',
                'public-question-auto-review-v5', 'public-question-auto-review-v6',
                'public-question-auto-review-v7', AUTO_REVIEW_VERSION}:
            if (mapping.get("node_id") != str(node.id) or mapping.get("node_code") != node.code
                    or mapping.get("node_subject") != node.subject):
                return False
            if node.is_reference_only:
                source_mapped_exam = (event.qualification_class == "exam_curated"
                    and mapping.get("source_pack_node_code") == node.code
                    and mapping.get("reference_topic_mapping") is True)
                generated_exact_mapping = False
                if event.qualification_class in {"development_original", "exam_variant"}:
                    from backend.services.question_generation import current_generation_binding
                    generated_exact_mapping = (mapping.get("generated_node_mapping") is True
                        and mapping.get("node_code") == node.code
                        and current_generation_binding(question, node))
                if not (source_mapped_exam or generated_exact_mapping):
                    return False
        elif node.is_reference_only:
            # v1/v2 never qualified a reference-only mapping; do not reinterpret
            # their historical receipts under the new source-pack mapping rule.
            return False
    return True


def _current_event_cache_key(question: Question, event: QuestionAutoReviewEvent,
                             node: KnowledgePoint | None) -> tuple[Any, ...] | None:
    """Key a positive v8 receipt check by immutable version and mapping state.

    Automatic-review events are append-only in PostgreSQL and every supported
    Question mutation creates a new QuestionVersion. Including both version
    identity and updated_at means a different content revision cannot reuse an
    old positive check. This cache stores no eligibility decision and is only
    used after the full hash/audit check has succeeded once in this process.
    """
    version_id = getattr(question, "current_version_id", None)
    if event.review_version != AUTO_REVIEW_VERSION or version_id is None:
        return None
    # Do not reuse a positive cache entry while an ORM object involved in the
    # decision has unflushed changes. Supported Question writes append a new
    # version during flush; this guard also handles a caller checking a dirty
    # object before that flush happens.
    try:
        from sqlalchemy import inspect as sa_inspect
        from backend.services.question_versions import VERSION_FIELDS
        question_state = sa_inspect(question)
        if any(question_state.attrs[name].history.has_changes() for name in VERSION_FIELDS):
            return None
        event_state = sa_inspect(event)
        if any(event_state.attrs[name].history.has_changes() for name in (
                "event_type", "qualification_class", "review_version",
                "question_snapshot_sha256", "answer_sha256", "audit_sha256", "audit_snapshot")):
            return None
        if node is not None:
            node_state_orm = sa_inspect(node)
            if any(node_state_orm.attrs[name].history.has_changes() for name in (
                    "code", "subject", "is_active", "is_assessable", "is_reference_only", "children")):
                return None
    except Exception:
        # Lightweight test doubles have no ORM state. For mapped-looking
        # objects, an inspection failure means we skip the optimization.
        if hasattr(question, "_sa_instance_state"):
            return None
    if node is None:
        node_state: tuple[Any, ...] = (None,)
    else:
        node_state = (
            str(node.id), node.code, node.subject, bool(node.is_active),
            bool(node.is_assessable), bool(node.is_reference_only),
            bool(getattr(node, "children", None)),
        )
    return (
        str(question.id), str(version_id), getattr(question, "updated_at", None),
        str(getattr(question, "auto_review_event_id", None)),
        bool(getattr(question, "is_active", True)), bool(getattr(question, "is_hidden", False)),
        getattr(question, "bank_scope", "public"),
        str(getattr(question, "generation_batch_id", None)),
        str(event.id), event.event_type, event.review_version, event.qualification_class,
        event.question_snapshot_sha256, event.answer_sha256, event.audit_sha256,
        node_state,
    )


def _cached_current_event_match(key: tuple[Any, ...]) -> bool:
    with _AUTO_REVIEW_MATCH_CACHE_LOCK:
        valid = _AUTO_REVIEW_MATCH_CACHE.get(key)
        if valid is None:
            return False
        _AUTO_REVIEW_MATCH_CACHE.move_to_end(key)
        return valid


def _remember_current_event_match(key: tuple[Any, ...]) -> None:
    with _AUTO_REVIEW_MATCH_CACHE_LOCK:
        _AUTO_REVIEW_MATCH_CACHE[key] = True
        _AUTO_REVIEW_MATCH_CACHE.move_to_end(key)
        while len(_AUTO_REVIEW_MATCH_CACHE) > _AUTO_REVIEW_MATCH_CACHE_MAX:
            _AUTO_REVIEW_MATCH_CACHE.popitem(last=False)


def current_auto_review(question: Question, node: KnowledgePoint | None = None,
                        *, events: dict | None = None) -> QuestionAutoReviewEvent | None:
    event_id = getattr(question, "auto_review_event_id", None)
    # 没有事件引用时绝不触碰 relationship，避免每道题一次懒加载 SELECT。
    if event_id is None:
        return None
    # 请求级映射优先；映射未命中或未提供时回退到 relationship，保证语义不变。
    event = (events.get(str(event_id)) if events else None)
    if event is None:
        event = getattr(question, "current_auto_review", None)
    if event_id is None or event is None or event.id != event_id:
        return None
    cache_key = _current_event_cache_key(question, event, node)
    if cache_key is not None and _cached_current_event_match(cache_key):
        return event
    try:
        matches = _current_event_matches(question, event, node)
        if matches and cache_key is not None:
            _remember_current_event_match(cache_key)
        return event if matches else None
    except Exception:
        return None


def infer_qualification_class(question: Question) -> str | None:
    """Derive public content production path from stable lineage, never model name."""
    if getattr(question, "bank_scope", "public") != "public" or question.generation_batch_id:
        return None
    generation = (question.grading_config or {}).get("generation", {})
    if not isinstance(generation, dict):
        generation = {}
    if question.question_provenance == "real_exam":
        return "exam_curated"
    if (generation.get("mode") == "adapted" and question.is_variant
            and generation.get("parent_question_id")):
        return "exam_variant"
    if (generation.get("mode") == "original" and generation.get("authoring_mode") in {
            "codex_offline", "codex_development", "real_model"}
            and not generation.get("parent_question_id")):
        return "development_original"
    return None


def _grading_tests(question: Question) -> dict[str, Any]:
    """Run the production comparator against right/wrong/blank/invalid values."""
    from backend.services.answer_grading import grade_final_answer

    config = question.grading_config if isinstance(question.grading_config, dict) else {}
    method = config.get("method")
    expected = question.correct_answer
    options = question.options if isinstance(question.options, dict) else None
    if config.get("verified") is not True or method not in {"single_choice", "numeric_final", "logarithm_final", "constant_final"}:
        return {"status": "UNKNOWN", "reason": "unsupported_formal_grader"}
    if method == "single_choice":
        wrong = next((str(key) for key in options or {} if str(key).strip().upper() != str(expected).strip().upper()), None)
        cases = [
            ("expected", expected, "right"), ("other_valid_choice", wrong, "wrong"),
            ("blank", "", "unknown"), ("invalid_choice", "Z", "unknown"),
        ]
        actual = [grade_final_answer(question_type=question.question_type, config=config,
            answer=None, selected_option=value, expected=expected, options=options).result for _, value, _ in cases]
    elif method == "numeric_final":
        cases = [("expected", expected, "right"), ("wrong_integer", "987654321", "wrong"),
                 ("blank", "", "unknown"), ("invalid_expression", "x+1", "unknown")]
        actual = [grade_final_answer(question_type=question.question_type, config=config,
            answer=value, selected_option=None, expected=expected, options=options).result for _, value, _ in cases]
    elif method=='constant_final':
        cases=[('expected',expected,'right'),('wrong_integer','987654321','wrong'),('blank','','unknown'),('invalid_expression','x+1','unknown')]
        actual=[grade_final_answer(question_type=question.question_type,config=config,answer=raw,selected_option=None,expected=expected,options=options).result for _,raw,_ in cases]
    else:
        wrong = "ln(2)" if expected != "ln(2)" else "ln(3)"
        cases = [("expected", expected, "right"), ("wrong_log", wrong, "wrong"),
                 ("blank", "", "unknown"), ("invalid_expression", "ln(x)", "unknown")]
        actual = [grade_final_answer(question_type=question.question_type, config=config,
            answer=value, selected_option=None, expected=expected, options=options).result for _, value, _ in cases]
    result = [{"case": label, "expected": want, "actual": got} for (label, _, want), got in zip(cases, actual)]
    return {"status": "PASS" if all(row["expected"] == row["actual"] for row in result) else "FAIL",
            "method": method, "cases": result}


def _review_answer_matches(question: Question, derived_answer: Any) -> bool:
    if not isinstance(derived_answer, str) or not derived_answer.strip():
        return False
    if question.question_type == "single_choice":
        return derived_answer.strip().upper() == str(question.correct_answer).strip().upper()
    from backend.services.constant_expression import compare_constant_expressions
    return compare_constant_expressions(derived_answer, question.correct_answer) == "right"


def make_codex_independent_review(question: Question, node: KnowledgePoint, *,
                                  derived_answer: str, method_evidence: list[dict[str, str]],
                                  explanation_key_steps: list[str],
                                  option_truth_table: dict[str, bool] | None = None,
                                  reviewed_on: str | None = None) -> dict[str, Any]:
    """Create a content-bound review receipt from an actual independent review.

    This records Codex review evidence; it is not a theorem prover and never
    claims HUMAN_VERIFIED.  Formal admission still runs the source, structure,
    node mapping, global duplicate and production-grader gates.
    """
    from hashlib import sha256
    from backend.services.question_attestation import question_content_sha256
    if node.id != question.kp_id or not node.is_active or not node.is_assessable or bool(node.children):
        raise ValueError("codex_review_requires_active_assessable_leaf_mapping")
    if not _review_answer_matches(question, derived_answer):
        raise ValueError("independent_derivation_conflicts_with_stored_answer")
    methods = method_evidence if isinstance(method_evidence, list) else []
    method_ids = [item.get("method") for item in methods if isinstance(item, dict)]
    if (len(methods) < 2 or len(set(method_ids)) != len(methods)
            or any(not isinstance(item.get("method"), str) or not item["method"].strip()
                   or not isinstance(item.get("result"), str) or len(item["result"].strip()) < 20
                   for item in methods if isinstance(item, dict))
            or any(not isinstance(item, dict) for item in methods)):
        raise ValueError("independent_review_requires_two_distinct_documented_methods")
    steps = explanation_key_steps if isinstance(explanation_key_steps, list) else []
    if len(steps) < 2 or any(not isinstance(step, str) or len(step.strip()) < 10 for step in steps):
        raise ValueError("independent_explanation_review_requires_key_steps")
    if question.question_type == "single_choice":
        options = question.options if isinstance(question.options, dict) else {}
        if duplicate_choice_option_pairs(options):
            raise ValueError("single_choice_review_requires_distinct_option_content")
        if (not isinstance(option_truth_table, dict) or set(option_truth_table) != set(options)
                or any(not isinstance(value, bool) for value in option_truth_table.values())
                or sum(option_truth_table.values()) != 1
                or option_truth_table.get(str(derived_answer).strip().upper()) is not True):
            raise ValueError("single_choice_review_requires_exactly_one_correct_option")
    elif option_truth_table is not None:
        raise ValueError("option_truth_table_only_applies_to_single_choice")
    timestamp = reviewed_on or datetime.now(timezone.utc).date().isoformat()
    try:
        datetime.fromisoformat(timestamp)
    except (TypeError, ValueError) as exc:
        raise ValueError("review_date_must_be_iso_date") from exc
    return {
        "version": CODEX_REVIEW_VERSION,
        "reviewer_kind": "codex_independent_review",
        "human_verified": False,
        "reviewed_on": timestamp,
        "node_code": node.code,
        "question_content_sha256": question_content_sha256(question),
        "answer_sha256": answer_version_sha256(question),
        "explanation_sha256": sha256(str(question.explanation or "").encode("utf-8")).hexdigest(),
        "derived_answer": derived_answer.strip(),
        "method_evidence": deepcopy(methods),
        "explanation_check": {"status": "PASS", "key_steps": list(steps)},
        "option_truth_table": deepcopy(option_truth_table),
    }


def attach_codex_independent_review(question: Question, node: KnowledgePoint, **review: Any) -> dict[str, Any]:
    receipt = make_codex_independent_review(question, node, **review)
    config = deepcopy(question.grading_config) if isinstance(question.grading_config, dict) else {}
    config["codex_independent_review"] = receipt
    question.grading_config = config
    return receipt


def current_codex_independent_review(question: Question, node: KnowledgePoint) -> dict[str, Any] | None:
    from hashlib import sha256
    from backend.services.question_attestation import question_content_sha256
    config = question.grading_config if isinstance(question.grading_config, dict) else {}
    receipt = config.get("codex_independent_review")
    if not isinstance(receipt, dict):
        return None
    if (receipt.get("version") != CODEX_REVIEW_VERSION
            or receipt.get("reviewer_kind") != "codex_independent_review"
            or receipt.get("human_verified") is not False
            or receipt.get("node_code") != node.code
            or receipt.get("question_content_sha256") != question_content_sha256(question)
            or receipt.get("answer_sha256") != answer_version_sha256(question)
            or receipt.get("explanation_sha256") != sha256(str(question.explanation or "").encode("utf-8")).hexdigest()
            or not _review_answer_matches(question, receipt.get("derived_answer"))):
        return None
    methods = receipt.get("method_evidence")
    explanation = receipt.get("explanation_check")
    if (not isinstance(methods, list) or len(methods) < 2
            or len({item.get("method") for item in methods if isinstance(item, dict)}) != len(methods)
            or not isinstance(explanation, dict) or explanation.get("status") != "PASS"
            or not isinstance(explanation.get("key_steps"), list) or len(explanation["key_steps"]) < 2):
        return None
    if question.question_type == "single_choice":
        truth = receipt.get("option_truth_table")
        options = question.options if isinstance(question.options, dict) else {}
        if duplicate_choice_option_pairs(options):
            return None
        if (not isinstance(truth, dict) or set(truth) != set(options)
                or any(not isinstance(value, bool) for value in truth.values())
                or sum(truth.values()) != 1
                or truth.get(str(question.correct_answer).strip().upper()) is not True):
            return None
    return receipt


def _explanation_check(question: Question, independent: dict[str, Any],
                       codex_review: dict[str, Any] | None = None) -> dict[str, Any]:
    if isinstance(codex_review, dict):
        checked = codex_review.get("explanation_check", {})
        key_steps = checked.get("key_steps") if isinstance(checked, dict) else None
        if (checked.get("status") == "PASS" and isinstance(key_steps, list) and len(key_steps) >= 2
                and codex_review.get("explanation_sha256")
                == sha256(str(question.explanation or "").encode("utf-8")).hexdigest()):
            return {"status": "PASS", "reason": "hash_bound_codex_independent_explanation_review",
                    "review_version": codex_review.get("version"),
                    "key_step_count": len(key_steps), "human_verified": False}
    generation = (question.grading_config or {}).get("generation", {})
    if not isinstance(generation, dict):
        return {"status": "UNKNOWN", "reason": "no_machine_checkable_solution_steps"}
    steps = generation.get("explanation_steps")
    final_value = generation.get("final_value")
    if not isinstance(steps, list) or not steps or not isinstance(final_value, str):
        record = generation.get("machine_explanation") if isinstance(generation, dict) else None
        rendered = render_curated_explanation(question, independent)
        from backend.services.question_attestation import question_content_sha256
        expected_text = rendered[0] if rendered else None
        expected_hash = sha256((expected_text or "").encode("utf-8")).hexdigest()
        valid = bool(expected_text and question.explanation == expected_text and isinstance(record, dict)
            and record.get("version") == "curated-solver-explanation-v1"
            and record.get("adapter") == independent.get("adapter")
            and record.get("question_content_sha256") == question_content_sha256(question)
            and record.get("answer_sha256") == answer_version_sha256(question)
            and record.get("proof_sha256") == digest(independent.get("proof"))
            and record.get("explanation_sha256") == expected_hash)
        return {"status": "PASS" if valid else "UNKNOWN",
            "reason": "allowlisted_deterministic_explanation_bound_to_current_problem" if valid
            else "no_machine_checkable_solution_steps",
            "adapter": independent.get("adapter"), "explanation_sha256": expected_hash if valid else None}
    from backend.services.question_generation import verify_explanation_step
    from backend.services.constant_expression import compare_constant_expressions
    checked = []
    for step in steps:
        if not isinstance(step, dict) or set(step) != {"expression", "value"}:
            checked.append("unknown")
        else:
            checked.append(verify_explanation_step(step["expression"], step["value"]))
    target = ((question.options or {}).get(question.correct_answer)
              if question.question_type == "single_choice" else question.correct_answer)
    final_matches = (final_value.strip().upper() == str(target).strip().upper()
                     if question.question_type == "single_choice"
                     else compare_constant_expressions(final_value, target) == "right")
    status = "PASS" if all(value == "right" for value in checked) and final_matches else "FAIL"
    return {"status": status, "reason": "bounded_solution_steps_and_final_value_checked",
            "checked_steps": checked, "final_value_matches_answer": final_matches,
            "scope": "structured arithmetic steps only; not a general proof checker"}


def render_curated_explanation(question: Question, independent: dict[str, Any]) -> tuple[str, dict[str, Any]] | None:
    """Render explanations only for explicitly bounded deterministic adapters.

    This is a content repair for an isolated/curated public question, not a
    general proof checker. The exact renderer output is hash-bound in review.
    """
    if independent.get("status") != "PASS" or independent.get("adapter") not in ALLOWED_SOLVERS:
        return None
    from backend.services.phase45hs_verifiers import explanation
    historical=explanation(question,independent)
    if historical is not None:return historical
    adapter = independent.get("adapter")
    proof = independent.get("proof") if isinstance(independent.get("proof"), dict) else {}
    answer = independent.get("derived_answer")
    if adapter == "hx_sparse_matrix_compression_v1":
        checked = proof.get("options_checked")
        if not isinstance(checked, dict) or proof.get("rule") is None:
            return None
        text = ("稀疏矩阵压缩存储需要保留非零元素及其行列位置。三元组表用(行号、列号、数值)记录非零项，"
                "十字链表分别连接同一行和同一列的非零结点；邻接矩阵仍占平方级空间，二叉链表也不是矩阵压缩表示。"
                f"逐项对照选项后，只有 {answer} 同时包含这两种结构。")
    elif adapter == "hx_preorder_equals_inorder_v1":
        if not isinstance(proof.get("proof"), str) or "no left subtree" not in proof["proof"]:
            return None
        text = ("先序遍历首先访问根；中序遍历先访问左子树再访问根。两序列相同要求根没有左子树。"
                "对子树递归应用同一条件，可知每个非叶结点只能有右子树，因此答案为 " + str(answer) + "。")
    elif adapter == "hx_binary_tree_postorder_depth_v1":
        order, target, depth = proof.get("derived_postorder"), proof.get("target_node"), proof.get("target_depth_zero_based")
        if not isinstance(order, list) or not isinstance(target, str) or not isinstance(depth, int):
            return None
        text = (f"按题面转写的左右孩子关系递归生成后序序列，得到 {','.join(order)}，与题干相符。"
                f"结点 {target} 的深度为 {depth}（根深度记为0）；选项中只有结点 {proof.get('options_checked', {}).get(answer)}"
                f"处于同一层，所以答案为 {answer}。")
    elif adapter == "hx_unaligned_memory_transfer_cycles_v1":
        address, offset = proof.get("address_hex"), proof.get("address_mod_transfer_bytes")
        size, transfer, cycles = (proof.get("value_bytes_double"), proof.get("transfer_bytes_per_cycle"),
            proof.get("derived_cycles"))
        if not isinstance(address, str) or not all(isinstance(v, int) for v in (offset, size, transfer, cycles)):
            return None
        text = (f"double 占 {size} 字节，地址 0x{address} 对 {transfer} 字节传送宽度的偏移为 {offset} 字节。"
                f"从该偏移开始覆盖 {offset + size} 个字节位置，每个存储周期最多传送 {transfer} 字节，"
                f"需向上取整为 {cycles} 个周期，故选 {answer}。")
    elif adapter == "binary_rational_v1":
        tests = proof.get("rational_denominator_test")
        if not isinstance(tests, dict) or not tests:
            return None
        details = []
        for key, item in tests.items():
            if not isinstance(item, dict) or not isinstance(item.get("denominator"), int):
                return None
            details.append(f"{key} 项约分后的分母为 {item['denominator']}，"
                + ("含有 2 以外的质因数，不能表示为有限二进制小数" if item.get("finite_binary") is False
                   else "只含因子 2，可表示为有限二进制小数"))
        text = "有限二进制小数化为最简分数后，分母必须是 2 的幂。" + "；".join(details) + f"。因此答案为 {answer}。"
    elif adapter == "twos_complement_range_v1":
        bits, low, high = proof.get("bits"), proof.get("minimum"), proof.get("maximum")
        if not all(isinstance(value, int) for value in (bits, low, high)) or bits < 2:
            return None
        text = (f"{bits} 位补码最高位为符号位，数值范围为 −2^({bits}−1) 至 2^({bits}−1)−1；"
                f"代入得到 [{low}, {high}]，对应选项 {answer}。")
    elif adapter == "twos_complement_subtract_v1":
        bits, x, y = proof.get("bits"), proof.get("x"), proof.get("y")
        exact, wrapped, overflow = proof.get("exact_difference"), proof.get("wrapped_signed"), proof.get("OF")
        if not all(isinstance(value, int) for value in (bits, x, y, exact, wrapped, overflow)):
            return None
        text = (f"按 {bits} 位补码解码，x={x}、y={y}，故数学差 x−y={exact}。"
                f"结果按 {bits} 位截取后补码解释为 {wrapped}，数学差超出该位数的有符号范围，OF={overflow}，"
                f"因此选 {answer}。")
    elif adapter == "chain_differential_v1":
        if not isinstance(proof.get("chain_rule"), str) or not isinstance(proof.get("premises"), str):
            return None
        text = (f"由题设微分式可得相应点的偏导数：{proof['premises']}。"
                f"再用复合函数求导法则，并在 x=1 代入：{proof['chain_rule']}。"
                f"所以结果为 {answer}。")
    elif adapter == "rational_improper_parameter_v1":
        required = ("domain", "primitive", "endpoint_value", "unique_solution")
        if any(not isinstance(proof.get(key), str) for key in required):
            return None
        text = (f"先检查反常积分的收敛条件：{proof['domain']}。在该范围内原函数为 {proof['primitive']}；"
                f"计算端点极限得 {proof['endpoint_value']}。令积分值等于题设，得到 {proof['unique_solution']}，"
                f"故答案为 {answer}。")
    elif adapter == "log1p_improper_integral_v1":
        if proof.get("primitive_derivative_checked") is not True or proof.get("lower_limit") != "-1" or proof.get("upper_limit") != "0":
            return None
        text = ("取原函数 F(x)=−(ln(1+x)+1)/(1+x)，其导数等于被积函数。"
                "下限 x=0 时 F(0)=−1，上限趋于无穷时 F(x)→0；因此反常积分为 0−(−1)=1。")
    elif adapter == "full_binary_tree_edges_v1":
        if proof.get("premises") != "nonempty tree; every nonleaf has exactly two children; k leaves":
            return None
        text = ("设分支结点数为 n₂、总结点数为 n。树中除根外每个结点有一条入边，故边数 n−1；"
                "每个分支结点恰有两个孩子，故边数又为 2n₂，于是 n₂=(n−1)/2。"
                "又 n=k+n₂，联立得 n=2k−1，因此选项为 " + str(answer) + "。")
    elif adapter == "polynomial_exponential_derivative_v1":
        if proof.get("order") != 5 or proof.get("point") != 1:
            return None
        crosscheck = proof.get("crosscheck")
        if not isinstance(crosscheck, str) or "31" not in crosscheck:
            return None
        text = ("对 x²eˣ 使用 Leibniz 公式，五阶导数为 eˣ(x²+10x+20)；"
                "多项式项 x² 的五阶导数为 0。代入 x=1 得 31e，因此答案为 " + str(answer) + "。")
    else:
        return None
    return text, {"adapter": adapter, "proof": proof}


def curated_explanation_record(question: Question, independent: dict[str, Any]) -> dict[str, Any] | None:
    rendered = render_curated_explanation(question, independent)
    if rendered is None:
        return None
    from backend.services.question_attestation import question_content_sha256
    text, details = rendered
    return {"version": "curated-solver-explanation-v1", "adapter": details["adapter"],
        "question_content_sha256": question_content_sha256(question),
        "answer_sha256": answer_version_sha256(question),
        "proof_sha256": digest(independent.get("proof")),
        "explanation_sha256": sha256(text.encode("utf-8")).hexdigest(),
        "method": "fixed_template_from_allowlisted_deterministic_solver", "human_verified": False}


def bind_solver_rendered_generation_explanation(question: Question,
                                               independent: dict[str, Any]) -> dict[str, Any] | None:
    """Replace an authored explanation with a version-bound allowlisted solver rendering.

    This is useful when a deterministic solver has a complete trace but the
    generic arithmetic-step checker cannot express that proof (e.g. stack
    operations or tuple-valued networking answers). It does not mark the item
    human reviewed and never changes the independent answer result.
    """
    generation = deepcopy((question.grading_config or {}).get("generation"))
    if not isinstance(generation, dict):
        return None
    rendered = render_curated_explanation(question, independent)
    if rendered is None:
        return None
    before_sha = sha256(str(question.explanation or "").encode("utf-8")).hexdigest()
    generation["author_explanation_sha256_before_solver_render"] = before_sha
    generation["author_explanation_steps_before_solver_render"] = deepcopy(
        generation.get("explanation_steps", []))
    generation["explanation_steps"] = []
    question.explanation = rendered[0]
    question.grading_config = {**(question.grading_config or {}), "generation": generation}
    machine_record = curated_explanation_record(question, independent)
    if machine_record is None:
        return None
    generation["machine_explanation"] = machine_record
    from backend.services.question_generation import generation_hash
    generation["verified_content_hash"] = generation_hash(question)
    question.grading_config = {**(question.grading_config or {}), "generation": generation}
    return {"kind": "allowlisted_solver_rendered", "adapter": machine_record["adapter"],
        "human_verified": False, "author_explanation_sha256_before_render": before_sha,
        "machine_explanation_sha256": machine_record["explanation_sha256"]}


def prepare_exam_curated_repair(question: Question, node: KnowledgePoint,
                                source_evidence: dict[str, Any]) -> dict[str, Any]:
    """Apply a bounded, reversible content repair to an isolated exam question.

    Only answer/explanation evidence and provenance metadata are prepared. The
    stem, choices, answer key, mappings, learner history and graduation policy
    are never touched. The caller must constrain writes to an owned isolated DB.
    """
    if (question.bank_scope != "public" or question.generation_batch_id
            or node.id != question.kp_id or not node.is_active or not node.is_assessable
            or bool(node.children)
            or source_evidence.get("mapped_node_code") != node.code
            or source_evidence.get("question_content_sha256")
            != __import__("backend.services.question_attestation", fromlist=["question_content_sha256"])
                .question_content_sha256(question)):
        raise ValueError("curated_repair_requires_exact_public_source_pack_and_node_mapping")
    source = _source_metadata(question)
    if source.get("source_type") != "exam":
        raise ValueError("curated_repair_requires_exam_source_declaration")
    if question.question_provenance not in {"legacy_unknown", "real_exam"}:
        raise ValueError("unsupported_origin_for_exam_curated_repair")
    independent = verify_problem(question)
    if independent.get("status") != "PASS" or independent.get("adapter") not in ALLOWED_SOLVERS:
        raise ValueError("no_allowlisted_independent_solution")
    rendered = render_curated_explanation(question, independent)
    if rendered is None:
        raise ValueError("no_bounded_explanation_renderer")
    from backend.services.answer_verification import answer_version_sha256
    before = {"question_snapshot_sha256": question_snapshot_sha256(question),
        "question_content_sha256": __import__("backend.services.question_attestation", fromlist=["question_content_sha256"])
            .question_content_sha256(question), "answer_sha256": answer_version_sha256(question),
        "question_provenance": question.question_provenance, "source_status": question.source_status,
        "explanation": question.explanation}
    text, _ = rendered
    config = deepcopy(question.grading_config) if isinstance(question.grading_config, dict) else {}
    generation = deepcopy(config.get("generation")) if isinstance(config.get("generation"), dict) else {}
    revisions = list(config.get("content_revisions", [])) if isinstance(config.get("content_revisions"), list) else []
    question.explanation = text
    # Bind the renderer metadata to the repaired/current content hash, not the
    # pre-repair explanation hash. Otherwise the new audit would immediately be
    # stale as soon as the explanation is written.
    record = curated_explanation_record(question, independent)
    if record is None:
        raise ValueError("curated_explanation_record_unavailable")
    revisions.append({"version": "phase45hr-curated-repair-v1", "before": before,
        "after_explanation_sha256": record["explanation_sha256"],
        "independent_verification": independent, "human_verified": False})
    config["content_revisions"] = revisions
    generation["independent_verification"] = independent
    generation["machine_explanation"] = record
    config["generation"] = generation
    question.grading_config = config
    question.question_provenance = "real_exam"
    question.source_status = "traceable"
    return {"question_id": str(question.id), "before": before,
        "after_question_snapshot_sha256": question_snapshot_sha256(question),
        "after_question_content_sha256": __import__("backend.services.question_attestation", fromlist=["question_content_sha256"])
            .question_content_sha256(question),
        "after_explanation_sha256": record["explanation_sha256"],
        "solver_adapter": independent["adapter"], "repair_version": "phase45hr-curated-repair-v1",
        "changed_fields": ["explanation", "grading_config.content_revisions", "grading_config.generation", "question_provenance", "source_status"],
        "stem_answer_options_mapping_unchanged": True, "human_verified": False}


def _source_metadata(question: Question) -> dict[str, Any]:
    config = question.grading_config if isinstance(question.grading_config, dict) else {}
    provenance = config.get("provenance") if isinstance(config.get("provenance"), dict) else {}
    source = provenance.get("source") if isinstance(provenance.get("source"), dict) else {}
    return source


def _source_trace_matches(question: Question, evidence: dict[str, Any] | None) -> tuple[bool, dict[str, Any]]:
    """Bind source identity clues without claiming verbatim page concordance.

    H v2 deliberately separates provenance traceability from transcription
    fidelity. A source trace can support a curated question candidate only
    when it matches the stored source identity, current question content hash,
    and a hashed local source asset. Unresolved wording differences are kept
    explicit in the immutable audit event.
    """
    import re
    from backend.services.question_attestation import question_content_sha256

    metadata = _source_metadata(question)
    evidence = evidence if isinstance(evidence, dict) else {}
    identity = evidence.get("source_identity") if isinstance(evidence.get("source_identity"), dict) else {}
    subject = str(metadata.get("subject") or "").strip()
    year = metadata.get("year")
    number = metadata.get("question_number")
    citation = str(metadata.get("citation") or "").strip()
    asset_sha = str(evidence.get("source_archive_sha256") or "").lower()
    asset_path = str(evidence.get("source_asset_path") or "")
    source_locator = str(evidence.get("source_locator") or "").strip()
    uncertainties = evidence.get("uncertainties")
    notes = str(evidence.get("reconstruction_notes") or "").strip()
    verbatim = evidence.get("verbatim_verified")
    expected = {"subject": subject, "year": year, "question_number": number}
    identity_matches = all(identity.get(key) == value for key, value in expected.items())
    asset_bound = bool(re.fullmatch(r"[a-f0-9]{64}", asset_sha)) and _local_source_asset_matches(asset_path, asset_sha)
    uncertainties_valid = isinstance(uncertainties, list) and all(
        isinstance(item, str) and item.strip() for item in uncertainties)
    if verbatim is False:
        fidelity_recorded = uncertainties_valid and bool(uncertainties) and bool(notes)
    elif verbatim is True:
        fidelity_recorded = (evidence.get("concordance") == "exact"
            and evidence.get("method") in {"page_text_exact_v1", "reviewed_image_exact_v1"})
    else:
        fidelity_recorded = False
    valid = (metadata.get("source_type") == "exam" and bool(subject) and isinstance(year, int)
        and 1900 <= year <= 2200 and bool(number) and bool(citation)
        and evidence.get("status") == "TRACEABLE"
        and evidence.get("method") == "curated_source_trace_v1"
        and evidence.get("question_content_sha256") == question_content_sha256(question)
        and identity_matches and bool(source_locator) and asset_bound and fidelity_recorded)
    record = {"status": "PASS" if valid else "UNKNOWN",
        "traceability": "TRACEABLE" if valid else "UNRESOLVED",
        "authenticity": "NOT_INDEPENDENTLY_AUTHENTICATED",
        "verbatim_concordance": "EXACT" if verbatim is True and valid else "NOT_CLAIMED",
        "source_identity": expected, "source_archive_sha256": asset_sha if asset_bound else None,
        "source_asset_path": asset_path if asset_bound else None,
        "source_locator": source_locator or None,
        "uncertainties": uncertainties if uncertainties_valid else [],
        "reason": "traceable_curated_source_with_explicit_fidelity_boundary" if valid else "source_trace_or_uncertainty_record_incomplete"}
    return valid, record


def _local_source_asset_matches(relative_path: str, expected_sha256: str) -> bool:
    """Verify a hashed local intake asset; never follows an arbitrary path."""
    import re
    from pathlib import PurePosixPath, PureWindowsPath
    from hashlib import sha256
    if (not isinstance(relative_path, str) or not relative_path or "\\" in relative_path
            or PurePosixPath(relative_path).is_absolute() or PureWindowsPath(relative_path).drive
            or any(part in {"", ".", ".."} for part in relative_path.split("/"))):
        return False
    allowed = QUESTION_INTAKE_ROOT.resolve()
    candidate = (allowed / relative_path).resolve()
    if candidate == allowed or not candidate.is_relative_to(allowed) or not candidate.is_file():
        return False
    if not re.fullmatch(r"[a-f0-9]{64}", expected_sha256):
        return False
    digest = sha256()
    try:
        with candidate.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError:
        return False
    return digest.hexdigest() == expected_sha256


def _source_check(db: Session, question: Question, qualification_class: str,
                  source_evidence: dict[str, Any] | None) -> dict[str, Any]:
    if qualification_class == "development_original":
        generation = (question.grading_config or {}).get("generation", {})
        valid = (generation.get("mode") == "original" and not generation.get("parent_question_id")
                 and generation.get("authoring_mode") in {"codex_offline", "codex_development", "real_model"}
                 and question.source_status == "not_applicable")
        return {"status": "PASS" if valid else "FAIL", "reason": "explicit_development_original_lineage" if valid else "development_origin_missing"}
    if qualification_class == "exam_curated":
        valid, trace = _source_trace_matches(question, source_evidence)
        valid = (valid and question.question_provenance == "real_exam"
                 and question.source_status in {"traceable", "verified"})
        return {**trace, "status": "PASS" if valid else "UNKNOWN",
                "reason": "curated_source_trace_recorded_not_verbatim_claim" if valid else trace["reason"]}
    parent_id = (question.grading_config or {}).get("generation", {}).get("parent_question_id")
    parent = db.get(Question, UUID(str(parent_id))) if parent_id else None
    evidence = source_evidence if isinstance(source_evidence, dict) else {}
    parent_trace, parent_record = _source_trace_matches(parent, evidence.get("parent_source_evidence") if isinstance(evidence, dict) else None) if parent else (False, {})
    valid = bool(question.is_variant and parent and parent.question_provenance == "real_exam"
        and parent.bank_scope == "public" and not parent.generation_batch_id
        and parent.source_status in {"traceable", "verified"} and parent_trace
        and evidence.get("status") == "TRACEABLE"
        and evidence.get("method") == "exam_variant_lineage_v1"
        and evidence.get("parent_question_id") == str(parent.id)
        and evidence.get("parent_snapshot_sha256") == question_snapshot_sha256(parent)
        and evidence.get("question_content_sha256")
        == __import__("backend.services.question_attestation", fromlist=["question_content_sha256"]).question_content_sha256(question)
        and isinstance(evidence.get("transformation_summary"), str)
        and len(evidence["transformation_summary"].strip()) >= 20
        and isinstance(evidence.get("uncertainties"), list))
    return {"status": "PASS" if valid else "UNKNOWN", "traceability": "TRACEABLE" if valid else "UNRESOLVED",
        "authenticity": parent_record.get("authenticity", "NOT_INDEPENDENTLY_AUTHENTICATED"),
        "uncertainties": evidence.get("uncertainties", []) if isinstance(evidence, dict) else [],
        "reason": "variant_source_lineage_bound_with_transformation_record" if valid else "source_parent_and_variant_lineage_required"}


def _exam_subject_matches_node(exam_subject: Any, node_subject: Any) -> bool:
    """Allow a paper subject to map to the project's broader curriculum label.

    The knowledge tree uses ``考研数学`` as a shared domain label while source
    records identify a specific paper such as ``数学二``. The exact source-pack
    node code remains the required mapping proof; this alias only avoids
    rejecting that known paper/domain relationship as a subject mismatch.
    """
    source = canonical_subject(exam_subject)
    target = canonical_subject(node_subject)
    return source == target or (source == "math2" and target == "考研数学")


def assess_auto_qualification(db: Session, question: Question, node: KnowledgePoint,
                              *, source_evidence: dict[str, Any] | None = None,
                              all_questions: list[Question] | None = None) -> dict[str, Any]:
    qualification_class = infer_qualification_class(question)
    if qualification_class not in QUALIFICATION_CLASSES:
        return {"status": "QUARANTINED", "reason": "unsupported_or_personal_production_origin"}
    grading_config = question.grading_config if isinstance(question.grading_config, dict) else {}
    quality_holds = grading_config.get("quality_holds", [])
    if isinstance(quality_holds, list) and any(
            isinstance(hold, dict) and hold.get("status") == "OPEN" for hold in quality_holds):
        return {"status": "QUARANTINED", "reason": "open_quality_hold_requires_resolution",
                "open_quality_hold_ids": [hold.get("id") for hold in quality_holds
                    if isinstance(hold, dict) and hold.get("status") == "OPEN"]}
    source_evidence = source_evidence if isinstance(source_evidence, dict) else {}
    from backend.services.question_generation import current_generation_binding
    generation_bound = current_generation_binding(question, node)
    reference_topic_mapping = bool(
        qualification_class == "exam_curated" and node.is_reference_only
        and source_evidence.get("mapped_node_code") == node.code
        and source_evidence.get("question_content_sha256")
    )
    generated_reference_mapping = bool(
        qualification_class in {"development_original", "exam_variant"}
        and node.is_reference_only and generation_bound
        and question.kp_id == node.id
    )
    has_children = (db.scalar(select(KnowledgePoint.id).where(KnowledgePoint.parent_id == node.id).limit(1))
        is not None) if db is not None else bool(node.children)
    if (not question.is_active or getattr(question, "is_hidden", False)
            or not node.is_active or not node.is_assessable or has_children
            or (node.is_reference_only and not (reference_topic_mapping or generated_reference_mapping))
            or node.id != question.kp_id):
        return {"status": "QUARANTINED", "reason": "inactive_or_unassessable_mapping"}

    structure = validate_question_content(question)
    structure_issues = [issue for issue in structure.detected_issues if issue != "human_content_review_required"]
    structure_stage = {"status": "PASS" if structure.completeness == "complete" and not structure_issues else "FAIL",
                       "issues": structure_issues, "option_content_rule_version": "distinct-choice-content-v1"}
    independent = verify_problem(question)
    codex_review = current_codex_independent_review(question, node)
    solver_independent_ok = (independent.get("status") == "PASS"
        and independent.get("adapter") in ALLOWED_SOLVERS
        and independent.get("derived_answer") is not None)
    if not solver_independent_ok and codex_review is not None:
        independent = {"status": "PASS", "adapter": "codex_independent_review_v1",
            "reason": "two_method_content_bound_review_receipt",
            "derived_answer": codex_review.get("derived_answer"),
            "proof": {"methods": codex_review.get("method_evidence"),
                "question_content_sha256": codex_review.get("question_content_sha256"),
                "answer_sha256": codex_review.get("answer_sha256")}}
    independent_ok = (solver_independent_ok or codex_review is not None) and independent.get("derived_answer") is not None
    independent_stage = {"status": "PASS" if independent_ok else "UNKNOWN",
                         "reason": independent.get("reason"),
                         "adapter": independent.get("adapter"), "proof": independent.get("proof"),
                         "review_version": codex_review.get("version") if codex_review else None,
                         "human_verified": False}
    source_stage = _source_check(db, question, qualification_class, source_evidence)
    generation = (question.grading_config or {}).get("generation", {})
    difficulty_reason = generation.get("difficulty_reason") if isinstance(generation, dict) else None
    difficulty_reason_version = generation.get("difficulty_reason_version") if isinstance(generation, dict) else None
    difficulty_reason_required = (isinstance(generation, dict) and generation.get("version") in {
        "codex-public-original-v2", "codex-public-variant-v2"})
    if difficulty_reason_required or difficulty_reason is not None:
        from backend.services.question_generation import DifficultyReason
        try:
            reason = DifficultyReason.model_validate(difficulty_reason).model_dump()
            reason_ok = difficulty_reason_version == "exam-difficulty-reason-v1"
        except Exception:
            reason, reason_ok = None, False
        difficulty_stage = {"status": "PASS" if reason_ok else "FAIL",
            "reason": "new_public_generation_has_specific_difficulty_rationale" if reason_ok
                else "new_public_generation_requires_four_specific_difficulty_fields",
            "version": difficulty_reason_version, "fields": sorted(reason) if reason_ok else []}
    else:
        difficulty_stage = {"status": "PASS", "reason": "legacy_content_no_new_generation_claim",
                            "legacy": True}
    prior_proof = generation.get("independent_verification") if isinstance(generation, dict) else None
    answer_stage = {"status": "PASS" if independent_ok and (
                    qualification_class == "exam_curated" or isinstance(prior_proof, dict)
                    and prior_proof.get("status") == "PASS"
                    and prior_proof.get("derived_answer") == independent.get("derived_answer")
                    or codex_review is not None and _review_answer_matches(question, codex_review.get("derived_answer"))) else "UNKNOWN",
                    "reason": "content_bound_independent_review_matches_answer" if codex_review is not None else
                    "fresh_bounded_solver_verified_stored_answer" if qualification_class == "exam_curated"
                    else "fresh_solver_matches_saved_production_proof"}

    explanation_stage = _explanation_check(question, independent, codex_review)
    from backend.services.question_attestation import has_current_source_attestation
    source_identity = source_stage.get("source_identity") if isinstance(source_stage.get("source_identity"), dict) else {}
    source_subject_ok = (qualification_class != "exam_curated"
        or _exam_subject_matches_node(source_identity.get("subject"), node.subject))
    mapping_code = str(source_evidence.get("mapped_node_code") or "")
    mapping_ok = bool(node.is_active and node.is_assessable and not has_children
        and (not node.is_reference_only or reference_topic_mapping or generated_reference_mapping)
        and question.skill_tags and all(isinstance(tag, str) and tag.strip() for tag in question.skill_tags)
        and source_subject_ok
        and (qualification_class != "exam_curated" or mapping_code == node.code)
        and ((qualification_class == "development_original" and generation_bound)
             or (qualification_class == "exam_variant" and generation_bound)
             or (qualification_class == "exam_curated" and source_stage.get("status") == "PASS")))
    mapping_stage = {"status": "PASS" if mapping_ok else "UNKNOWN",
        "reason": ("version_bound_source_pack_node_and_leaf_mapping" if qualification_class == "exam_curated"
            else "version_bound_generated_node_mapping"),
        "node_id": str(node.id), "node_code": node.code, "node_subject": node.subject,
        "node_assessable": bool(node.is_assessable), "node_is_leaf": not has_children,
        "source_pack_node_code": mapping_code or None,
        "reference_topic_mapping": reference_topic_mapping,
        "generated_node_mapping": generated_reference_mapping}

    duplicate_source = list(all_questions or [])
    # Qualification is a public-bank identity decision, so archived/hidden
    # rows remain part of the identity universe.  Visibility controls serving,
    # not whether an equivalent public problem already exists.
    duplicate_source = [q for q in duplicate_source if q.id != question.id
        and q.bank_scope == "public" and not q.generation_batch_id]
    from backend.services.question_quality import ambiguity
    from backend.services.question_identity import duplicate_findings,verified_identity
    findings=duplicate_findings(question,duplicate_source)
    matched={r['question_id'] for r in findings['matches']}
    peers=[question,*[q for q in duplicate_source if str(q.id) in matched]]
    def priority(q):
        return (0 if current_auto_review(q) is not None else 1,
            q.created_at.timestamp() if q.created_at else float('inf'),str(q.id))
    canonical=min(peers,key=priority)
    source_conflict=any(r['reasons']==['same_exam_identity'] and verified_identity(question)!=verified_identity(next(q for q in peers if str(q.id)==r['question_id']))
        for r in findings['matches'])
    clear=not source_conflict and canonical.id==question.id and not findings['uncertain_similar']
    duplicate_stage={'status':'PASS' if clear else 'UNKNOWN','reason':'canonical_independent_problem' if clear else
        'source_identity_content_conflict' if source_conflict else 'duplicate_canonical_exists' if canonical.id!=question.id else 'similarity_unresolved',
        'algorithm':'bank-question-identity-v1','exact':sorted(matched),'near':findings['uncertain_similar'],
        'canonical_question_id':str(canonical.id),'semantic_dedup_executed':True}
    unique = ambiguity(question, independent)
    if unique.get("status") not in {"PASS", "NOT_APPLICABLE"} and codex_review is not None:
        truth_table = codex_review.get("option_truth_table")
        if (question.question_type == "single_choice" and isinstance(truth_table, dict)
                and set(truth_table) == set(question.options or {})
                and sum(value is True for value in truth_table.values()) == 1
                and truth_table.get(str(question.correct_answer).strip().upper()) is True):
            unique = {"status": "PASS", "reason": "codex_independent_option_by_option_uniqueness_review",
                      "option_truth_table": truth_table, "human_verified": False}
    unique_stage = {"status": "PASS" if unique.get("status") in {"PASS", "NOT_APPLICABLE"} else unique.get("status"),
                    "reason": unique.get("reason")}

    config = question.grading_config if isinstance(question.grading_config, dict) else {}
    method = config.get("method") or config.get("generated_practice_method")
    if qualification_class == "exam_curated" and not method:
        if question.question_type == "single_choice":
            method = "single_choice"
        elif question.question_type in {"fill_blank", "calculation"}:
            from backend.services.answer_grading import available_grading_method
            for candidate_method in ("numeric_final", "logarithm_final", "constant_final"):
                if available_grading_method(question_type=question.question_type,
                        config={"verified": True, "method": candidate_method},
                        expected=question.correct_answer, options=question.options):
                    method = candidate_method
                    break
    if method and method.startswith("ai_generated_"):
        method = method.removeprefix("ai_generated_")
    previous_config = question.grading_config
    question.grading_config = {**config, "verified": bool(method), "method": method}
    try:
        grading = _grading_tests(question)
    finally:
        question.grading_config = previous_config
    # No strict evidence path exists for a proof/process-only answer.
    if not method:
        grading = {"status": "UNKNOWN", "reason": "no_bounded_objective_grader"}

    stages = {"structure": structure_stage, "source": source_stage,
              "independent_answer": independent_stage, "answer_consistency": answer_stage,
              "explanation": explanation_stage, "uniqueness": unique_stage,
              "mapping": mapping_stage, "duplicates": duplicate_stage, "grading": grading,
              "difficulty": difficulty_stage}
    status = "AUTO_VERIFIED" if all(v.get("status") == "PASS" for v in stages.values()) else (
        "REJECTED" if any(v.get("status") == "FAIL" for v in stages.values()) else "NEEDS_REVIEW")
    snapshot = {"version": AUTO_REVIEW_VERSION, "qualification_class": qualification_class,
                "question_snapshot": question_snapshot_payload(question), "stages": stages,
                "independent_verification": independent, "source_evidence": source_evidence,
                "duplicate_scope_count": len(duplicate_source), "verifier_version": VERIFIER_VERSION,
                "limits": ["bounded deterministic solver or explicit hash-bound Codex independent review",
                            "Codex review is not a theorem prover or human signature", "no general proof checker",
                            "no semantic duplicate model", "exam source traceability does not prove verbatim concordance or licensing"]}
    return {"status": status, "qualification_class": qualification_class,
            "question_snapshot_sha256": question_snapshot_sha256(question),
            "answer_sha256": answer_version_sha256(question), "audit_snapshot": snapshot,
            "audit_sha256": digest(snapshot), "stages": stages, "independent_verification": independent}


def _previous_state(question: Question) -> dict[str, Any]:
    return {"content_trust": question.content_trust, "answer_provenance": question.answer_provenance,
            "answer_reliability": question.answer_reliability,
            "grading_mode": question.grading_mode, "grading_config": deepcopy(question.grading_config)}


def qualify_public_question(db: Session, *, question_id: UUID, node_id: UUID,
                            expected_snapshot_sha256: str, idempotency_key: str,
                            source_evidence: dict[str, Any] | None = None,
                            now: datetime | None = None) -> tuple[QuestionAutoReviewEvent | None, dict[str, Any]]:
    """Append qualification after a live locked recheck; caller controls commit."""
    from backend.services.question_identity import PUBLIC_BANK_LOCK
    from sqlalchemy import text
    db.execute(text('SELECT pg_advisory_xact_lock(:key)'),{'key':PUBLIC_BANK_LOCK})
    question = db.scalar(select(Question).where(Question.id == question_id).with_for_update()
                         .execution_options(populate_existing=True))
    node = db.get(KnowledgePoint, node_id)
    if question is None or node is None or question.kp_id != node.id:
        raise ValueError("question_or_mapping_not_found")
    existing = db.scalar(select(QuestionAutoReviewEvent).where(
        QuestionAutoReviewEvent.idempotency_key == idempotency_key))
    if existing:
        if (existing.question_id != question.id
                or (existing.audit_snapshot or {}).get("prequalification_snapshot_sha256") != expected_snapshot_sha256):
            raise ValueError("auto_review_idempotency_conflict")
        if current_auto_review(question) and question.auto_review_event_id == existing.id:
            return existing, {"status": "NOOP", "event_id": str(existing.id)}
        raise ValueError("auto_review_event_exists_but_is_not_current")
    if question_snapshot_sha256(question) != expected_snapshot_sha256:
        raise ValueError("question_snapshot_changed")
    # Include inactive and hidden public questions in the locked live recheck.
    # Otherwise an archived duplicate could be reintroduced as a second formal
    # item simply by submitting it through a new pack or generation batch.
    rows = list(db.scalars(select(Question).where(Question.bank_scope == "public",
        Question.generation_batch_id.is_(None))))
    assessment = assess_auto_qualification(db, question, node,
        source_evidence=source_evidence, all_questions=rows)
    if assessment.get("status") != "AUTO_VERIFIED":
        return None, assessment
    if question.bank_scope != "public" or question.generation_batch_id:
        raise ValueError("personal_question_cannot_receive_public_auto_qualification")
    if question.answer_verification_event_id is not None:
        raise ValueError("human_answer_verification_uses_separate_current_pointer")

    prior = _previous_state(question)
    assessment["audit_snapshot"]["prequalification_snapshot_sha256"] = expected_snapshot_sha256
    question.content_trust = "auto_verified"
    question.answer_provenance = "auto_verified"
    question.answer_reliability = "verified"
    question.grading_mode = "auto"
    question.grading_config = {**(question.grading_config or {}), "verified": True,
                               "method": assessment["stages"]["grading"]["method"]}
    # The grading config is part of the full bound snapshot; re-evaluate after
    # setting the formal comparator and before appending the immutable event.
    assessment["audit_snapshot"]["question_snapshot"] = question_snapshot_payload(question)
    assessment["question_snapshot_sha256"] = question_snapshot_sha256(question)
    assessment["answer_sha256"] = answer_version_sha256(question)
    assessment["audit_snapshot"]["bound_question_snapshot_sha256"] = assessment["question_snapshot_sha256"]
    assessment["audit_sha256"] = digest(assessment["audit_snapshot"])
    event = QuestionAutoReviewEvent(id=uuid4(), question_id=question.id, event_type="qualified",
        qualification_class=assessment["qualification_class"], review_version=AUTO_REVIEW_VERSION,
        question_snapshot_sha256=assessment["question_snapshot_sha256"],
        answer_sha256=assessment["answer_sha256"], audit_sha256=assessment["audit_sha256"],
        audit_snapshot=assessment["audit_snapshot"], idempotency_key=idempotency_key,
        previous_state=prior, created_at=(now or datetime.now(timezone.utc)).astimezone(timezone.utc))
    db.add(event)
    db.flush()
    question.auto_review_event_id = event.id
    question.current_auto_review = event
    db.flush()
    return event, {**assessment, "status": "AUTO_VERIFIED", "event_id": str(event.id),
                   "question_snapshot_sha256": event.question_snapshot_sha256,
                   "prequalification_snapshot_sha256": expected_snapshot_sha256,
                   "audit_sha256": event.audit_sha256, "machine_auditor": AUTO_AUDITOR,
                   "human_verified": False, "learner_graduated": False}


def revoke_auto_qualification(db: Session, *, question_id: UUID, expected_event_id: UUID,
                              expected_snapshot_sha256: str, idempotency_key: str,
                              now: datetime | None = None) -> QuestionAutoReviewEvent:
    question = db.scalar(select(Question).where(Question.id == question_id).with_for_update()
                         .execution_options(populate_existing=True))
    if question is None:
        raise ValueError("question_not_found")
    if question_snapshot_sha256(question) != expected_snapshot_sha256:
        raise ValueError("question_snapshot_changed")
    original = db.get(QuestionAutoReviewEvent, expected_event_id)
    if (original is None or original.question_id != question.id or original.event_type != "qualified"
            or question.auto_review_event_id != original.id):
        raise ValueError("auto_review_not_current")
    state = original.previous_state or {}
    event = QuestionAutoReviewEvent(id=uuid4(), question_id=question.id, event_type="revoked",
        qualification_class=original.qualification_class, review_version=AUTO_REVIEW_VERSION,
        question_snapshot_sha256=question_snapshot_sha256(question),
        answer_sha256=answer_version_sha256(question), audit_sha256=original.audit_sha256,
        audit_snapshot={"revokes_event_id": str(original.id), "reason": "qualification_withdrawn"},
        idempotency_key=idempotency_key, related_event_id=original.id, previous_state=state,
        created_at=(now or datetime.now(timezone.utc)).astimezone(timezone.utc))
    db.add(event)
    db.flush()
    question.auto_review_event_id = None
    question.current_auto_review = None
    question.content_trust = state.get("content_trust", "needs_review")
    question.answer_provenance = state.get("answer_provenance", "unknown")
    question.answer_reliability = state.get("answer_reliability", "unknown")
    question.grading_mode = state.get("grading_mode", "self_assessed")
    question.grading_config = state.get("grading_config")
    db.flush()
    return event
