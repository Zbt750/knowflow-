import json
import subprocess

from scripts.audit_repository_checkpoint import audit, inspect


def test_reviewed_fixture_is_only_exempt_in_test_scope():
    content = b'api_key="synthetic-test-key"'
    assert inspect("tests/unit/test_example.py", content) == []
    assert inspect("backend/example.py", content)[0]["kind"] == "literal_api_key"


def test_real_shaped_key_in_test_is_not_exempt_and_never_printed():
    value = "sk-" + "A" * 32
    issues = inspect("tests/unit/test_example.py", f'api_key="{value}"'.encode())
    assert {i["kind"] for i in issues} == {"provider_key", "literal_api_key"}
    assert value not in json.dumps(issues)


def test_private_paths_are_blocked():
    for path in [".env", ".env.compose", "storage/private.txt", "eval/reports/run.json", ".pgdata/data.txt"]:
        assert "private_or_generated_path" in {i["kind"] for i in inspect(path, b"text")}


def test_public_env_template_is_still_scanned():
    prefix = b'LLM_API_KEY="'
    assert inspect(".env.example", prefix + b'your-api-key"') == []
    assert inspect(".env.example", prefix + b'not-a-placeholder"')


def test_assets_binary_and_large_files_require_review():
    assert "asset_requires_explicit_review" in {i["kind"] for i in inspect("paper.pdf", b"paper")}
    assert "binary_requires_review" in {i["kind"] for i in inspect("data.txt", b"a\x00b")}
    assert "large_file" in {i["kind"] for i in inspect("data.txt", b"a" * (2 * 1024 * 1024 + 1))}


def test_staged_audit_reads_index_not_modified_workspace(tmp_path):
    subprocess.run(["git", "init", str(tmp_path)], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(tmp_path), "-c", "user.name=Audit", "-c", "user.email=audit@example.invalid",
                    "commit", "--allow-empty", "-m", "test"], check=True, capture_output=True)
    source = tmp_path / "example.py"
    source.write_text("safe = True\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(tmp_path), "add", "example.py"], check=True, capture_output=True)
    source.write_text('api_key=' + '"unexpected-secret-value"\n', encoding="utf-8")
    staged = audit(tmp_path, staged=True)
    assert staged["issues"] == []
    assert staged["index_matches_workspace"] is False
    assert audit(tmp_path)["issues"]
