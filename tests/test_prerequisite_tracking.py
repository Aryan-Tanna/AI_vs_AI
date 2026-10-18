"""D-135: WARN_PREREQUISITE_UNADDRESSED is judged over the whole hearing, once, at the side's closing. Per turn it
fired on every LEX-D turn of DEV_0008 (a respondent need not argue undisputed prerequisites in each submission)."""

from __future__ import annotations

from typing import Any

from lexarena.config import load_config
from lexarena.storage.temporal import StatuteView
from lexarena.themis_local.audit import PREREQUISITE_UNADDRESSED
from lexarena.themis_local.verify import ThemisLocal
from tests.conftest import CONFIG_V1
from tests.test_layer1 import statute_view
from tests.test_statute_audit import claim

CFG = load_config(CONFIG_V1)
SID = "TEST_ACT_SEC_7"


def item(i: int) -> dict[str, Any]:
    return {"law_index": i, "quote": "<quoted span>", "confidence": 1.0}


def view_with_prerequisites() -> StatuteView:
    v = statute_view(SID)
    dc = v.record.diagnostic_checklist.model_copy(update={"mandatory_prerequisites": ["<first>", "<second>"]})
    return v.model_copy(update={"record": v.record.model_copy(update={"diagnostic_checklist": dc})})


def checker() -> ThemisLocal:
    return ThemisLocal(None, None, CFG, None)  # type: ignore[arg-type]  # only the bookkeeping is exercised


def test_prerequisites_addressed_in_any_turn_count_for_the_hearing() -> None:
    views = {SID: view_with_prerequisites()}
    n = len(views[SID].record.diagnostic_checklist.mandatory_prerequisites)
    assert n >= 1
    t = checker()
    t._note_prerequisites([claim(statute_id=SID, stance="ASSERT_CLAIM", mandatory_prerequisites=[item(0)])])
    t._note_prerequisites(
        [claim(statute_id=SID, stance="ASSERT_CLAIM", mandatory_prerequisites=[item(i) for i in range(1, n)])]
    )
    assert t._unaddressed(views) == []


def test_one_warning_at_closing_for_what_was_never_addressed() -> None:
    views = {SID: view_with_prerequisites()}
    n = len(views[SID].record.diagnostic_checklist.mandatory_prerequisites)
    t = checker()
    t._note_prerequisites([claim(statute_id=SID, stance="ASSERT_CLAIM", mandatory_prerequisites=[])])
    [w] = t._unaddressed(views)
    assert w.code == PREREQUISITE_UNADDRESSED and w.law_indices == list(range(n))


def test_a_statute_only_opposed_is_never_warned() -> None:
    views = {SID: view_with_prerequisites()}
    t = checker()
    t._note_prerequisites([claim(statute_id=SID, stance="INVOKE_BAR", mandatory_prerequisites=[])])
    assert t._unaddressed(views) == []
