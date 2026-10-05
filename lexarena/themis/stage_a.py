"""THEMIS-LOCAL Stage A: deterministic checks of a ClaimSet against the record, the rule engine, the law DB and
the authority registry (CLAUDE.md §8.3). No LLM. Pass/fail with error codes; never judges legal merit.

Error codes: ERR_FACT_MISMATCH, ERR_ARITHMETIC, ERR_PROVISION_NOT_IN_FORCE, ERR_UNVERIFIED_AUTHORITY,
ERR_ANACHRONISTIC_AUTHORITY. Notes (not failures) are returned separately: record conflicts, unverifiable
facts, authority treatment warnings, provisions missing from the law DB.
"""
import datetime as dt
import re
from dataclasses import dataclass, field

from lexarena.law.provisions import resolve
from lexarena.rules import (Acknowledgment, limitation, minimum_default, sec9_filing_window, sec10a_bar,
                            sec61_appeal, sec62_appeal)
from lexarena.schemas.public_case import PublicUnspoiled
from lexarena.themis.claims import Claim, ClaimSet
from lexarena.themis.local import Finding


@dataclass
class StageAResult:
    findings: list[Finding] = field(default_factory=list)
    notes: list[dict] = field(default_factory=list)


def _mentions(text: str, d) -> bool:
    """Does the claim text state this date (dd.mm.yyyy, dd/mm/yyyy, dd-mm-yyyy or ISO)?"""
    if not isinstance(d, dt.date):
        try:
            d = dt.date.fromisoformat(str(d))
        except ValueError:
            return False
    forms = {d.isoformat(), d.strftime("%d.%m.%Y"), d.strftime("%d/%m/%Y"), d.strftime("%d-%m-%Y")}
    return any(f in text for f in forms)


def _show(v):
    return [_show(x) for x in v] if isinstance(v, list) else (v.isoformat() if isinstance(v, dt.date) else v)


def _same(a, b) -> bool:
    """Numbers compare by value (482000000 == 482000000.0); dates and strings by their ISO/str form."""
    if isinstance(a, (int, float)) and not isinstance(a, bool):
        try:
            return abs(float(a) - float(b)) < 0.5
        except (TypeError, ValueError):
            return False
    return str(a) == str(b)


