"""Precedent record (DATA_FORMATS §2). Frozen format: validated as documented, never reshaped.

`decision_date` is kept as the raw string. Whether a value that is not a plain YYYY-MM-DD date can be
used for the date cut-off is decided at ingestion (Step 4, Q-008); here it is only reported.
"""

from __future__ import annotations

import re
from datetime import date

from pydantic import Field

from lexarena.schemas.base import FrozenFormatModel

DOCUMENTED_FORUMS = frozenset({"NCLT", "NCLAT"})
DOCUMENTED_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")  # DATA_FORMATS §2: DATE (YYYY-MM-DD)


class PrecedentRecord(FrozenFormatModel):
    precedent_id: str = Field(min_length=1)
    case_title: str
    appeal_number: str
    forum: str
    bench: str
    decision_date: str
    final_order: str
    is_overruled: bool
    statutes_cited: list[str]
    material_facts: str
    legal_issues: str
    ratio_decidendi: str
    operative_order: str
    summary: str

    def parsed_decision_date(self) -> date | None:
        """The decision date if the stored value is exactly YYYY-MM-DD, else None (never guessed).

        `date.fromisoformat` alone also accepts "20200101" and week dates such as "2020-W01".
        """
        if not DOCUMENTED_DATE.fullmatch(self.decision_date):
            return None
        try:
            return date.fromisoformat(self.decision_date)
        except ValueError:
            return None

    def format_issues(self) -> list[tuple[str, str]]:
        """(kind, offending value) for values that are well-typed but outside the documented shape."""
        issues = [("undocumented field", path) for path in self.undocumented_fields()]
        if self.parsed_decision_date() is None:
            issues.append(("decision_date is not YYYY-MM-DD", self.decision_date))
        if self.forum not in DOCUMENTED_FORUMS:
            issues.append((f"forum is not one of {sorted(DOCUMENTED_FORUMS)}", self.forum))
        return issues
