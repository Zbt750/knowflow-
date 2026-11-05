"""Read-only checkpoint inventory. Never print secret values or stage files.

Heuristic scanning is not a guarantee of absence of credentials/copyright issues.
Review reported paths/lines before staging; re-run against the exact Git index.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import subprocess

BLOCKED_PARTS = {"storage", ".pgdata", "node_modules", "__pycache__", ".venv", ".venv-ragas",
                 ".venv-desktop-build", "chroma", ".devlogs", "logs", "model-cache"}
RESTRICTED_SUFFIXES = {".pdf", ".docx", ".zip", ".exe", ".bin", ".pem", ".key", ".p12", ".pfx",
                       ".png", ".jpg", ".jpeg", ".webp", ".pt", ".safetensors", ".sqlite", ".db"}
PATTERNS = {
    "provider_key": re.compile(r"\bsk-[A-Za-z0-9_-]{16,}"),
    "github_token": re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,})"),
    "aws_access_key": re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"),
    "private_key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "literal_api_key": re.compile(r'''(?i)["']?(?:LLM_API_KEY|VISION_API_KEY|api_key)["']?\s*[:=]\s*["']([^"'\r\n]{8,})["']'''),
}
TEST_PLACEHOLDERS = {"test-key", "fake-key", "test-api-key", "unit-test-key", "synthetic-key",
    "synthetic-test-key", "synthetic", "DO_NOT_RECORD", "test-only", "inherited-development-key",
    "placeholder", "replacement-test-key", "secret-test-value", "synthetic-vision-key"}
TEMPLATE_PLACEHOLDERS = {"your-api-key", "your_api_key", "replace-with-your-key"}


def inspect(path, data):
    p = PurePosixPath(path)
    issues = []
    if (any(part in BLOCKED_PARTS for part in p.parts) or path.startswith("eval/reports/")
            or path.startswith("frontend/dist/") or path.startswith("frontend/test-results/")
            or path.startswith("frontend/playwright-report/")
            or (p.name.startswith(".env") and not p.name.endswith(".example"))):
        issues.append({"path": path, "kind": "private_or_generated_path"})
    if p.suffix.lower() in RESTRICTED_SUFFIXES:
        issues.append({"path": path, "kind": "asset_requires_explicit_review"})
    if len(data) > 2 * 1024 * 1024:
        issues.append({"path": path, "kind": "large_file", "bytes": len(data)})
    if b"\x00" in data:
        issues.append({"path": path, "kind": "binary_requires_review"})
        return issues
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        issues.append({"path": path, "kind": "non_utf8_requires_review"})
        return issues
    for number, line in enumerate(text.splitlines(), 1):
        for kind, pattern in PATTERNS.items():
            for match in pattern.finditer(line):
                value = match.group(1) if kind == "literal_api_key" else match.group(0)
                # Only exempt reviewed literal fixtures in their intended scope.
                # Real provider/token patterns are never exempt, even in tests.
                if kind == "literal_api_key" and (
                    (path.startswith("tests/") and value in TEST_PLACEHOLDERS)
                    or (p.name in {".env.example", ".env.compose.example"} and value in TEMPLATE_PLACEHOLDERS)
                ):
                    continue
                issues.append({"path": path, "line": number, "kind": kind})
    return issues


def git(root, *args):
    return subprocess.check_output(["git", "-C", str(root), *args])


def index_matches_workspace(root, paths):
    """Compare Git-normalized blobs, respecting the repository's line endings."""
    entries = {}
    for entry in git(root, "ls-files", "--stage", "-z").split(b"\0"):
        if entry:
            metadata, name = entry.split(b"\t", 1)
            mode, oid, stage = metadata.split()
            if stage != b"0" or mode != b"100644" and mode != b"100755":
                return False
            entries[name.decode("utf-8")] = oid.decode("ascii")
    if any(not (root / p).is_file() for p in paths):
        return False
    for start in range(0, len(paths), 40):
        batch = paths[start:start + 40]
        oids = git(root, "hash-object", "--", *batch).decode("ascii").splitlines()
        if len(oids) != len(batch) or any(entries.get(p) != oid for p, oid in zip(batch, oids)):
            return False
    return True


def audit(root, staged=False):
    root = root.resolve()
    args = ("ls-files", "-z") if staged else ("ls-files", "-z", "--cached", "--others", "--exclude-standard")
    paths = sorted(set(p.decode("utf-8") for p in git(root, *args).split(b"\0") if p))
    index_links = set()
    if staged:
        for entry in git(root, "ls-files", "--stage", "-z").split(b"\0"):
            if entry:
                metadata, path_bytes = entry.split(b"\t", 1)
                if metadata.split()[0] in {b"120000", b"160000"}:
                    index_links.add(path_bytes.decode("utf-8"))
    rows, issues, missing = [], [], []
    for path in paths:
        source = root / path
        if staged:
            if path in index_links:
                issues.append({"path": path, "kind": "link_or_submodule_requires_review"})
                continue
            data = git(root, "show", ":" + path)
        else:
            if not source.exists():
                missing.append(path)
                continue
            if source.is_symlink() or not source.resolve().is_relative_to(root):
                issues.append({"path": path, "kind": "link_or_path_escape"})
                continue
            data = source.read_bytes()
        rows.append({"path": path, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()})
        issues.extend(inspect(path, data))
    digest = hashlib.sha256(json.dumps(rows, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return {"version": "checkpoint-inventory-v1", "scope": "git_index" if staged else "tracked_and_unignored_workspace",
        "created_at": datetime.now(timezone.utc).isoformat(), "head": git(root, "rev-parse", "HEAD").decode().strip(),
        "files": len(rows), "bytes": sum(r["bytes"] for r in rows), "content_manifest_sha256": digest,
        "index_matches_workspace": index_matches_workspace(root, paths) if staged else None,
        "missing_workspace_files": missing, "issues": issues, "manifest": rows,
        "limitations": ["heuristic_secret_scan_not_exhaustive", "not_a_license_certificate",
                       "not_an_audit_of_all_prior_git_history", "does_not_include_ignored_private_data"]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--staged", action="store_true", help="Inspect the exact full Git index, not working files")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Refuse to overwrite a previous inventory")
    report = audit(args.root, args.staged)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k != "manifest"}, ensure_ascii=False, indent=2))
    raise SystemExit(1 if report["issues"] or report["missing_workspace_files"]
                     or report["index_matches_workspace"] is False else 0)


if __name__ == "__main__":
    main()
