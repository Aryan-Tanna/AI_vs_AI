"""The one place pymupdf (untyped) is called, so the rest of the code stays fully typed."""

from __future__ import annotations

import pymupdf


def pdf_pages_text(data: bytes) -> list[str]:
    """Text layer of each page, in page order; empty strings for pages without one (scans are never OCR'd)."""
    doc = pymupdf.open(stream=data, filetype="pdf")  # type: ignore[no-untyped-call]
    try:
        return [str(page.get_text()) for page in doc.pages()]  # type: ignore[no-untyped-call]
    finally:
        doc.close()  # type: ignore[no-untyped-call]
