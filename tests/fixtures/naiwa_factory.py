"""Small composable factories. Caller supplies a per-test namespace and transaction.

No commits, deletes, direct SQL, certification or random model calls here.
These builders are not an alternative to formal verification/generation services.
"""
from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID, uuid5

NOW = datetime(2040, 1, 2, tzinfo=timezone.utc)


@dataclass(frozen=True)
class TestActor:
    """Synthetic installation identity, NOT an ORM user/account or permission."""
    id: UUID
    namespace: UUID


def create_test_user(namespace: UUID, label="actor"):
    return TestActor(uuid5(namespace, label), namespace)


class NaiwaFactory:
    def __init__(self, session, namespace: UUID, *, now=NOW):
        self.session, self.namespace, self.now = session, namespace, now

    def identity(self, label):
        return uuid5(self.namespace, label)

    def add(self, obj):
        self.session.add(obj)
        self.session.flush()  # Original ORM hook creates immutable QuestionVersion.
        return obj

    def create_test_knowledge_tree(self):
        from backend.models.learning import KnowledgePoint
        root = self.add(KnowledgePoint(id=self.identity("root"), code=f"r13.{self.namespace}.root",
            name="合成数学", subject="math2", is_assessable=False, is_active=True))
        leaves = []
        for index, name in enumerate(("洛必达法则", "隐函数求导")):
            leaves.append(self.add(KnowledgePoint(id=self.identity(f"kp.{index}"),
                code=f"r13.{self.namespace}.kp.{index}", name=name, subject="math2",
                parent_id=root.id, ordinal=index, is_assessable=True, is_active=True)))
        return root, leaves

    def create_test_question(self, kp, label="question", *, bank_scope="public", **overrides):
        from backend.models.learning import Question
        protected = {"id", "kp_id", "current_version_id", "current_version", "answer_verification_event_id",
                     "content_trust", "answer_reliability", "answer_reviewed_by", "source_attestation_key"}
        if protected.intersection(overrides):
            raise ValueError("Use domain review/version services; factory cannot forge trust or pointers")
        values = dict(id=self.identity(label), kp_id=kp.id, question_type="single_choice",
            grading_mode="objective", stem=f"合成题[{label}]：计算1+1。", options=["1", "2", "3", "4"],
            correct_answer="B", explanation="按整数加法，1+1=2。", bank_scope=bank_scope,
            question_role="basic", difficulty="basic", estimated_minutes=5, is_active=True,
            question_provenance="developer_original", content_trust="unreviewed",
            answer_reliability="unknown", created_at=self.now, updated_at=self.now)
        values.update(overrides)
        return self.add(Question(**values))

    def create_test_personal_question(self, kp, label="personal", **overrides):
        overrides.setdefault("question_provenance", "ai_generated")
        return self.create_test_question(kp, label, bank_scope="personal", **overrides)

    def create_test_daily_plan(self, label="plan", *, study_date=None, status="draft"):
        from backend.models.learning import DailyPlan
        # Date is a global unique business key. Concurrent same-date plans need
        # separate DBs or serialization; a user namespace does NOT isolate it.
        return self.add(DailyPlan(id=self.identity(label), study_date=study_date or self.now.date().isoformat(),
            status=status, created_at=self.now, updated_at=self.now))

    def create_test_practice_item(self, plan, question, *, ordinal=0, label="item"):
        from backend.models.learning import PracticeItem
        if question.current_version_id is None:
            raise ValueError("Flush question with original version hook before binding item")
        return self.add(PracticeItem(id=self.identity(label), plan_id=plan.id, question_id=question.id,
            question_version_id=question.current_version_id, kp_id=question.kp_id, ordinal=ordinal,
            created_at=self.now, updated_at=self.now))

    def create_test_attempt(self, item, label="attempt", *, objective_result="unknown"):
        from backend.models.learning import QuestionAttempt
        return self.add(QuestionAttempt(id=self.identity(label), practice_item_id=item.id,
            question_id=item.question_id, question_version_id=item.question_version_id, kp_id=item.kp_id,
            raw_answer="B", objective_result=objective_result, submitted_at=self.now,
            idempotency_key=str(self.identity(label+".key")), result_state="unseen", reason_code="synthetic_fixture"))

    def create_test_chat_session(self, label="session", *, purpose="qa"):
        from backend.models.chat import ChatSession
        return self.add(ChatSession(id=self.identity(label), title="R13合成会话", mode="builtin", purpose=purpose,
            study_date=self.now.date().isoformat() if purpose=="study" else None,
            created_at=self.now, updated_at=self.now))

    def create_test_message(self, chat, label="message", *, metadata=None):
        from backend.models.chat import ChatMessage
        return self.add(ChatMessage(id=self.identity(label), session_id=chat.id, role="assistant",
            content="合成业务上下文", status="completed", metadata_=metadata or {},
            created_at=self.now, updated_at=self.now))
