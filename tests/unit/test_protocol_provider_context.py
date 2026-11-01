"""The offline protocol double consumes the real lossless record format."""
import json

from backend.services.learning_task_context import pack_records
from scripts.run_learning_agent_eval import ProtocolProvider


def test_protocol_double_accepts_packed_question_records():
    provider = ProtocolProvider({'query': 'fixture', 'budget': 20})
    provider.turn = 2
    questions = [{'question_id': f'fixture-{i}', 'in_today_plan': False,
                  'minutes': 5, 'question_type': 'single_choice', 'difficulty': 'basic'}
                 for i in range(5)]
    packed = pack_records({'questions': questions})
    assert isinstance(packed['questions'], dict), 'fixture must exercise the actual column format'
    result = provider.tool_turn([{'role': 'tool', 'content': json.dumps(packed)}], [], timeout=1)
    call = result['message']['tool_calls'][0]['function']
    assert call['name'] == 'validate_plan'
    assert json.loads(call['arguments'])['question_ids'] == ['fixture-0']


def test_evidence_planner_accepts_packed_question_records():
    from scripts.run_agent_evidence_journey import EvidencePlanner
    provider = EvidencePlanner()
    provider.turn, provider.budget = 3, 20
    provider.state = {'recent_attempts': [], 'pending_review_question_ids': []}
    questions = [{'question_id': f'fixture-{i}', 'in_today_plan': False, 'minutes': 5}
                 for i in range(5)]
    packed = pack_records({'questions': questions})
    assert isinstance(packed['questions'], dict)
    result = provider.tool_turn([{'role': 'tool', 'content': json.dumps(packed)}], [], timeout=1)
    call = result['message']['tool_calls'][0]['function']
    assert call['name'] == 'validate_plan'
    assert json.loads(call['arguments'])['question_ids'] == ['fixture-0']
