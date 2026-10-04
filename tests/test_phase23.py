"""Phase 2 (ingest, retrieval) and Phase 3 (research tools, THEMIS Stage A) — no model calls."""
import asyncio
import datetime as dt
import json
from pathlib import Path

import pytest

from lexarena.config import ROOT
from lexarena.ingest.load_raw import iter_raw_records, LoadReport
from lexarena.ingest.normalise import appeal_keys, label_of, split_ratio
from lexarena.ingest.statute_alias import canon, from_text
from lexarena.law.authorities import AuthorityRegistry
from lexarena.law.provisions import LawStore
from lexarena.public_db import UnspoiledCase
from lexarena.retrieval.search import ReferenceIndex
from lexarena.services import Services
from lexarena.themis.claims import ClaimSet
from lexarena.themis.stage_a import StageA
from lexarena.tools.research import make_research_tools

D = dt.date
EXAMPLE = Path(__file__).resolve().parent.parent / "docs" / "schema" / "example"


def ref_case(uid, title, date, prop, statutes=("IBC_2016_SEC_7",), overruled=False):
    return {"case_uid": uid, "title": title, "decision_date": date, "bench_city": "NEW_DELHI", "label": "DISMISSED",
            "statutes": list(statutes), "propositions": [prop], "legal_issues": [], "material_facts": "",
            "is_overruled_raw": overruled}


REFS = [
    ref_case("REF-A", "Alpha Bank v. Beta Mills", "2019-05-01", "A balance sheet entry acknowledges debt under section 18."),
    ref_case("REF-B", "Gamma ARC v. Delta Steel", "2021-06-01", "Balance sheet acknowledgment extends limitation under section 18."),
    ref_case("REF-SELF", "Simulated Case v. Itself", "2019-08-01", "Balance sheet entry section 18 acknowledgment of the very case."),
    ref_case("REF-OLD", "Omega v. Sigma", "2018-01-01", "Balance sheet entries are not acknowledgment under section 18.", overruled=True),
]
SEED = [{"uid": "SC-VIDARBHA", "title": "Vidarbha Industries Power Ltd. v. Axis Bank Ltd.", "year": 2022, "proposition": "p"},
        {"uid": "SC-BISHAL", "title": "Asset Reconstruction Company (India) Ltd. v. Bishal Jaiswal", "year": 2021, "proposition": "p"},
        {"uid": "SC-BK", "title": "B.K. Educational Services Pvt. Ltd. v. Parag Gupta and Associates", "year": 2018, "proposition": "p"}]


# ---- Phase 2: ingest ------------------------------------------------------------------------------------

def test_loader_recovers_record_after_broken_one(tmp_path):
    f = tmp_path / "x.jsonl"
    f.write_text('{"precedent_id": "a", "x": 1}\n{"precedent_id": "b", "x": BROKEN {"precedent_id": "c", "x": 3}\n', encoding="utf-8")
    rep = LoadReport()
    ids = [r["precedent_id"] for r in iter_raw_records(f, rep)]
    assert ids == ["a", "c"] and rep.lost == 1 and len(rep.errors) == 1


def test_label_reads_remand_and_partly_from_operative_order():
    assert label_of("ALLOWED", "Impugned order set aside; matter remitted to the Adjudicating Authority") == ("ALLOWED_REMANDED", "operative_order")
    assert label_of("ALLOWED", "Appeal partly allowed") == ("PARTLY_ALLOWED", "operative_order")
    assert label_of("REJECTED", "") == ("DISMISSED", "final_order")


def test_appeal_keys_are_qualified_by_bench_and_type():
    assert appeal_keys("Company Appeal (AT) (CH) (Ins) No. 32 of 2024") == {"INS|CH|32/2024"}
    assert appeal_keys("Company Appeal (AT) (Ins) No. 32 of 2024") == {"INS|32/2024"}
    assert appeal_keys("Comp. App. (AT) (Ins.) No. 426 of 2020 with No. 430 of 2020") == {"INS|426/2020", "INS|430/2020"}


