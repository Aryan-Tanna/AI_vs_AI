"""Structured outputs the agents must return (validated with pydantic)."""
from typing import Literal

from pydantic import BaseModel, Field

Label = Literal["ALLOWED", "DISMISSED", "PARTLY_ALLOWED", "ALLOWED_REMANDED", "WITHDRAWN", "DISPOSED"]


class Claim(BaseModel):
    kind: Literal["FACT", "DATE", "AMOUNT", "ARITHMETIC", "PROVISION", "AUTHORITY"]
    text: str = Field(description="The claim exactly as asserted, e.g. 'Default occurred on 31.03.2016'")
    record_ref: str | None = Field(None, description="Record section or chronology id relied on, if any")


class Turn(BaseModel):
    prose: str = Field(description="The submission as it would be made to the bench")
    claims: list[Claim] = Field(description="Every factual, date, amount, arithmetic, provision and authority claim in the prose")


class BaselinePrediction(BaseModel):
    label: Label
    appellant_won: bool
    reasons: str = Field(description="Three to six sentences")


class SmokeOutput(BaseModel):
    fact_from_tool: str
    could_read_files: bool = Field(description="True only if you were able to read any file on disk")
