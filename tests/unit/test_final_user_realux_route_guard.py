"""Regression tests for the offline/paid-run route guard contract."""
import json
from pathlib import Path
import unittest

from scripts.final_user_realux_server import PLAN, evaluation_stream_allowed, evaluation_stream_rejection_status


class EvaluationStreamGuardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cases = json.loads(Path(PLAN).read_text(encoding="utf-8"))["cases_in_priority_order"]
        cls.cases = {row["id"]: row for row in cases}
        cls.allowed = set(cls.cases)

    def test_ordinary_chat_case_allows_assistant_stream(self):
        self.assertEqual(self.cases["QA-04"]["surface"], "chat")
        path = "/api/chat/sessions/00000000-0000-0000-0000-000000000001/assistant:stream"
        self.assertTrue(evaluation_stream_allowed("QA-04", path, self.cases))

    def test_chat_case_still_rejects_materials_stream(self):
        path = "/api/chat/sessions/00000000-0000-0000-0000-000000000001/answers:stream"
        self.assertFalse(evaluation_stream_allowed("QA-04", path, self.cases))
        self.assertEqual(evaluation_stream_rejection_status("QA-04", path, self.cases, self.allowed), 409)

    def test_materials_case_uses_answers_stream_only(self):
        answers = "/api/chat/sessions/00000000-0000-0000-0000-000000000001/answers:stream"
        assistant = "/api/chat/sessions/00000000-0000-0000-0000-000000000001/assistant:stream"
        self.assertTrue(evaluation_stream_allowed("QA-01", answers, self.cases))
        self.assertFalse(evaluation_stream_allowed("QA-01", assistant, self.cases))

    def test_agent_case_uses_assistant_stream_only(self):
        assistant = "/api/chat/sessions/00000000-0000-0000-0000-000000000001/assistant:stream"
        answers = "/api/chat/sessions/00000000-0000-0000-0000-000000000001/answers:stream"
        self.assertTrue(evaluation_stream_allowed("Agent-01", assistant, self.cases))
        self.assertFalse(evaluation_stream_allowed("Agent-01", answers, self.cases))

    def test_unknown_case_or_non_stream_route_remains_rejected(self):
        assistant = "/api/chat/sessions/00000000-0000-0000-0000-000000000001/assistant:stream"
        self.assertFalse(evaluation_stream_allowed("QA-404", assistant, self.cases))
        self.assertFalse(evaluation_stream_allowed("QA-04", "/api/chat/sessions", self.cases))
        self.assertEqual(evaluation_stream_rejection_status("QA-404", assistant, self.cases, self.allowed), 409)


if __name__ == "__main__":
    unittest.main()
