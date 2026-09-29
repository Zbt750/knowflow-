"""按扩展名把文件解析成统一的规范化文本。

设计要点（与文档契约一致）：
- 所有格式最终都产出同一种 `normalized_text`，之后走同一套标题树与分块，
  **不给每种文件格式复制一份 chunk 算法**；
- 每个解析器都记录 `parser_version`，便于将来判断是否需要重建索引；
- 扫描件 PDF 明确报错，绝不伪造正文。
"""

from __future__ import annotations

import re
import json
import subprocess
import sys
from zipfile import ZipFile
from dataclasses import dataclass, field
from pathlib import Path

from backend.ingestion.source_io import (
    ScannedPdfError,
    decode_text,
    read_limited_bytes,
)
from backend.ingestion.text_normalize import normalize_text

# PDF 可提取字符数低于这个值基本可判定为扫描件。
SCANNED_PDF_MIN_CHARS = 30
MAX_DOCUMENT_CHARS = 1_000_000
MAX_PDF_PAGES = 500
MAX_DOCX_EXPANDED_BYTES = 32 * 1024 * 1024
PARSE_TIMEOUT_SECONDS = 30


def _check_text_size(text: str) -> str:
    if len(text) > MAX_DOCUMENT_CHARS:
        raise DocumentParseError("document_content_too_large")
    return text


class DocumentParseError(ValueError):
    """解析失败，且带一个**稳定业务错误码**。

    为什么必须有这一层：pypdf / python-docx 会抛 `PdfReadError`、`BadZipFile`
    之类的具体异常，甚至 `zipfile` 的异常类型会随版本变化。如果让它们冒到
    worker 的兜底分支，错误码就会变成 `unexpected:PdfReadError` 并被界面原样显示 ——
    用户看到的是一个 Python 类名，不是可理解的失败原因。

    约定：`code` 必须是 errors.SAFE_MESSAGES 里登记过的码，`detail` 只进日志。
    """

    def __init__(self, code: str, detail: str | None = None) -> None:
        self.code = code
        self.detail = detail
        super().__init__(code)

# TXT 标题启发式：编号开头且不像句子的短行提升为二级标题。
NUMBERED_TITLE_RE = re.compile(r"^(?:第[一二三四五六七八九十0-9]+[章节]|\d+(?:\.\d+){0,4})[\s、.]+(.+)$")


@dataclass(frozen=True)
class ParsedSource:
    """解析结果：规范化文本 + 解析器版本 + 诊断信息。"""

    normalized_text: str
    parser_version: str
    diagnostics: tuple[str, ...] = field(default_factory=tuple)


def plain_text_to_markdown(text: str) -> str:
    """把纯文本里的编号标题提升为 Markdown 标题，让标题树有结构可用。"""
    lines: list[str] = []
    for raw_line in text.split("\n"):
        line = raw_line.rstrip()
        match = NUMBERED_TITLE_RE.match(line.strip())
        # 只有「短且不像句子」的行才当标题，避免把正文句子误判成标题。
        if match and len(match.group(1)) <= 80 and not line.endswith(("。", "！", "？")):
            lines.append(f"## {line.strip()}")
            continue
        lines.append(line)
    return "\n".join(lines)


def docx_to_markdown(path: Path) -> str:
    """用 python-docx 读段落与表格，转成 Markdown 风格文本。"""
    from docx import Document
    from docx.oxml.ns import qn
    from docx.text.paragraph import Paragraph
    from docx.table import Table

    with ZipFile(path) as archive:
        entries = archive.infolist()
        if len(entries) > 2000 or sum(entry.file_size for entry in entries) > MAX_DOCX_EXPANDED_BYTES:
            raise DocumentParseError("document_content_too_large")
    document = Document(str(path))
    parts: list[str] = []
    chars = 0
    for block in document.element.body.iterchildren():
        if block.tag == qn("w:tbl"):
            table = Table(block, document)
            for row in table.rows:
                cells = [cell.text.strip() for cell in row.cells]
                if any(cells):
                    line = " | ".join(cells)
                    chars += len(line) + 2
                    if chars > MAX_DOCUMENT_CHARS:
                        raise DocumentParseError("document_content_too_large")
                    parts.append(line)
            continue
        if block.tag != qn("w:p"):
            continue
        paragraph = Paragraph(block, document)
        text = paragraph.text.strip()
        chars += len(text) + 10
        if chars > MAX_DOCUMENT_CHARS:
            raise DocumentParseError("document_content_too_large")
        if not text:
            continue
        style = (paragraph.style.name or "").lower()
        # Word 的 Heading 1..6 与中文「标题 1..6」都映射成 Markdown 标题。
        level = 0
        for index in range(1, 7):
            if style in (f"heading {index}", f"标题 {index}"):
                level = index
                break
        parts.append(f"{'#' * level} {text}" if level else text)
    return _check_text_size("\n\n".join(parts))


