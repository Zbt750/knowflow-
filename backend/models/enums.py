from __future__ import annotations

from enum import StrEnum


class MasteryState(StrEnum):
    """可考核叶子节点的当前掌握状态投影。"""

    UNSEEN = "unseen"
    CONSOLIDATING = "consolidating"
    STUCK = "stuck"
    MASTERED = "mastered"


class SelfGrade(StrEnum):
    """用户对一道题的自评。skip 不写练习记录。"""

    MASTERED = "mastered"
    PARTIAL = "partial"
    NOT_MASTERED = "not_mastered"
    SKIP = "skip"


class NodeSelfGrade(StrEnum):
    """叶子节点整体自评；父节点禁止使用。"""

    MASTERED = "mastered"
    PARTIAL = "partial"
    NOT_MASTERED = "not_mastered"


class ObjectiveResult(StrEnum):
    """可选机器判分；只是复盘参考，绝不代替 self_grade。"""

    RIGHT = "right"
    WRONG = "wrong"
    UNKNOWN = "unknown"


class PlanStatus(StrEnum):
    """今日练习卷状态：生成后 active，全部完成变 completed。"""

    DRAFT = "draft"
    ACTIVE = "active"
    COMPLETED = "completed"


class MaterialStatus(StrEnum):
    PENDING = "pending"
    INDEXING = "indexing"
    READY = "ready"
    FAILED = "failed"
    DELETING = "deleting"
    DELETED = "deleted"


class JobType(StrEnum):
    INGEST = "ingest"
    REINDEX = "reindex"
    DELETE = "delete"


class JobStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    RETRY = "retry"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class ChatRole(StrEnum):
    USER = "user"
    ASSISTANT = "assistant"


class ChatMessageStatus(StrEnum):
    PENDING = "pending"
    STREAMING = "streaming"
    COMPLETE = "complete"
    FAILED = "failed"
    CANCELLED = "cancelled"