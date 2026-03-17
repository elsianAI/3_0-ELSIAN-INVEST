"""PDF text extraction utilities.

Uses pdfplumber (layout=True) for column-preserving extraction.
Falls back to pypdf if pdfplumber is unavailable.
"""

from __future__ import annotations

import re
from io import BytesIO

try:
    import pdfplumber
except Exception:
    pdfplumber = None  # type: ignore[assignment]

try:
    from pypdf import PdfReader
except Exception:
    PdfReader = None  # type: ignore[assignment]


def _extract_with_pdfplumber(source: bytes | str) -> str:
    """Extract text using pdfplumber with layout preservation.

    Args:
        source: PDF bytes or file path string.
    """
    if pdfplumber is None:
        return ""
    try:
        if isinstance(source, bytes):
            pdf = pdfplumber.open(BytesIO(source))
        else:
            pdf = pdfplumber.open(source)
        with pdf:
            chunks: list[str] = []
            for page in pdf.pages:
                page_text = page.extract_text(layout=True) or ""
                page_text = page_text.replace("\r\n", "\n").replace("\r", "\n")
                page_text = re.sub(r"\n{3,}", "\n\n", page_text).strip()
                if page_text:
                    chunks.append(page_text)
            return "\n\n".join(chunks).strip()
    except Exception:
        return ""


def _extract_with_pypdf(content: bytes) -> str:
    """Fallback extraction using pypdf (collapses whitespace)."""
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


def extract_pdf_text(content: bytes) -> str:
    """Extract text from PDF bytes. Returns empty string on failure.

    Prefers pdfplumber (layout=True) for column-preserving extraction.
    Falls back to pypdf if pdfplumber is unavailable or fails.
    """
    text = _extract_with_pdfplumber(content)
    if text:
        return text
    return _extract_with_pypdf(content)


def extract_pdf_text_from_file(path: str) -> str:
    """Extract text from a PDF file path.

    Prefers pdfplumber (layout=True) for column-preserving extraction.
    Falls back to pypdf if pdfplumber is unavailable or fails.
    """
    text = _extract_with_pdfplumber(path)
    if text:
        return text
    try:
        with open(path, "rb") as f:
            return _extract_with_pypdf(f.read())
    except Exception:
        return ""
