"""Cleaned judgment text (sealed collection `judgment_texts`, D-056).

The clerk writes one document per case: the header block and the numbered paragraphs, each with our stable ID
(P1..Pn), the court's own paragraph number where it has one, the page it starts on, and the part of the judgment
it belongs to once routed. It holds the court's reasoning, so it lives in the sealed database: REVIEW reads it
before the first session, the evaluator and reflection after the verdict, and nothing in a session ever does.
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from lexarena.schemas.base import NonEmptyStr, StoredModel

JudgmentPart = Literal[
    "HEADER", "FACTS", "LOWER_ORDER", "ISSUES", "SUBMISSIONS_P", "SUBMISSIONS_R", "ANALYSIS", "CONCLUSION"
]
AGENT_VISIBLE_PARTS: tuple[JudgmentPart, ...] = ("FACTS", "LOWER_ORDER", "ISSUES", "SUBMISSIONS_P", "SUBMISSIONS_R")


class JudgmentParagraph(StoredModel):
    para_id: str = Field(pattern=r"^P[1-9]\d*$")
    court_no: str | None
    page: int = Field(ge=1)
    text: NonEmptyStr
    part: JudgmentPart | None = None


class JudgmentText(StoredModel):
    id: NonEmptyStr = Field(alias="_id")
    source_file: NonEmptyStr
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    header: str
    paragraphs: list[JudgmentParagraph] = Field(min_length=1)
