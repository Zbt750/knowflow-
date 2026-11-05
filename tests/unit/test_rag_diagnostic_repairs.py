from pathlib import Path

from scripts import run_ragas_chat_eval as evaluation


def test_revised_cases_correct_checks_without_changing_original():
    original = {c.case_id: c for c in evaluation.load_cases(Path('eval/dataset/chat_baseline_v3.jsonl'))}
    revised = {c.case_id: c for c in evaluation.load_cases(Path('eval/dataset/chat_baseline_v3_1.jsonl'))}
    assert original['mode-isolation'].answerability == 'general'
    assert revised['mode-isolation'].answerability == 'guard'
    case = revised['math-continuity']
    assert evaluation.phrase_check(case, '连续是必要条件，但不是可导的充分条件。|x|左右导数不同。', 'hybrid')['passed']
    assert evaluation.phrase_check(revised['math-implicit'], r'F_y=2y\neq0，切线x=1。', 'hybrid')['passed']
    case = revised['mode-isolation']
    assert evaluation.phrase_check(case, '不能读取我的资料，请切换模式。', 'scope_notice')['passed']
    assert not evaluation.phrase_check(case, '不能读取我的资料，请切换模式。SYNTHETIC-USER-47', 'scope_notice')['passed']


def test_file_focus_selection_has_exact_three_cases_and_four_requests():
    all_cases = evaluation.load_cases(Path('eval/dataset/chat_baseline_v3_1.jsonl'))
    selected = [case for case in all_cases if case.case_id in {'file-exact', 'file-alias', 'cross-file'}]
    assert [case.case_id for case in selected] == ['file-exact', 'file-alias', 'cross-file']
    assert sum(1 + len(case.setup_questions) for case in selected) == 4


def test_failed_generation_recovers_exact_message_before_cleanup(monkeypatch):
    calls = []
    def api(base, method, path):
        calls.append((method, path))
        return [{'message_id': 'other', 'content': 'wrong'}, {'message_id': 'wanted', 'content': 'partial', 'status': 'failed', 'generation_trace': {'retry_count': 1}, 'evaluation_evidence': {'contexts': ['synthetic']}}]
    monkeypatch.setattr(evaluation, 'api_call', api)
    stream = {'meta': {'message_id': 'wanted'}, 'error': {'code': 'generation_failed'}, 'answer': ''}
    result = evaluation.collect_failed_diagnostic('local', 'session', stream, include_content=True)
    assert result['diagnostic_status'] == 'recovered'
    assert result['partial_answer'] == 'partial'
    assert result['actual_evidence']['contexts'] == ['synthetic']
    assert calls == [('GET', '/chat/sessions/session/messages')]
    private = evaluation.collect_failed_diagnostic('local', 'session', stream, include_content=False)
    assert 'actual_evidence' not in private and 'partial_answer' not in private


def test_diagnostic_failure_is_distinct_and_does_not_retry(monkeypatch):
    def api(*args):
        raise evaluation.EvalError('unavailable')
    monkeypatch.setattr(evaluation, 'api_call', api)
    result = evaluation.collect_failed_diagnostic('local', 's', {'meta': {'message_id': 'm'}}, include_content=True)
    assert result['diagnostic_status'] == 'recovery_failed'
    assert result['recovery_error_type'] == 'EvalError'
    assert evaluation.collect_failed_diagnostic('local', 's', {}, include_content=True)['diagnostic_status'] == 'missing_message_id'


def test_body_clock_excludes_headings_and_split_prefix():
    from backend.chat.service import GENERAL_REFERENCE_PREFIX
    for text in ('##', '## 资料依据', '## 资料依据\n\n', GENERAL_REFERENCE_PREFIX[:30], GENERAL_REFERENCE_PREFIX):
        assert not evaluation.has_visible_body(text)
    assert evaluation.has_visible_body('## 资料依据\n正文')
    assert evaluation.has_visible_body(GENERAL_REFERENCE_PREFIX + '参考正文')


def test_eval_failure_diagnostics_are_saved_before_session_cleanup(monkeypatch):
    import asyncio
    from types import SimpleNamespace
    from scripts import rag_baseline_manifest
    calls = []
    class Judge:
        async def close(self):
            calls.append('judge_closed')
    def api(base, method, path, *args):
        if path == '/health':
            return {'environment': 'test', 'database': 'connected', 'retrieval': 'ready'}
        if method == 'POST':
            return {'session_id': 's'}
        calls.append(method)
        if method == 'GET':
            return [{'message_id': 'm', 'status': 'failed', 'content': 'partial', 'evaluation_evidence': {'contexts': ['test-only']}}]
    monkeypatch.setattr(evaluation, 'api_call', api)
    monkeypatch.setattr(evaluation, 'validate_fixture_scope', lambda *args, **kwargs: None)
    monkeypatch.setattr(rag_baseline_manifest, 'build_manifest', lambda *args: {})
    monkeypatch.setattr(evaluation, 'make_scorers', lambda *args: (Judge(), {}, 'offline'))
    monkeypatch.setattr(evaluation, 'stream_answer', lambda *args: {'answer': '', 'meta': {'message_id': 'm'}, 'done': None, 'error': {'code': 'generation_failed'}})
    args = SimpleNamespace(api_base='http://127.0.0.1:8001/api', dataset='eval/dataset/chat_baseline_v3_1.jsonl', limit=1,
                           baseline_v3=True, evaluation_settings=SimpleNamespace(llm_model='offline'), judge_model=None,
                           judge_max_tokens=1, metric_timeout=1)
    result = asyncio.run(evaluation.run(args))
    row = result['cases'][0]
    assert calls == ['GET', 'DELETE', 'judge_closed']
    assert row['failure_diagnostic']['actual_evidence']['contexts'] == ['test-only']
    assert result['summary']['case_errors'] == 1
    assert 'metrics' not in row
