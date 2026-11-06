from copy import deepcopy
from uuid import uuid4

from backend.models.learning import Question
from backend.services.auto_question_review import question_snapshot_payload, question_snapshot_sha256
from backend.services.golden_learning_slice import digest


def test_hash_matches_independent_snapshot_without_mutating_nested_config():
    config = {'public_practice_release': {'enabled': True}, 'generation': {'steps': [{'value': '隐函数'}]}}
    question = Question(id=uuid4(), kp_id=uuid4(), grading_config=deepcopy(config), skill_tags=['求导'])
    payload = question_snapshot_payload(question)
    before = question_snapshot_sha256(question)
    assert before == digest(payload)
    assert question.grading_config == config
    payload['grading_config']['generation']['steps'][0]['value'] = '独立快照'
    assert question.grading_config == config
    question.grading_config['generation']['steps'][0]['value'] = '修改内容'
    assert question_snapshot_sha256(question) != before
    assert question_snapshot_sha256(question) == digest(question_snapshot_payload(question))


def test_release_flag_does_not_change_content_hash():
    question = Question(id=uuid4(), kp_id=uuid4(), grading_config={'method': 'single_choice'})
    before = question_snapshot_sha256(question)
    question.grading_config['public_practice_release'] = {'enabled': True}
    assert question_snapshot_sha256(question) == before


def test_unseen_nodes_keep_explicit_empty_batch_history():
    from types import SimpleNamespace
    from backend.services.practice_service import _candidate_side_data
    calls = []
    def query(statement):
        calls.append(statement)
        return SimpleNamespace(all=lambda: [])
    ids = [uuid4(), uuid4()]
    result = _candidate_side_data(SimpleNamespace(execute=query, scalars=query), ids)
    assert len(calls) == 2
    assert result == {key: ({}, {}) for key in ids}
    result[ids[0]][0]['one'] = 'history'
    assert result[ids[1]] == ({}, {})
