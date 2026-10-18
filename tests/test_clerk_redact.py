"""Redaction of a stored agent view (D-129): replace a leaked string by the case's own pseudonym or a fixed mask, never
by new content; every string field is covered; the replaced text is never echoed into the flag."""

from __future__ import annotations

import pytest

from lexarena.clerk.names import ADDRESS_MASK
from lexarena.clerk.redact import NAME_MASK, NUMBER_MASK, RedactionError, redact_view
from lexarena.schemas.case import AgentView
from tests.test_clerk_assemble import build, draft


def _view() -> AgentView:
    view: AgentView = build(draft()).view
    assert view is not None
    view.factual_background += " The project IREO Rise sits in Mohali; see O.A. No. 367 of 2022 and a.b@x.com."
    return view


def test_replaces_every_occurrence_with_an_allowed_token() -> None:
    out, touched = redact_view(_view(), [("IREO", "Company-D")], allowed={"Company-D"})
    assert "IREO" not in out.model_dump_json() and "Company-D Rise" in out.factual_background
    assert touched == ["factual_background"]


def test_masks_are_always_allowed() -> None:
    out, _ = redact_view(_view(), [("O.A. No. 367 of 2022", NUMBER_MASK), ("a.b@x.com", ADDRESS_MASK)], allowed=set())
    assert NUMBER_MASK in out.factual_background and ADDRESS_MASK in out.factual_background


def test_new_content_is_refused() -> None:
    with pytest.raises(RedactionError, match="not a pseudonym"):
        redact_view(_view(), [("IREO", "a reputed developer")], allowed={"Company-D"})


def test_a_string_that_does_not_occur_is_refused() -> None:
    with pytest.raises(RedactionError, match="does not occur"):
        redact_view(_view(), [("Gardenia Towers", "Company-D")], allowed={"Company-D"})


def test_a_value_without_letters_is_refused() -> None:
    """Dates and amounts are typed record values; a redaction never touches them."""
    with pytest.raises(RedactionError, match="letter"):
        redact_view(_view(), [("2022", NUMBER_MASK)], allowed=set())


def test_a_project_name_can_be_masked() -> None:
    out, _ = redact_view(_view(), [("IREO Rise", NAME_MASK)], allowed=set())
    assert "IREO" not in out.factual_background and NAME_MASK in out.factual_background