def parse_txt(path: Path) -> ParsedSource:
    decoded = decode_text(read_limited_bytes(path))
    marked = plain_text_to_markdown(decoded.text)
    return ParsedSource(
        normalize_text(marked),
        "text-v1",
        (f"encoding={decoded.encoding}",),
    )


def parse_docx(path: Path) -> ParsedSource:
    """只支持真正的 .docx；损坏或加密的文件给出稳定错误码。"""
    try:
        marked = docx_to_markdown(path)
    except DocumentParseError:
        raise
    except Exception as error:  # noqa: BLE001 - python-docx 底层会抛 zipfile 的多种异常
        # 同上：`BadZipFile` / `PackageNotFoundError` 之类的类名绝不能漏到界面，
        # 用户只知道「这个文件打不开」，不知道也不该知道是 zip 结构坏了。
        raise DocumentParseError(
            "document_parse_failed", f"docx:{type(error).__name__}"
        ) from error
    return ParsedSource(
        normalize_text(marked),
        "docx-v2",
        (),
    )


def parse_pdf(path: Path) -> ParsedSource:
    """只支持含文本层的 PDF；扫描件与损坏文件都给出稳定错误码。"""
    from pypdf import PdfReader

    try:
        reader = PdfReader(str(path))
        page_count = len(reader.pages)
        if page_count > MAX_PDF_PAGES:
            raise DocumentParseError("document_content_too_large")
        parts: list[str] = []
        extracted_chars = 0
        for index, page in enumerate(reader.pages, start=1):
            page_text = (page.extract_text() or "").strip()
            extracted_chars += len(page_text)
            if extracted_chars > MAX_DOCUMENT_CHARS:
                raise DocumentParseError("document_content_too_large")
            if not page_text:
                # 空页不产出标题，避免标题树中出现无内容节点。
                continue
            parts.append(f"## 第 {index} 页\n\n{page_text}")
    except DocumentParseError:
        raise
    except Exception as error:  # noqa: BLE001 - 第三方 PDF 库异常类型多且随版本变化
        # 关键：pypdf 抛的是 PdfReadError 之类的具体异常。若让它冒到上层，
        # 错误码会变成 `unexpected:PdfReadError` 并被界面原样显示给用户。
        # 这里统一收敛成稳定业务码，真实的异常类型只写进日志。
        raise DocumentParseError(
            "document_parse_failed", f"pdf:{type(error).__name__}"
        ) from error

    if extracted_chars < SCANNED_PDF_MIN_CHARS:
        # 文本太少基本可判定为扫描件；V1 不支持 OCR。
        raise ScannedPdfError("scanned_pdf")
    return ParsedSource(
        normalize_text(_check_text_size("\n\n".join(parts))),
        "pypdf-text-v1",
        (f"pages={page_count}", "layout_restore_is_p2"),
    )


def parse_source(path: Path) -> ParsedSource:
    """按安全后缀选择解析器；调用者不用知道各格式的实现细节。"""
    suffix = path.suffix.lower()
    if suffix == ".md":
        # Markdown 不过标题启发式，保留作者写入的原始结构。
        decoded = decode_text(read_limited_bytes(path))
        return ParsedSource(
            normalize_text(decoded.text), "markdown-v1", (f"encoding={decoded.encoding}",)
        )
    if suffix == ".txt":
        return parse_txt(path)
    if suffix == ".docx":
        return _parse_binary_isolated(path)
    if suffix == ".pdf":
        return _parse_binary_isolated(path)
    # 其余后缀在上层已被拒绝，这里只是兜底。
    raise ValueError("unsupported_type")


def _parse_binary_isolated(path: Path) -> ParsedSource:
    """二进制解析放到可终止的子进程，避免线程超时后解析仍占用后端。"""
    read_limited_bytes(path)
    try:
        result = subprocess.run(
            [sys.executable, "-m", "backend.ingestion.parse_worker", str(path.resolve())],
            cwd=Path(__file__).resolve().parents[2], capture_output=True,
            timeout=PARSE_TIMEOUT_SECONDS,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
        )
    except subprocess.TimeoutExpired as error:
        raise DocumentParseError("document_parse_timeout") from error
    if result.returncode != 0:
        raise DocumentParseError("document_parse_failed", "parser_process_failed")
    try:
        payload = json.loads(result.stdout)
    except (ValueError, UnicodeError) as error:
        raise DocumentParseError("document_parse_failed", "invalid_parser_result") from error
    if payload.get("error") == "scanned_pdf":
        raise ScannedPdfError("scanned_pdf")
    if payload.get("error"):
        code = payload["error"]
        if code not in {"document_parse_failed", "document_content_too_large"}:
            code = "document_parse_failed"
        raise DocumentParseError(code)
    return ParsedSource(_check_text_size(payload["normalized_text"]), payload["parser_version"], tuple(payload.get("diagnostics", [])))
