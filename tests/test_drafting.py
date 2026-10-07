"""Two-model drafting of temporal_overlay rows and predicates into review/ (BUILD_PLAN Step 3, D-041).

Both "models" are fakes returning canned proposals; the source is a registered synthetic PDF of a fictional
Test Act. Nothing here is law.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from lexarena.config import load_config
from lexarena.drafting.draft import DraftingError, draft_overlay, draft_predicate
from lexarena.drafting.review import ReviewError, ReviewStore
from lexarena.drafting.sources import SourceRegistry
from lexarena.llm.client import LLMClient
from lexarena.prompts import PromptStore
from lexarena.schemas.config import AppConfig
from lexarena.schemas.law import LawRecord
from lexarena.secrets import SecretStore
from tests.conftest import CONFIG_V1, PROMPTS_ROOT
from tests.fakes import FakeProvider, text_response
from tests.test_drafting_sources import TEST_TEXT, make_pdf, meta
from tests.test_law_validation import law_record

STATUTE = "TEST_ACT_SEC_99X"
IN_FORCE = {
    "parameter": "section_in_force",
    "value_kind": "boolean",
    "value_number": None,
    "value_boolean": True,
    "value_from": None,
    "value_to": None,
    "value_text": None,
    "keyed_on": "DECISION",
    "effective_from": "2001-06-05",
    "effective_to": None,
    "source_text": "This section shall come into force on the 5th day of June, 2001.",
    "value_quote": "This section shall come into force",
    "effective_from_quote": "on the 5th day of June, 2001",
    "effective_to_quote": None,
    "commencement_note": "<note>",
}


def proposal(*rows: dict[str, Any]) -> str:
    return json.dumps({"rows": list(rows), "no_rows_reason": None if rows else "<none>"})


@pytest.fixture
def cfg() -> AppConfig:
    return load_config(CONFIG_V1)


@pytest.fixture
def registry(tmp_path: Path) -> SourceRegistry:
    reg = SourceRegistry(tmp_path / "sources")
    reg.register(make_pdf(TEST_TEXT), meta())
    return reg


@pytest.fixture
def record() -> LawRecord:
    raw = law_record(STATUTE)
    raw["diagnostic_checklist"]["mandatory_prerequisites"] = ["<prerequisite with a period of thirty days>"]
    return LawRecord.model_validate(raw)


def client(cfg: AppConfig, primary: str, secondary: str) -> tuple[LLMClient, FakeProvider, FakeProvider]:
    names = {m.api_key_env for m in cfg.models.by_role().values()}
    first, second = FakeProvider([text_response(primary)]), FakeProvider([text_response(secondary)])
    by_provider = {
        cfg.models.drafter_primary.provider: first,
        cfg.models.drafter_secondary.provider: second,
    }
    llm = LLMClient(
        cfg,
        SecretStore(env_file=None, environ={n: "k" for n in names}),
        PromptStore(PROMPTS_ROOT),
        providers=by_provider,
        cache=None,
        sleep=lambda _: None,
    )
    return llm, first, second


def run(cfg: AppConfig, registry: SourceRegistry, record: LawRecord, a: str, b: str) -> list[Any]:
    llm, _, _ = client(cfg, a, b)
    return draft_overlay(llm, cfg, PromptStore(PROMPTS_ROOT), record, registry, "TEST_ACT_2001", ["99X"])


# ---------------------------------------------------------------- overlay drafting


def test_agreeing_models_give_one_verified_draft(cfg: AppConfig, registry: SourceRegistry, record: LawRecord) -> None:
    [draft] = run(cfg, registry, record, proposal(IN_FORCE), proposal(IN_FORCE))
    assert draft.agreement == "AGREED" and draft.status == "DRAFT"
    assert draft.blocking_problems == []
    assert {c.name: c.status for c in draft.checks}["source_text"] == "VERIFIED"
    assert draft.reviewer_must_judge  # the legal questions are always handed to the reviewer


def test_disagreement_is_recorded_side_by_side(cfg: AppConfig, registry: SourceRegistry, record: LawRecord) -> None:
    other = {**IN_FORCE, "keyed_on": "DEFAULT"}
    drafts = run(cfg, registry, record, proposal(IN_FORCE), proposal(other))
    assert sorted(d.agreement for d in drafts) == ["PRIMARY_ONLY", "SECONDARY_ONLY"]
    same_param = {**IN_FORCE, "effective_from": "2001-06-06", "effective_from_quote": "on the 5th day of June, 2001"}
    drafts = run(cfg, registry, record, proposal(IN_FORCE), proposal(same_param))
    assert sorted(d.agreement for d in drafts) == ["DISAGREED", "DISAGREED"]
    a, b = drafts
    assert a.conflicts_with == [b.draft_id] and b.conflicts_with == [a.draft_id]


@pytest.mark.parametrize(
    ("change", "problem"),
    [
        ({"source_text": "This section shall come into force on the 6th day of June, 2001."}, "not found verbatim"),
        ({"effective_from": "2001-07-01"}, "not written in its quote"),
        ({"effective_from_quote": None}, "needs a quote"),
        ({"keyed_on": "SOMETHING_ELSE"}, "not in vocabulary.case_date_labels"),
        ({"keyed_on": "FILING"}, "section_in_force must key on DECISION"),
        ({"effective_from": None, "effective_from_quote": None}, "needs an effective_from"),
        ({"parameter": "made_up_parameter"}, "not in vocabulary.overlay_parameters"),
        ({"value_kind": "number", "value_boolean": None, "value_number": 1.0}, "section_in_force needs a boolean"),
    ],
)
def test_unverifiable_rows_carry_blocking_problems(
    cfg: AppConfig, registry: SourceRegistry, record: LawRecord, change: dict[str, Any], problem: str
) -> None:
    row = {**IN_FORCE, **change}
    [draft] = run(cfg, registry, record, proposal(row), proposal(row))
    assert any(problem in p for p in draft.blocking_problems), draft.blocking_problems


def test_number_written_in_words_goes_to_the_reviewer(
    cfg: AppConfig, registry: SourceRegistry, record: LawRecord
) -> None:
    row = {
        **IN_FORCE,
        "parameter": "minimum_default_inr",
        "value_kind": "number",
        "value_boolean": None,
        "value_number": 100000,
        "value_quote": "one lakh rupees",
        "keyed_on": "FILING",
    }
    [draft] = run(cfg, registry, record, proposal(row), proposal(row))
    assert draft.blocking_problems == []
    assert any("not written in digits" in j for j in draft.reviewer_must_judge)


def test_search_terms_must_hit_the_source(cfg: AppConfig, registry: SourceRegistry, record: LawRecord) -> None:
    llm, first, _ = client(cfg, proposal(), proposal())
    with pytest.raises(DraftingError, match="not found"):
        draft_overlay(llm, cfg, PromptStore(PROMPTS_ROOT), record, registry, "TEST_ACT_2001", ["no such words"])
    assert first.requests == []  # no model call is spent on a miss


def test_models_see_only_the_excerpt_and_the_record(
    cfg: AppConfig, registry: SourceRegistry, record: LawRecord
) -> None:
    llm, first, second = client(cfg, proposal(IN_FORCE), proposal(IN_FORCE))
    draft_overlay(llm, cfg, PromptStore(PROMPTS_ROOT), record, registry, "TEST_ACT_2001", ["99X"])
    for fake in (first, second):
        [request] = fake.requests
        text = request.messages[-1].content
        assert "99X" in text and STATUTE in text
        assert "DECISION" in text and "section_in_force" in text  # the vocabulary is shown, not guessed


# ---------------------------------------------------------------- predicate drafting


def predicate_proposal(**change: Any) -> str:
    base = {
        "field": "mandatory_prerequisites",
        "item_index": 0,
        "kind": "DAY_COUNT",
        "inputs": [{"name": "claimed", "source": "claim:mandatory_prerequisites.days"}],
        "open_parameters": [],
        "expression_json": json.dumps({"op": "==", "args": [{"var": "claimed"}, {"const": 30}]}),
        "error_code": "ERR_TIMELINE_MISSTATED",
        "source_text": "within thirty days",
    }
    return json.dumps({"predicates": [{**base, **change}], "no_predicate_reason": None})


def test_predicate_draft_pins_the_law_db_item(cfg: AppConfig, registry: SourceRegistry, record: LawRecord) -> None:
    llm, _, _ = client(cfg, predicate_proposal(), predicate_proposal())
    [draft] = draft_predicate(llm, cfg, PromptStore(PROMPTS_ROOT), record, registry, "TEST_ACT_2001", ["99X"])
    assert draft.agreement == "AGREED" and draft.entry is not None
    assert draft.entry.item_hash == draft.item_hash and len(draft.item_hash) == len("0" * 64)
    assert any("not written in digits" in j for j in draft.reviewer_must_judge)  # "thirty", not 30


@pytest.mark.parametrize(
    ("change", "problem"),
    [
        ({"item_index": 5}, "no item 5"),
        ({"expression_json": json.dumps({"op": ">=", "args": [{"const": 1}, {"const": 2}]})}, "claim: input"),
        ({"expression_json": "{not json"}, "not valid JSON"),
    ],
)
def test_predicate_problems_block(
    cfg: AppConfig, registry: SourceRegistry, record: LawRecord, change: dict[str, Any], problem: str
) -> None:
    llm, _, _ = client(cfg, predicate_proposal(**change), predicate_proposal(**change))
    [draft] = draft_predicate(llm, cfg, PromptStore(PROMPTS_ROOT), record, registry, "TEST_ACT_2001", ["99X"])
    assert any(problem in p for p in draft.blocking_problems), draft.blocking_problems


# ---------------------------------------------------------------- review store


def test_review_store_approve_reject_and_guards(
    cfg: AppConfig, registry: SourceRegistry, record: LawRecord, tmp_path: Path
) -> None:
    store = ReviewStore(tmp_path / "review")
    [good] = run(cfg, registry, record, proposal(IN_FORCE), proposal(IN_FORCE))
    bad_row = {**IN_FORCE, "source_text": "<not in the source>"}
    [bad] = run(cfg, registry, record, proposal(bad_row), proposal(bad_row))
    assert store.save(good) and store.save(bad)
    assert not store.save(good)  # the same draft is not written twice

    with pytest.raises(ReviewError, match="--by"):
        store.approve(good.draft_id, by="")
    with pytest.raises(ReviewError, match="blocking"):
        store.approve(bad.draft_id, by="<reviewer>")
    with pytest.raises(ReviewError, match="reason"):
        store.reject(bad.draft_id, by="<reviewer>", reason="")

    store.approve(good.draft_id, by="<reviewer>")
    store.reject(bad.draft_id, by="<reviewer>", reason="<quote not in source>")
    assert {d.draft_id: d.status for d in store.all()} == {good.draft_id: "APPROVED", bad.draft_id: "REJECTED"}
    with pytest.raises(ReviewError, match="already"):
        store.approve(bad.draft_id, by="<reviewer>")
    reopened = ReviewStore(tmp_path / "review").get(good.draft_id)
    assert reopened.decided_by == "<reviewer>" and reopened.decided_on is not None


def test_a_quote_that_occurs_more_than_once_proves_nothing(cfg: AppConfig, tmp_path: Path, record: LawRecord) -> None:
    """A bare date such as '5th day of June, 2001' may belong to another provision's footnote (D-043)."""
    reg = SourceRegistry(tmp_path / "dup")
    reg.register(
        make_pdf(TEST_TEXT + "\n100Y. Other provision.-Comes into force on the 5th day of June, 2001."), meta()
    )
    llm, _, _ = client(cfg, proposal(IN_FORCE), proposal(IN_FORCE))
    [draft] = draft_overlay(llm, cfg, PromptStore(PROMPTS_ROOT), record, reg, "TEST_ACT_2001", ["99X"])
    assert any("effective_from_quote: quote occurs 2 times" in p for p in draft.blocking_problems)
    found = {c.name: c for c in draft.checks}
    assert found["source_text"].status == "VERIFIED" and "99X" in found["source_text"].detail  # context shown


