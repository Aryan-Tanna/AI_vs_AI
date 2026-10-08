"""Clerk steps 1-2 (BUILD_PLAN Step 6, SPEC H5 rule 1, A5): page-furniture removal, encoding repair and
paragraph splitting. Deterministic, no model calls. Placeholder text only (non-negotiable 1).
"""

from __future__ import annotations

from lexarena.clerk.text import SplitText, clean_pages, split_paragraphs

SHARE = 0.5
HEADINGS = ["JUDGMENT", "ORDER", "J U D G M E N T"]


def sp(pages: list[str], jump: int, running: int) -> SplitText:
    return split_paragraphs(clean_pages(pages, SHARE), HEADINGS, max_number_jump=jump, running_text_min_chars=running)


def page(n: int, body: str) -> str:
    return f"<Source title> on 1 January, 2001\n{body}\n<Site> - http://x/doc/123/ {n}"


def test_lines_repeated_across_pages_are_removed_even_with_page_numbers() -> None:
    cleaned = clean_pages([page(1, "<body one>"), page(2, "<body two>"), page(3, "<body three>")], SHARE)
    texts = [line.text for line in cleaned.lines]
    assert texts == ["<body one>", "<body two>", "<body three>"]
    assert cleaned.removed_furniture == 6


def test_a_line_on_too_few_pages_is_kept() -> None:
    pages = ["<a>\n<only here>", "<a>\n<b>", "<a>\n<c>", "<a>\n<d>"]
    texts = [line.text for line in clean_pages(pages, SHARE).lines]
    assert "<only here>" in texts and "<a>" not in texts


def test_a_single_page_document_loses_nothing() -> None:
    cleaned = clean_pages(["<title>\n<body>\n<footer> 1"], SHARE)
    assert [line.text for line in cleaned.lines] == ["<title>", "<body>", "<footer> 1"]


def test_mojibake_is_repaired_and_flagged() -> None:
    cleaned = clean_pages(["Employeesâ€™ fund\n<plain>"], SHARE)
    assert cleaned.lines[0].text == "Employees" + chr(0x2019) + " fund"
    assert [f.code for f in cleaned.flags] == ["ENCODING_ERROR"] and "repaired 1" in cleaned.flags[0].detail


def test_unrepairable_characters_are_flagged_not_guessed() -> None:
    cleaned = clean_pages(["<name> " + chr(0xFFFD) + "APPELLANT"], SHARE)
    assert chr(0xFFFD) in cleaned.lines[0].text
    assert cleaned.flags[0].code == "ENCODING_ERROR" and "unrepairable 1" in cleaned.flags[0].detail


def test_pages_are_tracked() -> None:
    cleaned = clean_pages(["<first page line>", "<second page line>"], SHARE)
    assert [(line.page, line.text) for line in cleaned.lines] == [(1, "<first page line>"), (2, "<second page line>")]


def body(*lines: str) -> list[str]:
    return ["<court name>", "1. <party list item, not a paragraph>", "JUDGMENT", *lines]


def test_header_ends_at_the_first_heading_and_its_numbered_lines_are_not_paragraphs() -> None:
    split = sp(["\n".join(body("1. <first>", "2. <second>"))], 1, 99)
    assert "<party list item" in split.header
    assert [(p.para_id, p.court_no, p.text) for p in split.paragraphs] == [
        ("P1", "1", "<first>"),
        ("P2", "2", "<second>"),
    ]


def test_out_of_sequence_numbers_stay_inside_the_paragraph() -> None:
    text = "\n".join(body("1. <a>", "2. <b> quoting:", "45. <quoted paragraph of another judgment>", "3. <c>"))
    paras = sp([text], 1, 99).paragraphs
    assert [p.court_no for p in paras] == ["1", "2", "3"]
    assert "45. <quoted paragraph" in paras[1].text


def test_text_before_the_first_number_is_its_own_paragraph() -> None:
    paras = sp(["\n".join(body("<unnumbered opening>", "2. <next>"))], 1, 99)
    assert [(p.court_no, p.text) for p in paras.paragraphs] == [(None, "<unnumbered opening>"), ("2", "<next>")]


