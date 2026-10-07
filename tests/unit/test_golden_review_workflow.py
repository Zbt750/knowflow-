from copy import deepcopy
from datetime import date, timedelta
from pathlib import Path

import pytest

from backend.services.golden_learning_slice import GoldenSlice
from scripts.apply_golden_review import apply_review, review_template


@pytest.fixture
def review_input():
    path = Path(__file__).resolve().parents[2] / 'eval/golden/integral_binary_tree_v1.json'
    asset = GoldenSlice.model_validate_json(path.read_text(encoding='utf-8'))
    decisions = review_template(asset)
    decisions.update(attest_human_review=True, reviewer='SIMULATED TEST HUMAN - NOT ACTUAL CERTIFICATION', reviewed_on=date.today().isoformat())
    decisions['questions'] = decisions['questions'][:1]
    decisions['questions'][0]['aspects'] = {'answer': 'Isolated synthetic test attestation only'}
    decisions['lessons'] = []
    return asset, decisions


def test_template_never_certifies_and_partial_review_keeps_gate_closed(review_input):
    asset, decisions = review_input
    template = review_template(asset)
    assert template['attest_human_review'] is False and template['reviewer'] == ''
    result = apply_review(asset, decisions)
    assert result.questions[0].reviews['answer'].status == 'VERIFIED'
    assert not result.questions[0].verified
    assert asset.questions[0].reviews['answer'].status == 'GENERATED'


@pytest.mark.parametrize('kind', ['no-human', 'wrong-asset', 'wrong-content', 'no-reviewer',
                                  'blank-note', 'unknown-aspect', 'future-date', 'duplicate', 'empty'])
def test_invalid_or_stale_declarations_rejected(review_input, kind):
    asset, original = review_input
    decisions = deepcopy(original)
    if kind == 'no-human': decisions['attest_human_review'] = False
    if kind == 'wrong-asset': decisions['asset_sha256'] = '0' * 64
    if kind == 'wrong-content': decisions['questions'][0]['content_sha256'] = '0' * 64
    if kind == 'no-reviewer': decisions['reviewer'] = ''
    if kind == 'blank-note': decisions['questions'][0]['aspects']['answer'] = ''
    if kind == 'unknown-aspect': decisions['questions'][0]['aspects'] = {'everything': 'invalid'}
    if kind == 'future-date': decisions['reviewed_on'] = (date.today() + timedelta(days=1)).isoformat()
    if kind == 'duplicate': decisions['questions'] *= 2
    if kind == 'empty': decisions['questions'] = []
    with pytest.raises(ValueError): apply_review(asset, decisions)
    assert asset.questions[0].reviews['answer'].status == 'GENERATED'
