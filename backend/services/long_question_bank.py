"""AI 大题练习库：内容包 → 现有 Question / QuestionVersion / 生成批次。

边界（与项目既有规则一致）：
- 只写 personal 练习库，不授予公共正式题资格，不产生毕业证据。
- 绑定 personal-general-generation-v1，使现有 question_eligibility 能把它们
  作为“个人 AI 练习（参考答案）”放行；正式题集与毕业算法完全不变。
- 幂等：题目 ID 由 batch_key + slug 稳定派生；重复执行不会重复入库。
- 题库版本由 Question 的 before_flush 钩子自动创建，本模块不手写 QuestionVersion。
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from uuid import NAMESPACE_URL, UUID, uuid5

from backend.models.learning import Question

PACK_VERSION = "long-question-pack-v1"
GENERATION_VERSION = "personal-general-generation-v1"
PROMPT_VERSION = "personal-general-authoring-v1"
REVIEW_STATUS = "STRUCTURE_CHECKED_REFERENCE_ONLY"
QUESTION_TYPES = {"single_choice", "fill_blank", "calculation", "proof", "subjective"}


@dataclass(frozen=True)
class PackItem:
    slug: str
    kp_code: str
    title: str
    question_type: str
    difficulty: str
    estimated_minutes: int
    role: str
    skill_tags: list[str]
    objective: str
    stem: str
    answer: str
    final_value: str
    solution_steps: list[str]
    key_points: list[str]
    common_errors: list[str]
    scope: str
    verification_steps: list[dict[str, str]]
    verification: dict
    review: dict
    raw: dict

    @classmethod
    def from_dict(cls, item: dict) -> "PackItem":
        required = ("slug", "kp_code", "title", "question_type", "difficulty",
                    "estimated_minutes", "role", "skill_tags", "objective", "stem",
                    "answer", "final_value", "solution_steps", "key_points",
                    "common_errors", "scope", "verification_steps", "verification", "review")
        missing = [key for key in required if key not in item]
        if missing:
            raise ValueError(f"pack_item_missing:{','.join(missing)}")
        if item["question_type"] not in QUESTION_TYPES:
            raise ValueError(f"pack_item_type_unsupported:{item['question_type']}")
        if len(item["solution_steps"]) < 3:
            raise ValueError("pack_item_solution_too_short")
        return cls(
            slug=str(item["slug"]),
            kp_code=str(item["kp_code"]),
            title=str(item["title"]),
            question_type=item["question_type"],
            difficulty=item["difficulty"],
            estimated_minutes=int(item["estimated_minutes"]),
            role=item.get("role", "basic"),
            skill_tags=list(item["skill_tags"]),
            objective=str(item["objective"]),
            stem=str(item["stem"]),
            answer=str(item["answer"]),
            final_value=str(item["final_value"]),
            solution_steps=list(item["solution_steps"]),
            key_points=list(item["key_points"]),
            common_errors=list(item["common_errors"]),
            scope=str(item["scope"]),
            verification_steps=list(item["verification_steps"]),
            verification=dict(item["verification"]),
            review=dict(item["review"]),
            raw=item,
        )


@dataclass(frozen=True)
class Pack:
    batch_key: str
    pack_version: str
    path: str
    sha256: str
    items: list[PackItem]

    @classmethod
    def load(cls, path: Path) -> "Pack":
        raw_bytes = path.read_bytes()
        data = json.loads(raw_bytes.decode("utf-8"))
        if data.get("pack_version") != PACK_VERSION:
            raise ValueError(f"pack_version_unsupported:{data.get('pack_version')}")
        batch_key = str(data.get("batch_key") or "").strip()
        if not batch_key:
            raise ValueError("pack_batch_key_missing")
        items = [PackItem.from_dict(item) for item in data.get("items", [])]
        if not items:
            raise ValueError("pack_items_empty")
        return cls(batch_key=batch_key, pack_version=data["pack_version"], path=str(path),
                   sha256=hashlib.sha256(raw_bytes).hexdigest(), items=items)


def request_key(batch_key: str, item: PackItem) -> str:
    return f"{batch_key}:{item.slug}"


def stable_question_id(batch_key: str, item: PackItem) -> UUID:
    """同一批次同一 slug 永远生成同一个 UUID，导入可安全重跑。"""
    return uuid5(NAMESPACE_URL, f"long-question-bank:{request_key(batch_key, item)}")


def build_explanation(item: PackItem) -> str:
    steps = "\n".join(f"{index}. {step}" for index, step in enumerate(item.solution_steps, 1))
    key_points = "\n".join(f"- {point}" for point in item.key_points)
    errors = "\n".join(f"- {error}" for error in item.common_errors)
    verification = item.verification
    return (
        f"## 参考答案\n{item.answer}\n\n"
        f"## 分步解析\n{steps}\n\n"
        f"## 关键定理 / 公式 / 原理\n{key_points}\n\n"
        f"## 常见错误\n{errors}\n\n"
        f"## 适用范围与前提\n{item.scope}\n\n"
        f"## 复核记录\n"
        f"- 复核方法：{verification.get('method', 'unknown')}\n"
        f"- 复核结果：{verification.get('result', 'unknown')}\n"
        f"- 说明：{verification.get('detail', '')}\n"
        f"- 本题为 AI 生成练习的参考答案，不能替代正式真题复核；证明题仍需人工复核。"
    )


def build_question(item: PackItem, node, batch_id: UUID, batch_key: str) -> Question:
    """构造 Question；版本快照由现有 before_flush 钩子自动创建。"""
    question_id = stable_question_id(batch_key, item)
    generation_record = {
        "version": GENERATION_VERSION,
        "prompt_version": PROMPT_VERSION,
        "node_code": node.code,
        "generation_mode": "ai_generated",
        "identity_label": "个人 AI 练习",
        "request_id": request_key(batch_key, item),
        "model": "claude-agent-offline",
        "model_calls": 0,
        "authoring_mode": "claude_offline_authoring",
        "parent_question_id": None,
        "parent_input_sha256": None,
        "independent_verification": {
            "method": item.verification.get("method"),
            "status": item.verification.get("result"),
            "detail": item.verification.get("detail"),
        },
        # 既有规则：个人 AI 题永远是参考题，不能宣称答案已被独立证明。
        "review_status": REVIEW_STATUS,
        "answer_independently_verified": False,
        "original_label": item.raw.get("identity_label", "原创题"),
        "explanation_steps": item.verification_steps,
        "final_value": item.final_value,
        "raw_response_sha256": None,
        "normalized_response_sha256": None,
        "long_question": {
            "title": item.title,
            "objective": item.objective,
            "key_points": item.key_points,
            "common_errors": item.common_errors,
            "scope": item.scope,
            "review": item.review,
            "pack_version": PACK_VERSION,
            "source": "ai_generated_original",
            # 与既有 Codex 原创题共用 provenance 字段；UI 资格标签仍由现有规则决定。
            "identity_label": item.raw.get("identity_label", "原创题"),
        },
    }
    question = Question(
        id=question_id,
        kp_id=node.id,
        question_type=item.question_type,
        grading_mode="self_assessed",
        grading_config={"verified": False, "method": None, "generation": generation_record},
        stem=item.stem,
        options=None,
        correct_answer=item.answer,
        explanation=build_explanation(item),
        question_role=item.role,
        skill_tags=list(item.skill_tags),
        estimated_minutes=item.estimated_minutes,
        is_variant=False,
        variant_group=None,
        difficulty=item.difficulty,
        is_active=True,
        is_hidden=False,
        bank_scope="personal",
        generation_batch_id=batch_id,
        question_provenance="ai_generated_practice",
        content_trust="unreviewed",
        source_status="not_applicable",
        answer_provenance="ai_generated",
        answer_reliability="model_generated",
        content_reviewed_by=None,
        content_reviewed_at=None,
        answer_reviewed_by=None,
        answer_reviewed_at=None,
    )
    # 便于审计/查询的顶层镜像；不参与生成哈希（哈希只看 generation 记录）。
    question.grading_config["long_question"] = generation_record["long_question"]
    return question


def finalize_generation_hash(question: Question) -> str:
    """在题目字段全部就位后写入内容绑定哈希；导入前后各校验一次。"""
    from backend.services.question_generation import generation_hash
    record = question.grading_config["generation"]
    record["verified_content_hash"] = generation_hash(question)
    return record["verified_content_hash"]


def binding_is_current(question: Question, node) -> bool:
    from backend.services.personal_question_general import current_general_binding
    return current_general_binding(question, node)


def batch_request_payload(pack: Pack) -> dict:
    return {
        "pack_version": pack.pack_version,
        "pack_sha256": pack.sha256,
        "authoring_mode": "claude_offline_authoring",
        "model_calls": 0,
        "items": [{"slug": item.slug, "kp_code": item.kp_code, "title": item.title}
                  for item in pack.items],
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
    }


def summarize_items(items: list[PackItem]) -> dict:
    by_kp: dict[str, int] = {}
    for item in items:
        by_kp[item.kp_code] = by_kp.get(item.kp_code, 0) + 1
    return {"items": len(items), "kps": len(by_kp), "per_kp": by_kp}
