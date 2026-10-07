import pytest
from scripts.run_photo_transcription_eval import select_cases, load_photo_dataset

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


@pytest.mark.parametrize('name,total,reviews', [('photo-handwriting-v1',6,2), ('photo-messy-handwriting-eval-v1',4,0)])
def test_pinned_datasets_keep_separate_authorization_budgets(name,total,reviews):
    dataset=load_photo_dataset(name)
    assert len(dataset['cases'])==total
    assert sum(c['review'] for c in select_cases(dataset,None))==reviews
    assert all(len(dataset['image_sha256'][c['id']])==64 for c in dataset['cases'])


@pytest.mark.parametrize('name', ['../../.env','photo-messy-handwriting-assets-v1','private'])
def test_unapproved_dataset_paths_are_rejected(name):
    with pytest.raises(ValueError,match='pinned'): load_photo_dataset(name)
