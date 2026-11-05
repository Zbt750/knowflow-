import json

import pytest

from scripts.test_backend import _counts, _validate_manifest


def test_manifest_must_bind_exact_cluster_port_and_test_database(tmp_path):
    cluster = tmp_path / "KaoyanStudy" / "postgres" / "cluster"
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({
        "format": "naiwa-owned-test-pg18-v1",
        "cluster_directory": str(cluster.resolve()),
        "cluster_id": "a" * 32,
        "system_identifier": "123456789",
        "port": 18761,
        "database": "kaoyan_test",
    }), encoding="utf-8")

    assert _validate_manifest(manifest, cluster=cluster, port=18761)["database"] == "kaoyan_test"
    with pytest.raises(RuntimeError, match="manifest_invalid"):
        _validate_manifest(manifest, cluster=cluster, port=18762)
    with pytest.raises(RuntimeError, match="manifest_invalid"):
        _validate_manifest(manifest, cluster=cluster, port=18761, cluster_id="b" * 32)


def test_existing_cluster_without_its_runner_manifest_is_not_adopted(tmp_path):
    cluster = tmp_path / "cluster"
    cluster.mkdir()
    (cluster / "PG_VERSION").write_text("18", encoding="ascii")

    with pytest.raises(RuntimeError, match="manifest_missing"):
        _validate_manifest(tmp_path / "missing.json", cluster=cluster, port=18761)


def test_junit_counts_aggregate_suites_and_skip(tmp_path):
    junit = tmp_path / "junit.xml"
    junit.write_text(
        '<testsuites><testsuite tests="3" failures="1" errors="0" skipped="1"/>'
        '<testsuite tests="2" failures="0" errors="1" skipped="0"/></testsuites>',
        encoding="utf-8",
    )
    assert _counts(junit) == {"tests": 5, "failures": 1, "errors": 1, "skipped": 1}
