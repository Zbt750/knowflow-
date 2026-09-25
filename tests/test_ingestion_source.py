"""阶段 C 第一层：安全读取、文档解析、流式落盘的单元测试。

这一层是「资料进知识库」的入口，出错方式都很安静（乱码、半个文件、路径越界），
所以每一条防护都单独用一个用例钉住。
"""

from __future__ import annotations

import asyncio
import hashlib
from pathlib import Path
from uuid import uuid4

import pytest

from backend.ingestion.document_parsers import (
    parse_source,
    plain_text_to_markdown,
)
from backend.ingestion.file_storage import (
    MAX_UPLOAD_BYTES,
    FileTooLargeError,
    delete_stored_file,
    save_upload_streaming,
)
from backend.ingestion.source_io import (
    DocumentDecodeError,
    ScannedPdfError,
    decode_text,
    read_limited_bytes,
    resolve_source_path,
    safe_suffix,
)


class FakeUpload:
    """最小化 UploadFile 替身：只要 read/close 就能覆盖落盘逻辑。"""

    def __init__(self, filename: str, data: bytes) -> None:
        self.filename = filename
        self._data = data
        self._offset = 0
        self.closed = False

    async def read(self, size: int = -1) -> bytes:
        if size is None or size < 0:
            chunk = self._data[self._offset :]
            self._offset = len(self._data)
            return chunk
        chunk = self._data[self._offset : self._offset + size]
        self._offset += len(chunk)
        return chunk

    async def close(self) -> None:
        self.closed = True


# ---------------------------------------------------------------- safe_suffix


def test_safe_suffix_accepts_whitelist() -> None:
    assert safe_suffix("a.MD") == ".md"
    assert safe_suffix("b.txt") == ".txt"
    assert safe_suffix("c.docx") == ".docx"
    assert safe_suffix("d.pdf") == ".pdf"


def test_safe_suffix_strips_directories_before_checking() -> None:
    """带路径的文件名要按最后一段判断，不能因为目录名合法就放过。"""
    assert safe_suffix("../../evil/x.md") == ".md"
    with pytest.raises(ValueError, match="unsupported_type"):
        safe_suffix("../../evil/x.exe")


@pytest.mark.parametrize("name", ["x.exe", "x.docx.exe", "noext", "x.md.exe", "x"])
def test_safe_suffix_rejects_others(name: str) -> None:
    with pytest.raises(ValueError, match="unsupported_type"):
        safe_suffix(name)


# ------------------------------------------------------- resolve_source_path


def test_resolve_source_path_inside_root(tmp_path: Path) -> None:
    root = tmp_path / "materials"
    (root / "abc").mkdir(parents=True)
    (root / "abc" / "source.md").write_text("内容", encoding="utf-8")

    resolved = resolve_source_path(root, "abc/source.md")
    assert resolved == (root / "abc" / "source.md").resolve()


def test_resolve_source_path_rejects_escape(tmp_path: Path) -> None:
    root = tmp_path / "materials"
    root.mkdir(parents=True)
    outside = tmp_path / "secret.md"
    outside.write_text("机密", encoding="utf-8")

    with pytest.raises(ValueError, match="unsafe_storage_path"):
        resolve_source_path(root, "../secret.md")


def test_resolve_source_path_rejects_root_itself(tmp_path: Path) -> None:
    """根目录本身不是资料文件。"""
    root = tmp_path / "materials"
    root.mkdir(parents=True)
    with pytest.raises(ValueError, match="unsafe_storage_path"):
        resolve_source_path(root, ".")


def test_resolve_source_path_rejects_missing_file(tmp_path: Path) -> None:
    root = tmp_path / "materials"
    root.mkdir(parents=True)
    with pytest.raises(ValueError, match="material_file_not_found"):
        resolve_source_path(root, "abc/source.md")


def test_resolve_source_path_rejects_directory(tmp_path: Path) -> None:
    """指向目录的路径不能当成文件读。"""
    root = tmp_path / "materials"
    (root / "abc").mkdir(parents=True)
    with pytest.raises(ValueError, match="material_file_not_found"):
        resolve_source_path(root, "abc")


def test_resolve_source_path_rejects_bad_suffix(tmp_path: Path) -> None:
    root = tmp_path / "materials"
    (root / "abc").mkdir(parents=True)
    (root / "abc" / "source.exe").write_bytes(b"MZ")
    with pytest.raises(ValueError, match="unsupported_type"):
        resolve_source_path(root, "abc/source.exe")


