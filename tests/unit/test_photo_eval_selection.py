import pytest
from scripts.run_photo_transcription_eval import select_cases

DATASET = {'cases':[{'id':'code','review':True},{'id':'blur'},{'id':'math','review':True}]}


def test_targeted_selection_respects_order_and_disables_all_reviews():
    cases = select_cases(DATASET, ['code','blur'], True)
    assert [c['id'] for c in cases] == ['code','blur']
    assert all(c['review'] is False for c in cases)
    assert DATASET['cases'][0]['review'] is True


@pytest.mark.parametrize('ids', [['private'], ['code','code']])
def test_unknown_or_duplicate_ids_rejected(ids):
    with pytest.raises(ValueError): select_cases(DATASET, ids)


def test_default_selection_preserves_existing_review_budget():
    assert sum(c['review'] for c in select_cases(DATASET, None)) == 2