def test_spaced_heading_is_recognised() -> None:
    split = sp(["<court>\nJ U D G M E N T\n1. <a>"], 1, 99)
    assert split.header == "<court>" and split.paragraphs[0].text == "<a>"


def test_without_a_heading_everything_is_body() -> None:
    split = sp(["1. <a>\n2. <b>"], 1, 99)
    assert split.header == "" and [p.court_no for p in split.paragraphs] == ["1", "2"]


def test_continuation_lines_join_with_spaces_and_pages_follow_the_start() -> None:
    split = sp(["JUDGMENT\n1. <starts>\n<continues>", "<still going>\n2. <next>"], 1, 99)
    first, second = split.paragraphs
    assert first.text == "<starts> <continues> <still going>" and first.page == 1
    assert second.page == 2


def test_a_heading_merged_into_a_line_still_ends_the_header() -> None:
    text = "<court>\n<appeal number> J U D G M EN T (<date>) <member> This appeal\n<continues>\n2. <next>"
    split = sp([text], 2, 99)
    assert split.header == "<court>\n<appeal number>"
    assert split.paragraphs[0].text == "(<date>) <member> This appeal <continues>"
    assert split.paragraphs[1].court_no == "2"


def test_a_whole_line_heading_wins_over_an_embedded_one() -> None:
    text = "<ARISING OUT OF JUDGMENT DATED>\n<court>\nJUDGMENT\n1. <a>"
    split = sp([text], 2, 99)
    assert split.header == "<ARISING OUT OF JUDGMENT DATED>\n<court>" and split.paragraphs[0].text == "<a>"


def test_lower_case_words_are_never_headings() -> None:
    split = sp(["the impugned judgment was passed\n1. <a>"], 2, 99)
    assert split.header == ""


def test_a_small_skip_in_the_court_numbering_is_followed_and_flagged() -> None:
    text = "JUDGMENT\n1. <a>\n2. <b>\n4. <d, the court skipped 3>\n5. <e>"
    split = sp([text], 2, 99)
    assert [p.court_no for p in split.paragraphs] == ["1", "2", "4", "5"]
    assert [f.code for f in split.flags] == ["PARAGRAPH_NUMBERING_GAP"] and "2 -> 4" in split.flags[0].detail


def test_a_big_jump_is_a_quotation_not_a_paragraph() -> None:
    text = "JUDGMENT\n1. <a>\n2. <b> quoting:\n45. <quoted>\n3. <c>"
    split = sp([text], 2, 99)
    assert [p.court_no for p in split.paragraphs] == ["1", "2", "3"] and split.flags == []


def test_a_running_footer_merged_into_body_text_is_removed() -> None:
    footer = "Company Appeal (AT) No. 77 of 2001"
    pages = [
        f"<court>\n{footer}\nJUDGMENT\n1. <a> start",
        f"<more a> {footer} <still a>\n2. <b>",
        f"<b> continues {footer.replace(' No.', chr(10) + 'No.')} <end b>",
    ]
    split = sp(pages, 1, 20)
    assert all("Company Appeal" not in p.text for p in split.paragraphs)
    assert split.paragraphs[0].text == "<a> start <more a> <still a>"
    assert split.paragraphs[1].text == "<b> <b> continues <end b>"
    assert [f.code for f in split.flags] == ["RUNNING_TEXT_REMOVED"]


def test_a_header_line_mentioned_once_in_the_body_stays() -> None:
    pages = ["<court>\nCompany Appeal (AT) No. 77 of 2001\nJUDGMENT\n1. <a> see Company Appeal (AT) No. 77 of 2001"]
    split = sp(pages, 1, 20)
    assert "Company Appeal (AT) No. 77 of 2001" in split.paragraphs[0].text and split.flags == []


def test_a_euro_sign_before_an_indian_grouped_number_is_a_rupee_sign() -> None:
    cleaned = clean_pages(["claim of €1,54,64,626/- and a fee of € 2,500"], SHARE)
    assert cleaned.lines[0].text == "claim of ₹1,54,64,626/- and a fee of € 2,500"
    assert any("rupee" in f.detail for f in cleaned.flags)
