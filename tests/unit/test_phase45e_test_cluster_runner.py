from types import SimpleNamespace

from scripts.run_phase45e_test_cluster import _preserve_temporary_data_on_failure


def test_failure_cluster_preservation_is_opt_in():
    failed = {"failure": {"stage": "initdb"}, "checks": []}
    assert _preserve_temporary_data_on_failure(
        SimpleNamespace(preserve_temp_on_failure=True), failed
    ) is True
    assert _preserve_temporary_data_on_failure(
        SimpleNamespace(preserve_temp_on_failure=False), failed
    ) is False


def test_failed_check_preserves_cluster_only_when_requested():
    failed_check = {"checks": [{"name": "pytest", "exit_code": 1}]}
    assert _preserve_temporary_data_on_failure(
        SimpleNamespace(preserve_temp_on_failure=True), failed_check
    ) is True
    assert _preserve_temporary_data_on_failure(
        SimpleNamespace(preserve_temp_on_failure=True), {"checks": [{"exit_code": 0}]}
    ) is False
