"""安全读取与严格解码。

为什么需要单独一层：
- 资料路径来自数据库，必须防止 `..` 与符号链接逃出资料根目录；
- 同一份文件在不同机器上可能用不同编码保存，必须严格解码而不是忽略错误，
  否则「丢失的字符」会悄悄进入索引，引用回跳原文时就对不上了。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

# 只放行这四种后缀；其余格式一律拒绝，不做猜测。
ALLOWED_SUFFIXES: frozenset[str] = frozenset({".md", ".txt", ".docx", ".pdf"})

# 单个文件的唯一上限：**上传与解析共用同一个常量**。
#
# 为什么不能设两档（曾经是上传 20 MB / 解析 5 MB）：
# 那样会出现「上传返回 201、用户看到进入队列，随后异步失败」的先成功后失败，
# 而且失败提示会说「超过 20 MB」——对一个 11 MB 的文件来说这是假话。
# 用户无法理解，也违背「失败原因必须可理解」的要求。
#
# 这个值同时决定了内存占用（解析要把整篇读进内存）与索引规模
# （约 10 MB 正文 ≈ 1.5 万个块），10 MB 是本机可接受的上限。
MAX_FILE_BYTES = 10 * 1024 * 1024

# 兼容旧名字：解析阶段的上限就是同一个上限。
MAX_SOURCE_BYTES = MAX_FILE_BYTES

# 按顺序尝试的编码：先 UTF-8（带 BOM 也能识别），再 GB18030（中文 Windows 常见）。
CANDIDATE_ENCODINGS: tuple[str, ...] = ("utf-8-sig", "gb18030")


class DocumentDecodeError(ValueError):
    """文件无法用受支持的编码解码。"""


class ScannedPdfError(ValueError):
    """PDF 没有可提取文本（大概率是扫描件）；V1 不支持 OCR。"""


@dataclass(frozen=True)
class DecodedText:
    """解码结果：正文 + 实际使用的编码（写进诊断信息，便于排查乱码）。"""

    text: str
    encoding: str


def safe_suffix(filename: str) -> str:
    """取小写后缀并校验白名单；不合法时抛 unsupported_type。"""
    # 先剥掉任何路径成分：客户端可能传来 "a/b/../../x.md"。
    suffix = Path(Path(filename).name).suffix.lower()
    if suffix not in ALLOWED_SUFFIXES:
        raise ValueError("unsupported_type")
    return suffix


def resolve_source_path(materials_root: Path, stored_path: str) -> Path:
    """把相对路径解析到资料根目录内，并确认文件真实存在。

    先拼接后 `resolve()`，这样 `..` 与符号链接都会被消解；
    只要结果不在根目录之下就一律拒绝。
    """
    root_resolved = materials_root.resolve()
    candidate = (root_resolved / stored_path).resolve()
    # 目录本身也不是合法资料：要求 candidate 严格位于根目录之下。
    if root_resolved not in candidate.parents:
        raise ValueError("unsafe_storage_path")
    # 先判断「是不是存在的文件」，再判断后缀：
    # 目录名通常没有后缀，先查后缀会报出误导性的 unsupported_type。
    if not candidate.is_file():
        raise ValueError("material_file_not_found")
    if candidate.suffix.lower() not in ALLOWED_SUFFIXES:
        raise ValueError("unsupported_type")
    return candidate


def read_limited_bytes(path: Path, *, max_bytes: int = MAX_SOURCE_BYTES) -> bytes:
    """先看大小再读，避免把超大文件整个读进内存。"""
    size = path.stat().st_size
    if size == 0:
        raise ValueError("empty_file")
    if size > max_bytes:
        raise ValueError("file_too_large")
    return path.read_bytes()


def decode_text(data: bytes) -> DecodedText:
    """严格解码：所有候选编码都失败时报错，绝不使用 errors="ignore"。"""
    for encoding in CANDIDATE_ENCODINGS:
        try:
            return DecodedText(text=data.decode(encoding), encoding=encoding)
        except UnicodeDecodeError:
            continue
    raise DocumentDecodeError("document_decode_failed")