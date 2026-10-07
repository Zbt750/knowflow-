"""上传文件的流式落盘：同目录 `.part` → 原子替换。

为什么必须原子替换：
   如果直接写正式文件，一旦中途失败就会留下半个文件，
   而数据库里可能已经有指向它的记录 —— 用户会看到一份「永远解析失败」的资料。
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from uuid import UUID

from fastapi import UploadFile

from backend.ingestion.source_io import MAX_FILE_BYTES, safe_suffix

# 上传上限与解析上限必须是同一个值：见 source_io.MAX_FILE_BYTES 的说明。
# 若这里放宽，用户会遇到「上传成功、随后异步失败」，且提示与实际不符。
MAX_UPLOAD_BYTES = MAX_FILE_BYTES
# 每次读取 1 MiB：既能算 hash，又不会把整个文件读进内存。
CHUNK_SIZE = 1024 * 1024


class FileTooLargeError(ValueError):
    """上传超过大小上限。"""


def _safe_directory(root: Path, material_id: UUID) -> Path:
    """为一份资料准备目录，并确认它确实位于根目录之下。"""
    root_resolved = root.resolve()
    directory = (root_resolved / str(material_id)).resolve()
    if root_resolved not in directory.parents:
        raise ValueError("unsafe_storage_path")
    directory.mkdir(parents=True, exist_ok=True)
    return directory


async def save_upload_streaming(
    upload: UploadFile,
    *,
    material_id: UUID,
    root: Path,
    max_bytes: int = MAX_UPLOAD_BYTES,
) -> tuple[str, int, str]:
    """流式写入 `.part`，算 SHA-256，完成后原子替换成正式文件。

    返回 `(相对根目录的路径, 字节数, 原始字节的 SHA-256)`。
    """
    suffix = safe_suffix(upload.filename or "untitled")
    directory = _safe_directory(root, material_id)
    final_path = directory / f"source{suffix}"
    temp_path = directory / f"source{suffix}.part"

    digest = hashlib.sha256()
    total = 0
    try:
        with temp_path.open("wb") as handle:
            while True:
                chunk = await upload.read(CHUNK_SIZE)
                if not chunk:
                    break
                total += len(chunk)
                if total > max_bytes:
                    raise FileTooLargeError("file_too_large")
                digest.update(chunk)
                handle.write(chunk)
            handle.flush()
        if total == 0:
            raise ValueError("empty_file")
        # 原子替换：读者要么看到旧文件，要么看到完整新文件。
        temp_path.replace(final_path)
    except Exception:
        # 失败时清理临时文件，绝不留下半成品。
        temp_path.unlink(missing_ok=True)
        raise
    finally:
        await upload.close()

    stored_path = str(final_path.relative_to(root.resolve())).replace("\\", "/")
    return stored_path, total, digest.hexdigest()


def delete_stored_file(root: Path, stored_path: str) -> None:
    """删除已落盘的文件；重复调用是安全的。"""
    root_resolved = root.resolve()
    target = (root_resolved / stored_path).resolve()
    # 删除同样要防越界：即使是数据库里的路径也不能跳出根目录。
    if root_resolved not in target.parents:
        raise ValueError("unsafe_storage_path")
    target.unlink(missing_ok=True)
    # 目录只剩空壳时顺手删掉；失败不影响主流程（比如目录里还有别的文件）。
    try:
        if target.parent.exists() and not any(target.parent.iterdir()):
            target.parent.rmdir()
    except OSError:
        pass