def test_approve_re_runs_the_checks(
    cfg: AppConfig, registry: SourceRegistry, record: LawRecord, tmp_path: Path
) -> None:
    from lexarena.drafting.loader import recheck

    store = ReviewStore(tmp_path / "review")
    [good] = run(cfg, registry, record, proposal(IN_FORCE), proposal(IN_FORCE))
    store.save(good)
    stale = good.model_copy(update={"row": good.row.model_copy(update={"source_text": "<not in the source>"})})
    rechecked = recheck(stale, registry, cfg.vocabulary, record)
    assert any("not found verbatim" in p for p in rechecked.blocking_problems)


def two_page_pdf() -> bytes:
    import pymupdf

    doc = pymupdf.open()  # type: ignore[no-untyped-call]
    for text in (
        "1[88Z. Another provision.\n1 Ins. by Act 7 of 2000, s. 2 (w.e.f. 1-1-2000).",
        "1[99X. Placeholder provision.-(1) Text.\n1 Ins. by Act 9 of 2001, s. 4 (w.e.f. 5-6-2001).",
    ):
        page = doc.new_page()
        page.insert_textbox(pymupdf.Rect(36, 36, 560, 800), text, fontsize=10)  # type: ignore[no-untyped-call]
    return bytes(doc.tobytes())  # type: ignore[no-untyped-call]


