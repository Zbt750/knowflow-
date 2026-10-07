"""记录可重复基线条件，不读取密钥、真实资料或配置原文。"""
import hashlib
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def build_manifest(settings, dataset, baseline_v3):
    def git(*args):
        return subprocess.check_output(["git", *args], cwd=ROOT).decode("utf-8", errors="replace").strip()
    paths = git("ls-files", "--cached", "--others", "--exclude-standard", "-z").split("\0")
    digests = {}
    for name in sorted(set(paths)):
        path = ROOT / name
        if not path.is_file() or name.startswith((".env", "storage/", ".venv")):
            continue
        digests[name] = hashlib.sha256(path.read_bytes()).hexdigest()
    from backend.chat import service
    from backend.chat.call_trace import PROMPT_VERSION
    from backend.chat.context_screening import POLICY_VERSION, MIN_COSINE
    return {
        "dataset_version": ("chat-baseline-v3.1" if Path(dataset).stem == "chat_baseline_v3_1" else "chat-baseline-v3") if baseline_v3 else "legacy",
        "dataset_sha256": hashlib.sha256(Path(dataset).read_bytes()).hexdigest(),
        "commit": git("rev-parse", "HEAD"), "branch": git("branch", "--show-current"),
        "dirty_status": git("status", "--porcelain"), "workspace_file_sha256": digests,
        "model": settings.llm_model,
        "model_parameters": {field: getattr(settings, field) for field in (
            "llm_timeout_seconds", "llm_max_output_tokens", "llm_retry_max_output_tokens", "llm_history_token_budget", "llm_stream_include_usage")},
        "embedding_model": settings.embedding_model, "reranker_model": settings.reranker_model,
        "context_screening_configuration": {
            "mode": getattr(settings, "chat_context_screening", "off"),
            "version": POLICY_VERSION, "min_cosine": MIN_COSINE,
        },
        "prompt_version": PROMPT_VERSION, "snapshot_version": "actual-model-evidence-v2",
        "retrieval_source_sha256": digests.get("backend/services/retrieval_service.py"),
        "chat_source_sha256": digests.get("backend/chat/service.py"),
        "retrieval_configuration": {name: value for name, value in vars(service).items()
                                    if name.startswith("CHAT_RETRIEVAL_") and isinstance(value, (dict, int, float, str))},
        "diagnostic_limit": "仅实际入prompt与引用可观测；候选和被裁剪阶段未重建，不以二次检索填补",
    }