# ---------------------------------------------------------- read_limited_bytes


def test_read_limited_bytes_rejects_empty(tmp_path: Path) -> None:
    target = tmp_path / "empty.md"
    target.write_bytes(b"")
    with pytest.raises(ValueError, match="empty_file"):
        read_limited_bytes(target)


def test_read_limited_bytes_rejects_too_large(tmp_path: Path) -> None:
    target = tmp_path / "big.md"
    target.write_bytes(b"x" * 50)

    with pytest.raises(ValueError, match="file_too_large"):
        read_limited_bytes(target, max_bytes=10)


def test_read_limited_bytes_reads_within_limit(tmp_path: Path) -> None:
    target = tmp_path / "ok.md"
    target.write_text("洛必达法则", encoding="utf-8")

    assert read_limited_bytes(target, max_bytes=100).decode("utf-8") == "洛必达法则"


# ------------------------------------------------------------------ decode_text


def test_decode_text_prefers_utf8_sig_and_drops_bom() -> None:
    decoded = decode_text("\ufeff第一行".encode("utf-8"))
    assert decoded.encoding == "utf-8-sig"
    # BOM 必须被剥掉，否则第一个标题会因前缀字符而识别失败。
    assert decoded.text == "第一行"


def test_decode_text_falls_back_to_gb18030() -> None:
    decoded = decode_text("洛必达法则".encode("gb18030"))
    assert decoded.encoding == "gb18030"
    assert decoded.text == "洛必达法则"


def test_decode_text_never_silently_drops_characters() -> None:
    """无效字节必须报错：忽略错误会让正文悄悄变短，引用回跳就对不上了。"""
    with pytest.raises(DocumentDecodeError, match="document_decode_failed"):
        decode_text(b"\xff\xfe\x00\x01\xff")


# ------------------------------------------------------- plain_text_to_markdown


def test_plain_text_to_markdown_promotes_numbered_headings() -> None:
    text = "第一章 极限\n洛必达法则用于求极限。\n1.2 常见公式"
    marked = plain_text_to_markdown(text)

    assert "## 第一章 极限" in marked
    assert "## 1.2 常见公式" in marked
    # 以句号结尾的正文句子不能被当成标题。
    assert "洛必达法则用于求极限。" in marked
    assert "## 洛必达法则" not in marked


def test_plain_text_to_markdown_keeps_long_numbered_lines_as_body() -> None:
    long_line = "1.1 " + "极限的计算方法" * 20
    assert not plain_text_to_markdown(long_line).startswith("##")


# ------------------------------------------------------------------ parse_source


def test_parse_markdown_keeps_author_structure(tmp_path: Path) -> None:
    target = tmp_path / "a.md"
    target.write_text("# 极限\n\n## 洛必达法则\n\n内容\n", encoding="utf-8")

    parsed = parse_source(target)
    assert parsed.parser_version == "markdown-v1"
    assert parsed.normalized_text.startswith("# 极限")
    # 规范化文本必须以单个换行结尾，便于后续按行遍历。
    assert parsed.normalized_text.endswith("\n")


def test_parse_txt_normalizes_gbk_source(tmp_path: Path) -> None:
    target = tmp_path / "a.txt"
    target.write_bytes("第一章 极限\r\n\r\n\r\n洛必达法则。".encode("gb18030"))

    parsed = parse_source(target)
    assert parsed.parser_version == "text-v1"
    assert "encoding=gb18030" in parsed.diagnostics
    # CRLF 与多余空行都被规范化掉（连续空行最多两行）。
    assert "\r" not in parsed.normalized_text
    assert "\n\n\n\n" not in parsed.normalized_text


def test_parse_docx_reads_paragraphs_and_tables(tmp_path: Path) -> None:
    docx = pytest.importorskip("docx")
    document = docx.Document()
    document.add_heading("极限", level=1)
    document.add_heading("洛必达法则", level=2)
    document.add_paragraph("适用条件是 0/0 型。")
    table = document.add_table(rows=1, cols=2)
    table.cell(0, 0).text = "条件"
    table.cell(0, 1).text = "结论"
    target = tmp_path / "a.docx"
    document.save(str(target))

    parsed = parse_source(target)
    assert parsed.parser_version == "docx-v1"
    assert "# 极限" in parsed.normalized_text
    assert "## 洛必达法则" in parsed.normalized_text
    assert "适用条件是 0/0 型。" in parsed.normalized_text
    assert "条件 | 结论" in parsed.normalized_text