def test_statute_canonical_ids():
    assert canon("CA2013_SEC241") == ("COMPANIES_ACT_2013_SEC_241", "COMPANIES_ACT_2013_SEC_241")
    assert canon("IBC_2016_SEC_61_2") == ("IBC_2016_SEC_61", "IBC_2016_SEC_61_2")
    assert canon("NCLAT_RULES2016_R11")[0] == "NCLAT_RULES_2016_RULE_11"
    assert from_text("Section 61(2) of the IBC") == ("IBC_2016_SEC_61", "IBC_2016_SEC_61_2")
    assert from_text("Article 137 of the Limitation Act")[0] == "LIMITATION_ACT_1963_ART_137"


def test_ratio_split_into_numbered_propositions():
    parts = split_ratio("1. ABSTRACT LEGAL RULE: First rule. 2. STATUTORY INTERPRETATION: Second rule.")
    assert len(parts) == 2 and parts[1].startswith("2. STATUTORY")


# ---- Phase 2: retrieval filters -------------------------------------------------------------------------

def test_search_never_returns_excluded_or_future_cases():
    idx = ReferenceIndex(REFS)
    hits = idx.search("balance sheet acknowledgment section 18", cutoff=D(2020, 1, 1), exclude={"REF-SELF"}, k=10)
    uids = {h.case_uid for h in hits}
    assert "REF-SELF" not in uids and "REF-B" not in uids        # excluded; decided after the cutoff
    assert uids == {"REF-A", "REF-OLD"}
    assert next(h for h in hits if h.case_uid == "REF-OLD").treatment_note   # overruled flag surfaced, not hidden


def test_section_references_tokenised():
    from lexarena.retrieval.bm25 import tokenize
    assert "sec_29a" in tokenize("Section 29A of the Code") and "sec_29a" in tokenize("s. 29A") and "art_137" in tokenize("Article 137")


# ---- Phase 3: research tools ----------------------------------------------------------------------------

def services():
    return Services(LawStore.load(ROOT), AuthorityRegistry(REFS, SEED), ReferenceIndex(REFS))


def call(tool_obj, args):
    res = asyncio.run(tool_obj.handler(args))
    return res, res["content"][0]["text"]


def test_search_tool_applies_case_cutoff_and_exclusions():
    tools = make_research_tools(D(2019, 12, 31), services(), exclude={"REF-SELF"})
    _, text = call(tools["search_authorities"], {"query": "balance sheet acknowledgment section 18", "k": 10})
    assert "Alpha Bank" in text and "Gamma ARC" not in text and "Simulated Case" not in text and "REF-" not in text


def test_authority_status_hides_post_cutoff_details():
    tools = make_research_tools(D(2021, 3, 14), services(), exclude=set())
    _, text = call(tools["authority_status"], {"title": "Vidarbha Industries v. Axis Bank", "court": "SC"})
    assert json.loads(text)["usable"] is False


def test_rules_tool_and_bad_input():
    tools = make_research_tools(D(2021, 3, 14), services(), exclude=set())
    _, text = call(tools["rules_limitation"], {"default_date": "2015-12-31", "filing_date": "2020-01-10",
                                               "acknowledgment_dates": ["2018-09-05"]})
    assert json.loads(text)["status"] == "WITHIN_LIMITATION"
    res, _ = call(tools["rules_limitation"], {"default_date": "31/12/2015"})
    assert res.get("is_error")


# ---- Phase 3: THEMIS Stage A ----------------------------------------------------------------------------

@pytest.fixture
def stage_a():
    case = UnspoiledCase.model_validate(json.loads((EXAMPLE / "unspoiled.json").read_text(encoding="utf-8")))
    return StageA(case, LawStore.load(ROOT), AuthorityRegistry(REFS, SEED))


def run(stage_a, *claims):
    return stage_a.run(ClaimSet.model_validate({"claims": list(claims)}))


def codes(res):
    return [f.code for f in res.findings]


def test_correct_facts_pass(stage_a):
    r = run(stage_a, {"id": "C1", "kind": "DATE", "text": "Default on 31.12.2015", "fact_key": "date_of_default", "date": "2015-12-31"},
            {"id": "C2", "kind": "DATE", "text": "Balance sheet signed 05.09.2018", "record_ref": "E4", "date": "2018-09-05"})
    assert codes(r) == []


