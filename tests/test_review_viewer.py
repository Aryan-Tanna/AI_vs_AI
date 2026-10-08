"""The clerk-review viewer's model and tick store (D-056, S-007). Offline; the app itself is smoke-tested in
test_review_viewer_app.py against the real services."""

from __future__ import annotations

from pathlib import Path

from lexarena.schemas.judgment import JudgmentText
from lexarena.ui.review_model import build_page, resolve
from lexarena.ui.ticks import TickStore
from tests import builders

TEXT = "The bank filed on 01.01.2001. The debtor replied. Mr. A. Kumar signed it."


def judgment() -> JudgmentText:
    doc = builders.judgment_text("TESTCASE_0001", "<sentinel>").to_document()
    doc["paragraphs"] = [
        {"para_id": f"P{n}", "court_no": str(n), "page": 1, "text": TEXT if n == 1 else f"<para {n}>", "part": "FACTS"}
        for n in (1, 2, 3)
    ]
    return JudgmentText.model_validate(doc)


def test_sources_resolve_to_the_clerks_own_sentences() -> None:
    j = judgment()
    assert resolve("P1.S1", j).text == "The bank filed on 01.01.2001."
    assert resolve("P1.S3", j).text == "Mr. A. Kumar signed it."  # abbreviations and initials do not split
    assert resolve("P2", j).text == "<para 2>"
    for missing in ("P9", "P1.S9", "P1.Sx"):
        assert not resolve(missing, j).found


def test_page_lists_every_reviewable_item_with_its_sources() -> None:
    page = build_page(builders.case("TESTCASE_0001"), builders.ground_truth("TESTCASE_0001", "<sentinel>"), judgment())
    ids = [i.item_id for i in page.items]
    assert {"F1", "C1", "EX-1", "AM1", "date:FILING", "issue:I1", "finding:I1", "conclusion"} <= set(ids)
    assert len(ids) == len(set(ids))
    f1 = next(i for i in page.items if i.item_id == "F1")
    assert [s.source_id for s in f1.sources] == ["1"] and not f1.sources[0].found  # builder IDs are not P-IDs
    am1 = next(i for i in page.items if i.item_id == "AM1")
    assert [s.source_id for s in am1.sources] == ["1"]  # an amount shows its fact's sources
    assert page.sections()[0] == "Parties" and "Sealed findings" in page.sections()


def test_ticks_persist_and_complete(tmp_path: Path) -> None:
    store = TickStore(tmp_path)
    assert not store.load("C").done(["F1", "F2"])
    store.set("C", "F1", ok=True, by="<owner>")
    store.set("C", "F2", ok=False, by="<owner>", note="<wrong date>")
    reloaded = store.load("C")
    assert reloaded.ticks["F2"].note == "<wrong date>" and not reloaded.done(["F1", "F2"])
    store.set("C", "F2", ok=True, by="<owner>")
    assert store.load("C").done(["F1", "F2"])
    assert not store.load("C").done([])
