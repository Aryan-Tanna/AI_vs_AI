"""Provision lookup (CLAUDE.md §6.5) over the current law DB (law_db/, law2db/).

Law DB v2 (verbatim bare text + version history, build step E) does not exist yet. Until then every answer
says so explicitly: the text is an LLM-written summary, and `as_of` is honoured only for the insertion dates
known below. Never present a summary as statutory text.
"""
import ast
import datetime as dt
import json
from dataclasses import dataclass
from pathlib import Path

from lexarena.ingest.normalise import strip_cites
from lexarena.ingest.statute_alias import canon, from_text


def resolve(provision: str) -> tuple[str, str]:
    """Canonical (section_id, full_id) from a canonical ID or plain language ('Section 7 of the IBC')."""
    return from_text(provision) or canon(provision)

# Provisions inserted after the Code/Act came into force: not available before these dates. VERIFY each date
# against the amending instrument before reporting results.
INSERTED_ON = {
    "IBC_2016_SEC_29A": dt.date(2017, 11, 23),     # Insolvency and Bankruptcy Code (Amendment) Ordinance, 2017
    "IBC_2016_SEC_12A": dt.date(2018, 6, 6),       # IBC (Second Amendment) Ordinance, 2018
    "IBC_2016_SEC_238A": dt.date(2018, 6, 6),
    "IBC_2016_SEC_240A": dt.date(2018, 6, 6),
    "IBC_2016_SEC_32A": dt.date(2019, 12, 28),     # IBC (Amendment) Ordinance, 2019
    "IBC_2016_SEC_10A": dt.date(2020, 6, 5),       # IBC (Amendment) Ordinance, 2020
    "IBC_2016_SEC_54A": dt.date(2021, 4, 4),       # pre-packaged insolvency (Ordinance, 2021)
    "COMPANIES_ACT_2013_SEC_212_14A": dt.date(2019, 8, 15),   # Act 22 of 2019 (as stated in an NCLAT judgment)
}

SUMMARY_NOTE = ("LLM-written summary from the law DB, not statutory text; no version history yet (law DB v2 pending). "
                "Check the bare text before quoting it.")


def _parse(v):
    if isinstance(v, str) and v[:1] in "[{":
        try:
            return ast.literal_eval(v)
        except (ValueError, SyntaxError):
            return v
    return v


@dataclass
class ProvisionAnswer:
    provision_id: str
    found: bool
    in_force_on_date: bool | None
    title: str | None = None
    act: str | None = None
    summary: str | None = None
    core_inquiry: str | None = None
    checklist: dict | None = None
    note: str = SUMMARY_NOTE

    def to_dict(self) -> dict:
        return self.__dict__.copy()


class LawStore:
    def __init__(self, entries: list[dict]):
        self.by_id: dict[str, dict] = {}
        for e in entries:
            e = strip_cites(e)
            section, full = canon(e.get("_id") or e.get("statute_id", ""))
            self.by_id.setdefault(section, e)
            self.by_id.setdefault(full, e)

    @classmethod
    def load(cls, root: Path) -> "LawStore":
        entries = []
        for f in sorted(list((root / "law_db").glob("*.json")) + list((root / "law2db").glob("*.json"))):
            entries += json.loads(f.read_text(encoding="utf-8"))
        return cls(entries)

    @staticmethod
    def in_force(provision_id: str, as_of: dt.date) -> bool | None:
        section, full = resolve(provision_id)
        start = INSERTED_ON.get(full) or INSERTED_ON.get(section)
        return None if start is None else as_of >= start

    def get(self, provision_id: str, as_of: dt.date) -> ProvisionAnswer:
        section, full = resolve(provision_id)
        e = self.by_id.get(full) or self.by_id.get(section)
        ans = ProvisionAnswer(full, e is not None, self.in_force(full, as_of))
        if e:
            ans.title, ans.act = e.get("section_title"), e.get("act_name")
            ans.summary, ans.core_inquiry = e.get("statutory_summary"), e.get("core_judicial_inquiry")
            ans.checklist = _parse(e.get("diagnostic_checklist"))
        if ans.in_force_on_date is False:
            ans.note = f"Not in force on {as_of.isoformat()} (inserted {INSERTED_ON.get(full) or INSERTED_ON.get(section)}). " + SUMMARY_NOTE
        return ans