@pytest.mark.parametrize(
    ("footnote", "problem"),
    [
        ("1 Ins. by Act 7 of 2000, s. 2 (w.e.f. 1-1-2000).", "not on the same page"),  # number matches, wrong page
        ("1 Ins. by Act 9 of 2001, s. 4 (w.e.f. 5-6-2001).", None),  # the provision's own footnote
    ],
)
def test_a_footnote_must_sit_on_the_markers_page(
    cfg: AppConfig, tmp_path: Path, record: LawRecord, footnote: str, problem: str | None
) -> None:
    reg = SourceRegistry(tmp_path / "pages")
    reg.register(two_page_pdf(), meta())
    day = "2000-01-01" if "2000" in footnote else "2001-06-05"
    row = {
        **IN_FORCE,
        "source_text": "1[99X. Placeholder provision",
        "value_quote": footnote,
        "effective_from": day,
        "effective_from_quote": footnote,
    }
    llm, _, _ = client(cfg, proposal(row), proposal(row))
    [draft] = draft_overlay(llm, cfg, PromptStore(PROMPTS_ROOT), record, reg, "TEST_ACT_2001", ["99X"])
    if problem is None:
        assert draft.blocking_problems == []
    else:
        assert any(problem in p for p in draft.blocking_problems), draft.blocking_problems


def test_a_footnote_number_must_match_the_marker(cfg: AppConfig, tmp_path: Path, record: LawRecord) -> None:
    reg = SourceRegistry(tmp_path / "num")
    reg.register(make_pdf("2[99X. Placeholder provision.\n1 Ins. by Act 9 of 2001, s. 4 (w.e.f. 5-6-2001)."), meta())
    footnote = "1 Ins. by Act 9 of 2001, s. 4 (w.e.f. 5-6-2001)."
    row = {
        **IN_FORCE,
        "source_text": "2[99X. Placeholder provision",
        "value_quote": footnote,
        "effective_from_quote": footnote,
    }
    llm, _, _ = client(cfg, proposal(row), proposal(row))
    [draft] = draft_overlay(llm, cfg, PromptStore(PROMPTS_ROOT), record, reg, "TEST_ACT_2001", ["99X"])
    assert any("footnote 1 does not match the provision's marker 2" in p for p in draft.blocking_problems)
