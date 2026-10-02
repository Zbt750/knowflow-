"""Bounded, zero-model context for explicit knowledge follow-ups only."""
from dataclasses import dataclass
import re
from collections.abc import Sequence


QUERY_CONTEXT_VERSION = "bounded-previous-user-v1"
_REFERENCE = re.compile(
    r"^(?:刚才那个|刚才的|上面那个|上面的|这个反例|那个反例|这一步|那一步|"
    r"这个结论|那个结论|这是什么意思|为什么这样|再解释一下|换种讲法)"
)
_RESET = re.compile(r"不谈|别谈|换个|换一个|换一下|另外|接下来|新问题|重新开始|先不|转到")
_DOCUMENT = re.compile(r"文件|资料|讲义|笔记|文档|章节|阶段|《|\.(?:md|txt|pdf|docx)(?![A-Za-z0-9_])", re.I)


@dataclass(frozen=True)
class RetrievalQueryContext:
    query: str
    previous_user_turns: int = 0

    def diagnostic(self):
        # Neither raw question nor private historical content is stored here.
        return {"version": QUERY_CONTEXT_VERSION,
                "source": "previous_user_question" if self.previous_user_turns else "current_only",
                "previous_user_turns": self.previous_user_turns}


def is_knowledge_followup(question: str) -> bool:
    text = question.strip()
    return (len(text) <= 180 and bool(_REFERENCE.match(text))
            and not _RESET.search(text) and not _DOCUMENT.search(text))


def contextualize_retrieval_query(question: str, previous_questions: Sequence[str]) -> RetrievalQueryContext:
    """Use only the immediately previous user's concrete question, not assistant claims.

    Never scan past a topic switch, ambiguous follow-up, file reference or oversized
    turn to revive older context. This is deliberately not universal query rewriting.
    """
    unchanged = RetrievalQueryContext(question)
    if not is_knowledge_followup(question) or not previous_questions:
        return unchanged
    previous = previous_questions[0]
    if not isinstance(previous, str):
        return unchanged
    previous = previous.strip()
    if (not previous or len(previous) > 240 or _DOCUMENT.search(previous)
            or _REFERENCE.match(previous) or _RESET.search(previous)
            or previous == question.strip()
            or re.fullmatch(r"你好|您好|hello|hi|谢谢|好的|继续|不懂|为什么", previous, re.I)):
        return unchanged
    return RetrievalQueryContext(f"{previous}\n{question}", previous_user_turns=1)
