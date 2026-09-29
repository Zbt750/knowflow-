"""仅负责一次受限二进制文档解析；不读取模型配置，不接触数据库。"""
import json
import sys
from dataclasses import asdict
from pathlib import Path

from backend.ingestion.document_parsers import DocumentParseError, parse_docx, parse_pdf
from backend.ingestion.source_io import ScannedPdfError


def main() -> None:
    path = Path(sys.argv[1])
    try:
        if path.suffix.lower() == ".docx":
            payload = asdict(parse_docx(path))
        elif path.suffix.lower() == ".pdf":
            payload = asdict(parse_pdf(path))
        else:
            payload = {"error": "document_parse_failed"}
    except ScannedPdfError:
        payload = {"error": "scanned_pdf"}
    except DocumentParseError as error:
        payload = {"error": error.code}
    except Exception:
        payload = {"error": "document_parse_failed"}
    sys.stdout.buffer.write(json.dumps(payload, ensure_ascii=False).encode("utf-8"))


if __name__ == "__main__":
    main()
