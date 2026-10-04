"""Research tools for advocates and judges: authority search, provision lookup, authority status, rule engine.

Every tool is built per case with the case's cutoff, law date and retrieval exclusions fixed inside it; the
agent cannot pass a later date or switch a filter off (CLAUDE.md §8.0).
"""
import datetime as dt
import json

from claude_agent_sdk import tool

from lexarena.law.provisions import resolve
from lexarena.rules import (Acknowledgment, limitation, minimum_default, sec9_filing_window, sec10a_bar,
                            sec61_appeal, sec62_appeal)
from lexarena.services import Services


def _text(obj) -> dict:
    return {"content": [{"type": "text", "text": obj if isinstance(obj, str) else json.dumps(obj, ensure_ascii=False, indent=1, default=str)}]}


def _err(msg: str) -> dict:
    return {**_text(msg), "is_error": True}


def _date(s: str | None) -> dt.date | None:
    return dt.date.fromisoformat(s) if s else None


def make_research_tools(law_as_of: dt.date, services: Services, exclude: set[str]) -> dict:
    cutoff = law_as_of + dt.timedelta(days=1)

    @tool("search_authorities",
          "Search NCLAT precedents decided before this appeal. Returns propositions/issues with case title, date, "
          "outcome and any treatment warning. Supreme Court landmarks are checked with authority_status.",
          {"type": "object", "properties": {
              "query": {"type": "string", "description": "What the authority should say"},
              "provisions": {"type": "array", "items": {"type": "string"}, "description": "e.g. ['Section 18 of the Limitation Act']"},
              "k": {"type": "integer", "minimum": 1, "maximum": 10}},
           "required": ["query"]})
    async def search_authorities(args):
        if services.index is None:
            return _err("Reference DB not built; run python -m lexarena.ingest.build_reference")
        provs = tuple(resolve(p)[0] for p in args.get("provisions") or [])
        hits = services.index.search(args["query"], cutoff=cutoff, exclude=exclude, provisions=provs, k=int(args.get("k") or 6))
        return _text([{k: v for k, v in h.to_dict().items() if k != "case_uid"} for h in hits] or "No authorities found.")

    @tool("get_provision", "Look up a provision as in force on the date of this appeal (summary, checklist, in-force status).",
          {"type": "object", "properties": {"provision": {"type": "string", "description": "e.g. 'Section 7 of the IBC' or IBC_2016_SEC_7"}},
           "required": ["provision"]})
    async def get_provision(args):
        return _text(services.law.get(args["provision"], law_as_of).to_dict())

    @tool("authority_status", "Check whether an authority exists in the authority sources and was decided before this appeal.",
          {"type": "object", "properties": {"title": {"type": "string"},
                                            "court": {"type": "string", "enum": ["SC", "NCLAT", "OTHER"]}},
           "required": ["title"]})
    async def authority_status(args):
        st = services.authorities.status(args["title"], cutoff, args.get("court"))
        d = st.to_dict()
        if st.anachronistic:
            d = {"found": True, "title": st.title, "usable": False, "reason": "decided on or after the date of this appeal"}
        return _text(d)

    def rule_tool(name: str, desc: str, props: dict, required: list[str], fn):
        @tool(name, desc, {"type": "object", "properties": props, "required": required})
        async def _t(args):
            try:
                return _text(fn(args).to_dict())
            except (ValueError, TypeError) as e:
                return _err(f"bad input: {e}")
        return _t

    D = {"type": "string", "description": "YYYY-MM-DD"}
    rules = {
        "rules_limitation": rule_tool(
            "rules_limitation", "Article 137 limitation for a s.7/s.9 application with s.18/s.19 acknowledgments and the COVID exclusion.",
            {"default_date": D, "filing_date": D, "acknowledgment_dates": {"type": "array", "items": D}},
            ["default_date"],
            lambda a: limitation(_date(a["default_date"]), _date(a.get("filing_date")),
                                 [Acknowledgment(_date(x)) for x in a.get("acknowledgment_dates") or []])),
        "rules_appeal_timeline": rule_tool(
            "rules_appeal_timeline", "s.61(2) (30+15 days) or s.62 (45+15 days) appeal limitation from pronouncement.",
            {"order_date": D, "filing_date": D, "section": {"type": "string", "enum": ["61", "62"]},
             "certified_copy_applied": D, "certified_copy_ready": D},
            ["order_date"],
            lambda a: (sec62_appeal if a.get("section") == "62" else sec61_appeal)(
                _date(a["order_date"]), _date(a.get("filing_date")),
                certified_copy_applied=_date(a.get("certified_copy_applied")), certified_copy_ready=_date(a.get("certified_copy_ready")))),
        "rules_sec9_notice": rule_tool(
            "rules_sec9_notice", "s.8/s.9: earliest filing date after delivery of the demand notice.",
            {"delivery_date": D, "filing_date": D}, ["delivery_date"],
            lambda a: sec9_filing_window(_date(a["delivery_date"]), _date(a.get("filing_date")))),
        "rules_sec10a": rule_tool(
            "rules_sec10a", "s.10A bar for defaults between 25.03.2020 and 24.03.2021.",
            {"default_dates": {"type": "array", "items": D}}, ["default_dates"],
            lambda a: sec10a_bar([_date(x) for x in a["default_dates"]])),
        "rules_threshold": rule_tool(
            "rules_threshold", "s.4 minimum default in force on the filing date.",
            {"filing_date": D, "amount_in_default_inr": {"type": "number"}}, ["filing_date"],
            lambda a: minimum_default(_date(a["filing_date"]), a.get("amount_in_default_inr"))),
    }
    return {"search_authorities": search_authorities, "get_provision": get_provision,
            "authority_status": authority_status, **rules}