class StageA:
    def __init__(self, case: PublicUnspoiled, law, authorities, mode: str = "eval"):
        """`law` has get(provision, as_of); `authorities` has status(title, cutoff, court): a SourceRegistry's
        .law/.authorities, or LawStore/AuthorityRegistry directly. In live mode an authority missing from every
        local source may come from the web, so it is noted as unverified instead of failing."""
        self.case, self.law, self.authorities, self.mode = case, law, authorities, mode
        self.facts = case.typed_facts.all_facts()
        self.events = {e.id: e for e in case.chronology}
        self.documents = {d.id: d for d in case.record_documents}
        self.cutoff = case.law_as_of + dt.timedelta(days=1)      # authorities must be decided before the decision date

    def run(self, claims: ClaimSet | dict) -> StageAResult:
        cs = claims if isinstance(claims, ClaimSet) else ClaimSet.model_validate(claims)
        out = StageAResult()
        for c in cs.claims:
            for check in (self._record_ref, self._fact, self._day_count, self._computation, self._provision, self._authority):
                check(c, out)
        return out

    # -- record grounding ------------------------------------------------------------------------------------
    def _record_ref(self, c: Claim, out: StageAResult) -> None:
        """A claim that cites the record must cite something that exists: an invented exhibit or event is a
        deterministic failure. Facts with no reference at all are left to Stage B (record support)."""
        if not c.record_ref:
            return
        refs = re.findall(r"\b[ED]\d+\b", c.record_ref.upper())      # "E4, D2" / "E4 and D2" -> [E4, D2]
        unknown = [r for r in refs if r not in self.events and r not in self.documents]
        if not refs:
            return
        if unknown:
            out.findings.append(Finding("ERR_UNKNOWN_RECORD_REF", c.text,
                                        f"{', '.join(unknown)} not a chronology event or record document in this record", "A"))

    # -- record facts --------------------------------------------------------------------------------------
    def _fact(self, c: Claim, out: StageAResult) -> None:
        asserted = c.date if c.date is not None else c.amount_inr
        if asserted is None:
            return
        if c.fact_key:
            f = self.facts.get(c.fact_key)
            if f is None or (f.value is None and not f.values):
                out.notes.append({"claim": c.id, "note": f"{c.fact_key} is not on the record; cannot verify"})
                return
            allowed = f.values if f.conflict else [f.value]
            if not any(_same(asserted, v) for v in allowed):
                if c.date is not None and any(_mentions(c.text, v) for v in allowed):
                    out.notes.append({"claim": c.id, "note": f"{c.fact_key} stated correctly; {c.date.isoformat()} is a derived date"})
                    return
                out.findings.append(Finding("ERR_FACT_MISMATCH", c.text, f"record {c.fact_key} = {_show(allowed)}", "A"))
            elif f.conflict:
                out.notes.append({"claim": c.id, "note": f"record conflict on {c.fact_key}: {f.values}; asserted value is one of them"})
        elif c.record_ref and c.record_ref in self.events and c.date is not None:
            e = self.events[c.record_ref]
            if _mentions(e.event, c.date):
                return                                  # the event's text states this date (e.g. "fixing default as 27.09.2019")
            if e.date and _mentions(c.text, e.date) and e.date != c.date:
                return                                  # the event's own date is stated; c.date is derived from it
            if e.date and e.date_precision == "DAY" and e.date != c.date:
                out.findings.append(Finding("ERR_FACT_MISMATCH", c.text, f"{e.id} is dated {e.date.isoformat()}: {e.event}", "A"))
            elif e.date and e.date_to and not (e.date <= c.date <= e.date_to):
                out.findings.append(Finding("ERR_FACT_MISMATCH", c.text,
                                            f"{e.id} lies between {e.date.isoformat()} and {e.date_to.isoformat()}", "A"))

    def _day_count(self, c: Claim, out: StageAResult) -> None:
        if c.kind != "DAY_COUNT" or None in (c.date_from, c.date_to, c.days):
            return
        if not re.search(rf"(?<![\d,]){c.days:,}(?![\d,])|(?<!\d){c.days}(?!\d)", c.text):
            out.notes.append({"claim": c.id, "note": "day count not stated in the claim text (e.g. a period in years); not checked"})
            return
        actual = (c.date_to - c.date_from).days
        if c.days != actual:
            out.findings.append(Finding("ERR_ARITHMETIC", c.text,
                                        f"{c.date_from.isoformat()} to {c.date_to.isoformat()} is {actual} days", "A"))

    # -- computations: redo with the rule engine -------------------------------------------------------------
    def _computation(self, c: Claim, out: StageAResult) -> None:
        k = c.computation
        if c.kind != "COMPUTATION" or k is None:
            return
        res, accepted_dates, outcome_map = None, set(), {}
        filled = self._fill_from_record(k)
        if filled:
            out.notes.append({"claim": c.id, "note": f"inputs taken from the record: {', '.join(filled)}"})
        try:
            if k.rule == "ART137_LIMITATION" and k.default_date:
                acks = [Acknowledgment(d) for d in k.acknowledgment_dates]
                res = limitation(k.default_date, k.filing_date, acks, covid=True)
                # Both the plain three-year end date and the COVID-extended one are correct arithmetic; the
                # exclusion is a legal extension on top. A wrong conclusion is still caught by the outcome check.
                accepted_dates = {res.value, limitation(k.default_date, k.filing_date, acks, covid=False).value}
                outcome_map = {"WITHIN_LIMITATION": "WITHIN", "BARRED": "BARRED"}
            elif k.rule in ("SEC61_APPEAL", "SEC62_APPEAL") and k.order_date:
                res = (sec61_appeal if k.rule == "SEC61_APPEAL" else sec62_appeal)(k.order_date, k.filing_date)
                accepted_dates = {res.value}
                outcome_map = {"WITHIN_PERIOD": "IN_TIME", "CONDONABLE": "CONDONABLE", "BEYOND_CONDONABLE_LIMIT": "BEYOND_LIMIT"}
            elif k.rule == "SEC9_NOTICE" and k.delivery_date:
                res = sec9_filing_window(k.delivery_date, k.filing_date)
                accepted_dates = {res.value}
                outcome_map = {"FILED_AFTER_PERIOD": "IN_TIME", "PREMATURE": "PREMATURE"}
            elif k.rule == "SEC10A_BAR" and k.default_date:
                res = sec10a_bar([k.default_date])
                outcome_map = {"BARRED": "BARRED", "NOT_BARRED": "WITHIN"}
            elif k.rule == "SEC4_THRESHOLD" and k.filing_date:
                res = minimum_default(k.filing_date, k.amount_inr)
                outcome_map = {"MET": "MET", "NOT_MET": "NOT_MET"}
        except ValueError as e:
            out.notes.append({"claim": c.id, "note": f"could not recompute: {e}"})
            return
        if res is None:
            out.notes.append({"claim": c.id, "note": f"{k.rule}: inputs missing; not recomputed"})
            return
        expected = outcome_map.get(res.status)
        same = {"IN_TIME": "WITHIN", "BEYOND_LIMIT": "BARRED"}      # the extractor mixes appeal and limitation wording
        if k.asserted_outcome and expected and same.get(k.asserted_outcome, k.asserted_outcome) != same.get(expected, expected):
            out.findings.append(Finding("ERR_ARITHMETIC", c.text, f"rule engine: {res.status} ({'; '.join(res.steps[-2:])})", "A"))
        if k.asserted_date and accepted_dates and k.asserted_date not in accepted_dates:
            out.findings.append(Finding("ERR_ARITHMETIC", c.text,
                                        f"rule engine computes {sorted(d.isoformat() for d in accepted_dates)}", "A"))
        if res.for_bench:
            out.notes.append({"claim": c.id, "for_bench": res.for_bench})

    def _fill_from_record(self, k) -> list[str]:
        """Inputs the extractor left out are taken from the record's typed facts (single values only)."""
        def val(key):
            f = self.facts.get(key)
            if f is None or f.conflict or f.value is None:
                return None
            if isinstance(f.value, dt.date):
                return f.value
            try:
                return dt.date.fromisoformat(str(f.value))       # typed facts keep ISO dates as strings
            except ValueError:
                return None
        filled = []
        for attr, key in (("default_date", "date_of_default"), ("filing_date", "nclt_filing_date"),
                          ("order_date", "impugned_order_date"), ("delivery_date", "demand_notice_delivery")):
            if getattr(k, attr) is None and val(key) is not None:
                setattr(k, attr, val(key))
                filled.append(attr)
        # Acknowledgments are never filled in: "without an acknowledgment, limitation expired on X" is a
        # legitimate hypothetical and must be recomputed as stated.
        return filled

    # -- provisions and authorities ---------------------------------------------------------------------------
    def _provision(self, c: Claim, out: StageAResult) -> None:
        if not c.provision:
            return
        section, full = resolve(c.provision)
        ans = self.law.get(full, self.case.law_as_of)
        if ans.in_force_on_date is False:
            out.findings.append(Finding("ERR_PROVISION_NOT_IN_FORCE", c.text, ans.note, "A"))
        elif not ans.found:
            out.notes.append({"claim": c.id, "note": f"{full} is not in the law DB (coverage gap, not an error)"})

    def _authority(self, c: Claim, out: StageAResult) -> None:
        if not c.authority_title:
            return
        st = self.authorities.status(c.authority_title, self.cutoff, c.authority_court)
        if not st.found:
            if self.mode == "live":
                out.notes.append({"claim": c.id, "note": "authority not in any local source (possibly from the web): unverified"})
            else:
                out.findings.append(Finding("ERR_UNVERIFIED_AUTHORITY", c.text, "not found in any enabled authority source", "A"))
            return
        if st.anachronistic:
            when = st.date or str(st.year)
            out.findings.append(Finding("ERR_ANACHRONISTIC_AUTHORITY", c.text,
                                        f"{st.title} ({when}) is not before the decision date {self.cutoff.isoformat()}", "A"))
        if st.same_year_unknown:
            out.notes.append({"claim": c.id, "note": f"{st.title}: decided in {st.year}, same year as the cutoff; exact date unverified"})
        if st.treatment_note:
            out.notes.append({"claim": c.id, "note": st.treatment_note})
