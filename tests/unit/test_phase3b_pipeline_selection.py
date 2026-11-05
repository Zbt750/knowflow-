from types import SimpleNamespace

from scripts.run_phase3b_question_pipeline import _answer_check_state


def run(role, status):
    return SimpleNamespace(run_role=role, status=status)


def test_answer_check_state_is_resumable_before_role_and_global_limits():
    assert _answer_check_state([run("solve_a", "failed")]) == "resumable"
    assert _answer_check_state([
        run("solve_a", "failed"), run("solve_a", "failed"),
        run("solve_b", "completed"),
    ]) == "resumable"


def test_answer_check_state_excludes_completed_or_exhausted_checks_from_new_batches():
    assert _answer_check_state([
        run("solve_a", "completed"), run("solve_b", "completed"),
        run("verify_c", "completed"),
    ]) == "complete"
    assert _answer_check_state([
        run("solve_a", "failed"), run("solve_a", "failed"), run("solve_a", "failed"),
    ]) == "exhausted"
    assert _answer_check_state([run("solve_a", "failed")] * 6) == "exhausted"
