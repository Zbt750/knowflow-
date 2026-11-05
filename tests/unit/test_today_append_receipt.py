from types import SimpleNamespace
from uuid import uuid4

from backend.services.today_append_result import read_append_result, render_append_result


def test_uncommitted_or_missing_receipt_does_not_report_success():
    assert render_append_result(None) is None
    assert render_append_result({'status': 'proposed', 'items': [{}]}) is None


def test_receipt_uses_readback_position_stem_and_actual_count():
    result = {'status': 'committed', 'total_count': 9, 'added_count': 50,
              'items': [{'number': 7, 'kp_name': '洛必达法则',
                         'question_type': 'single_choice', 'stem': '完整的已提交版本题干',
                         'source_category': 'exam_curated'}]}
    text = render_append_result(result)
    assert '新增 1 道' in text and '共 9 道' in text
    assert '第7题' in text and '洛必达法则' in text
    assert '完整的已提交版本题干' in text and '整理真题' in text
    assert '50' not in text


def test_missing_committed_item_never_becomes_successful_receipt():
    plan = SimpleNamespace(id=uuid4())
    db = SimpleNamespace(get=lambda *args: plan, scalars=lambda *args: [])
    assert read_append_result(db, operation_id=uuid4(), plan_id=plan.id,
                             item_ids=[uuid4()], added_count=1) is None


def test_legacy_receipt_without_item_bindings_is_not_invented():
    assert read_append_result(None, operation_id=uuid4(), plan_id=uuid4(),
                             item_ids=[], added_count=1) is None


def test_task_read_exposes_the_committed_receipt_in_its_message(monkeypatch):
    from backend.services.learning_task_service import task_view
    import backend.services.today_append_result as receipts
    item_id, plan_id = uuid4(), uuid4()
    result = {'status': 'committed', 'total_count': 3, 'items': [
        {'number': 2, 'kp_name': '隐函数求导', 'question_type': 'fill_blank',
         'stem': '保存在不可变版本中的题干', 'source_category': 'development_original'}]}
    monkeypatch.setattr(receipts, 'read_append_result', lambda *a, **kw: result)
    row = SimpleNamespace(id=uuid4(), session_id=uuid4(), goal='增加一道题',
                          budget_minutes=15, status='ready', trace=[], draft=None,
                          message='已加入1道题', error_code=None,
                          metrics={'commit': {'item_ids': [str(item_id)],
                                              'plan_id': str(plan_id), 'added_count': 1}})
    view = task_view(row, db=object())
    assert '第2题' in view.message and '隐函数求导' in view.message
    assert '保存在不可变版本中的题干' in view.message
    assert view.append_result == result
