"""PDF text extraction utilities.

Extracted from scripts/runners/sec_fetcher_v2_runner.py.
No pipeline dependencies.
"""

from __future__ import annotations

import re
from io import BytesIO

try:
    from pypdf import PdfReader
except Exception:
    PdfReader = None  # type: ignore[assignment]


def extract_pdf_text(content: bytes) -> str:
    """Extract text from PDF bytes. Returns empty string on failure."""
    if PdfReader is None:
        return ""
    try:
        reader = PdfReader(BytesIO(content))
        chunks: list[str] = []
        for page in reader.pages:
            page_text = page.extract_text() or ""
            page_text = page_text.replace("\r\n", "\n").replace("\r", "\n")
            page_text = re.sub(r"[ \t]+", " ", page_text)
            page_text = re.sub(r"\n{3,}", "\n\n", page_text).strip()
            if page_text:
                chunks.append(page_text)
        return "\n\n".join(chunks).strip()
    except Exception:
        return ""


def extract_pdf_text_from_file(path: str) -> str:
    """Extract text from a PDF file path."""
    try:
        with open(path, "rb") as f:
            return extract_pdf_text(f.read())
    except Exception:
        return ""