def test_wrong_fact_and_wrong_event_date(stage_a):
    r = run(stage_a, {"id": "C1", "kind": "DATE", "text": "Default on 31.03.2016", "fact_key": "date_of_default", "date": "2016-03-31"},
            {"id": "C2", "kind": "AMOUNT", "text": "Rs 50 crore in default", "fact_key": "amount_in_default_inr", "amount_inr": 500000000},
            {"id": "C3", "kind": "DATE", "text": "OTS in May 2019", "record_ref": "E7", "date": "2019-05-01"})
    assert codes(r) == ["ERR_FACT_MISMATCH"] * 3


def test_wrong_limitation_conclusion_is_arithmetic_error(stage_a):
    r = run(stage_a, {"id": "C1", "kind": "COMPUTATION", "text": "Limitation expired on 31.12.2018, so the application is barred",
                      "computation": {"rule": "ART137_LIMITATION", "default_date": "2015-12-31", "filing_date": "2020-01-10",
                                      "acknowledgment_dates": ["2018-09-05"], "asserted_outcome": "BARRED"}})
    assert codes(r) == ["ERR_ARITHMETIC"]


def test_pre_covid_filing_accepts_expiry_with_or_without_covid(stage_a):
    r = run(stage_a, {"id": "C1", "kind": "COMPUTATION", "text": "Fresh period ran to 05.09.2021",
                      "computation": {"rule": "ART137_LIMITATION", "default_date": "2015-12-31", "filing_date": "2020-01-10",
                                      "acknowledgment_dates": ["2018-09-05"], "asserted_outcome": "WITHIN", "asserted_date": "2021-09-05"}})
    assert codes(r) == []


def test_day_count(stage_a):
    r = run(stage_a, {"id": "C1", "kind": "DAY_COUNT", "text": "30 days", "date_from": "2020-01-01", "date_to": "2020-02-01", "days": 30})
    assert codes(r) == ["ERR_ARITHMETIC"]


def test_provision_not_yet_in_force(stage_a):
    r = run(stage_a, {"id": "C1", "kind": "PROVISION", "text": "s.54A", "provision": "Section 54A of the IBC"})
    assert codes(r) == ["ERR_PROVISION_NOT_IN_FORCE"]          # inserted 04.04.2021; law_as_of 14.03.2021


def test_authorities(stage_a):
    r = run(stage_a,
            {"id": "C1", "kind": "AUTHORITY", "text": "Imaginary v. Nobody", "authority_title": "Imaginary Pvt Ltd v. Nobody Bank"},
            {"id": "C2", "kind": "AUTHORITY", "text": "Vidarbha", "authority_title": "Vidarbha Industries Power v. Axis Bank", "authority_court": "SC"},
            {"id": "C3", "kind": "AUTHORITY", "text": "B.K. Educational", "authority_title": "B.K. Educational Services v. Parag Gupta"},
            {"id": "C4", "kind": "AUTHORITY", "text": "Bishal Jaiswal", "authority_title": "Asset Reconstruction Company v. Bishal Jaiswal", "authority_court": "SC"})
    assert codes(r) == ["ERR_UNVERIFIED_AUTHORITY", "ERR_ANACHRONISTIC_AUTHORITY"]
    assert any("same year" in n.get("note", "") for n in r.notes)     # Bishal Jaiswal 2021 vs cutoff 2021: flagged, not failed


def test_read_record_all_returns_whole_record_in_one_call():
    from lexarena.tools.record import make_record_tools
    case = UnspoiledCase.model_validate(json.loads((EXAMPLE / "unspoiled.json").read_text(encoding="utf-8")))
    _, text = call(make_record_tools(case, [])["read_record"], {"section": "all"})
    body = json.loads(text)
    assert {"chronology", "issues", "impugned_order"} <= set(body) and "case_uid" not in body


def test_wrapped_structured_output_is_unwrapped_and_empty_is_rejected():
    from pydantic import ValidationError
    from lexarena.llm.claude_code import coerce_structured
    from lexarena.themis.claims import ClaimSet
    wrapped = {"parameter": json.dumps({"claims": [{"id": "C1", "kind": "DATE", "text": "x", "date": "2015-12-31"}]})}
    assert len(ClaimSet.model_validate(coerce_structured(wrapped, ClaimSet)).claims) == 1
    with pytest.raises(ValidationError):                 # the old silent failure: wrapper validated as "no claims"
        ClaimSet.model_validate(wrapped)