def test_parse_pdf_without_text_layer_raises(tmp_path: Path) -> None:
    """空白/扫描 PDF 提取不到文本时必须明确报错，不能产出空正文。"""
    from pypdf import PdfWriter

    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    target = tmp_path / "blank.pdf"
    with target.open("wb") as handle:
        writer.write(handle)

    with pytest.raises(ScannedPdfError, match="scanned_pdf"):
        parse_source(target)


def test_parse_unknown_suffix_raises(tmp_path: Path) -> None:
    target = tmp_path / "a.csv"
    target.write_text("a,b\n", encoding="utf-8")
    with pytest.raises(ValueError, match="unsupported_type"):
        parse_source(target)


# ------------------------------------------------------- save_upload_streaming


def test_save_upload_streaming_writes_and_hashes(tmp_path: Path) -> None:
    root = tmp_path / "materials"
    root.mkdir(parents=True)
    material_id = uuid4()
    data = "洛必达法则的内容".encode("utf-8")

    stored_path, size, digest = asyncio.run(
        save_upload_streaming(
            FakeUpload("原始资料.MD", data), material_id=material_id, root=root
        )
    )

    assert stored_path == f"{material_id}/source.md"
    assert size == len(data)
    assert digest == hashlib.sha256(data).hexdigest()
    # 正式文件已就位，且临时文件不残留。
    assert (root / str(material_id) / "source.md").read_bytes() == data
    assert not (root / str(material_id) / "source.md.part").exists()


def test_save_upload_streaming_leaves_no_partial_on_failure(tmp_path: Path) -> None:
    root = tmp_path / "materials"
    root.mkdir(parents=True)
    material_id = uuid4()

    with pytest.raises(FileTooLargeError, match="file_too_large"):
        asyncio.run(
            save_upload_streaming(
                FakeUpload("a.md", b"x" * 64),
                material_id=material_id,
                root=root,
                max_bytes=16,
            )
        )

    assert not (root / str(material_id) / "source.md").exists()
    assert not (root / str(material_id) / "source.md.part").exists()


def test_save_upload_streaming_rejects_empty_file(tmp_path: Path) -> None:
    root = tmp_path / "materials"
    root.mkdir(parents=True)

    with pytest.raises(ValueError, match="empty_file"):
        asyncio.run(
            save_upload_streaming(FakeUpload("a.md", b""), material_id=uuid4(), root=root)
        )


def test_save_upload_streaming_closes_upload(tmp_path: Path) -> None:
    root = tmp_path / "materials"
    root.mkdir(parents=True)
    upload = FakeUpload("a.md", "内容".encode("utf-8"))

    asyncio.run(save_upload_streaming(upload, material_id=uuid4(), root=root))
    assert upload.closed is True


def test_upload_and_parse_limits_are_identical() -> None:
    """上传上限必须与解析上限是**同一个值**。

    回归用例：曾经上传 20 MB、解析 5 MB，于是 11 MB 的文件会「上传成功、
    随后异步失败」，而且失败提示说「超过 20 MB」——对一个 11 MB 的文件来说是假话。
    只要这两个常量还能分别调整，这个缺陷就会回来，所以直接断言它们相等。
    """
    from backend.ingestion.source_io import MAX_FILE_BYTES, MAX_SOURCE_BYTES

    assert MAX_UPLOAD_BYTES == MAX_SOURCE_BYTES == MAX_FILE_BYTES
    # 上限必须是正数且不超过 10 MB（解析要把整篇读进内存，10 MB 是本机可接受上限）。
    assert 0 < MAX_FILE_BYTES <= 10 * 1024 * 1024


def test_delete_stored_file_is_idempotent(tmp_path: Path) -> None:
    root = tmp_path / "materials"
    root.mkdir(parents=True)
    material_id = uuid4()

    stored_path, _, _ = asyncio.run(
        save_upload_streaming(FakeUpload("a.md", "内容".encode("utf-8")), material_id=material_id, root=root)
    )
    delete_stored_file(root, stored_path)
    assert not (root / str(material_id)).exists()

    # 重复删除不应抛错，方便上传回滚时无脑调用。
    delete_stored_file(root, stored_path)


def test_delete_stored_file_rejects_escape(tmp_path: Path) -> None:
    root = tmp_path / "materials"
    root.mkdir(parents=True)
    outside = tmp_path / "secret.md"
    outside.write_text("机密", encoding="utf-8")

    with pytest.raises(ValueError, match="unsafe_storage_path"):
        delete_stored_file(root, "../secret.md")
    assert outside.exists()
