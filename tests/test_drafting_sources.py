"""Legal source registry and the mechanical checks every drafted quote must pass (D-041).

The PDF is generated here from a fictional "Test Act"; its wording is a placeholder, not law.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pymupdf
import pytest

from lexarena.drafting.sources import (
    SourceError,
    SourceIntegrityError,
    SourceMeta,
    SourceRegistry,
    dates_mentioned,
    excerpts,
    find_quote,
    normalize,
    numbers_mentioned,
)

TEST_TEXT = (
    "THE TEST ACT, 2001\n99X. Placeholder provision.\N{EM DASH}(1) This section shall come into force "
    "on the 5th day of June, 2001.\n(2) The minimum amount of default shall be one lakh rupees or "
    "Rs. 1,00,000, whichever the Central Gov-\nernment may by notification specify, within thirty days."
)


def make_pdf(text: str) -> bytes:
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_textbox(pymupdf.Rect(36, 36, 560, 800), text, fontsize=10)
    return doc.tobytes()


def meta(source_id: str = "TEST_ACT_2001") -> SourceMeta:
    return SourceMeta(
        source_id=source_id,
        title="<The Test Act, 2001>",
        issuer="<placeholder issuer>",
        reference="<Act No. 0 of 2001>",
        issued_on=date(2001, 1, 1),
        url="https://example.invalid/test-act.pdf",
    )


# ---------------------------------------------------------------- normalisation and quotes


def test_normalize_is_declared_and_small() -> None:
    assert normalize("a \n\t b") == "a b"
    assert normalize("\N{LATIN SMALL LIGATURE FI}le") == "file"  # ligature (NFKC)
    assert (
        normalize(
            "\N{LEFT DOUBLE QUOTATION MARK}quoted\N{RIGHT DOUBLE QUOTATION MARK} "
            "\N{LEFT SINGLE QUOTATION MARK}x\N{RIGHT SINGLE QUOTATION MARK}"
        )
        == "\"quoted\" 'x'"
    )
    assert normalize("pro\N{SOFT HYPHEN}vision") == "provision"  # soft hyphen
    assert normalize("a\N{EM DASH}b \N{EN DASH} c") == "a-b - c"


def test_line_break_hyphens_match_joined_or_hyphenated() -> None:
    assert find_quote("the Central Government may", "the Central Gov-\nernment may")
    assert find_quote("a pre-existing dispute", "a pre-\nexisting dispute")
    assert find_quote("the Central Gov ernment", "the Central Gov-\nernment") is None


def test_find_quote_tolerates_layout_but_not_wording() -> None:
    span = find_quote("shall come into force on the 5th day of June, 2001.", TEST_TEXT)
    assert span is not None and span[0] < span[1]
    assert find_quote("shall come into force on the 6th day of June, 2001.", TEST_TEXT) is None
    assert find_quote("", TEST_TEXT) is None


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("on the 5th day of June, 2001", date(2001, 6, 5)),
        ("dated 05.06.2001", date(2001, 6, 5)),
        ("June 5, 2001", date(2001, 6, 5)),
        ("5 June 2001", date(2001, 6, 5)),
        ("25th March, 2020", date(2020, 3, 25)),
        ("[13th March, 2020.]", date(2020, 3, 13)),
    ],
)
def test_dates_mentioned(text: str, expected: date) -> None:
    assert expected in dates_mentioned(text)


def test_dates_mentioned_ignores_impossible_dates() -> None:
    assert dates_mentioned("31.02.2020") == set()


def test_numbers_mentioned_reads_indian_grouping() -> None:
    found = numbers_mentioned("Rs. 1,00,000 or Rs. 1,00,00,000 within 30 days")
    assert {100000, 10000000, 30} <= found


def test_excerpts_window_around_search_terms() -> None:
    hits = excerpts(TEST_TEXT, ["99X"], window_chars=60, max_excerpts=3)
    assert len(hits) == 1 and "99X" in hits[0]
    assert excerpts(TEST_TEXT, ["no such term"], window_chars=60, max_excerpts=3) == []
    many = excerpts("1 xxxxxxxx 1 xxxxxxxx 1", ["1"], window_chars=2, max_excerpts=2)
    assert len(many) == 2


# ---------------------------------------------------------------- registry


def test_register_extracts_text_and_pins_hashes(tmp_path: Path) -> None:
    registry = SourceRegistry(tmp_path)
    source = registry.register(make_pdf(TEST_TEXT), meta())
    assert source.page_chars and source.page_chars[0] > 0
    assert len(source.file_sha256) == len(source.text_sha256) == len("0" * 64)
    assert find_quote("whichever the Central Government may by notification specify", registry.text("TEST_ACT_2001"))
    reopened = SourceRegistry(tmp_path)
    assert reopened.get("TEST_ACT_2001") == source


def test_registry_refuses_duplicates_and_textless_pdfs(tmp_path: Path) -> None:
    registry = SourceRegistry(tmp_path)
    pdf = make_pdf(TEST_TEXT)
    registry.register(pdf, meta())
    with pytest.raises(SourceError, match="already registered"):
        registry.register(make_pdf(TEST_TEXT + " "), meta())
    with pytest.raises(SourceError, match="same file"):
        registry.register(pdf, meta("TEST_ACT_2001_COPY"))
    blank = pymupdf.open()
    blank.new_page()
    with pytest.raises(SourceError, match="no text layer"):
        registry.register(blank.tobytes(), meta("TEST_BLANK"))


@pytest.mark.parametrize("target", ["text", "pdf"])
def test_changed_source_files_are_detected(tmp_path: Path, target: str) -> None:
    registry = SourceRegistry(tmp_path)
    source = registry.register(make_pdf(TEST_TEXT), meta())
    path = tmp_path / (source.text_file if target == "text" else source.file)
    path.write_bytes(path.read_bytes() + b" ")
    with pytest.raises(SourceIntegrityError, match="TEST_ACT_2001"):
        SourceRegistry(tmp_path).text("TEST_ACT_2001")
