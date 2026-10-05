"""Build the SILVER public case DB from the reference DB (CLAUDE.md §6.6.4a). Pure code: no model calls.

  python -m lexarena.ingest.build_silver                 # -> data/silver/{unspoiled,ground_truth,manifest}.jsonl
  LEX_PUBLIC_DB_DIR=data/silver python -m lexarena.cli enqueue debate --split dev --run-id silver-dev1

Silver cases are for train (reflection memory) and dev (prompt tuning, debugging) only. They are built from
LLM-written summaries that knew the outcome, so they are never used for reported results. Rules:
- only reference cases decided on or before 2024-12-31 (2025-26 decisions are the gold test pool: kept out);
- only in-scope IBC appeals;
- party names and case numbers anonymised; sentences that state the NCLAT's own outcome dropped;
- the real outcome goes to ground_truth.jsonl only; every case must pass the public DB validator, otherwise it
  is dropped with a reason (see data/reports/silver_build.md).
"""
import argparse
import collections
import datetime as dt
import hashlib
import json
import re
from pathlib import Path

from lexarena.config import Settings
from lexarena.ingest.statute_alias import from_text
from lexarena.public_db_validate import CASE_NUMBER_RE, ISSUE_OUTCOME_WORDS, _ngrams, validate_dir
from lexarena.schemas.public_case import PublicGroundTruth, PublicManifest, PublicUnspoiled

LAST_SILVER_DATE = dt.date(2024, 12, 31)
REMAND_COUNTS_AS_WIN = True        # proposed to the project owner 2026-10-05; fixed here so silver labels are explicit
SRC = lambda para: [{"doc": "REFERENCE_SUMMARY", "page": 1, "para": para}]  # noqa: E731

MONTHS = {m: i for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}
DATE_NUM = re.compile(r"\b(\d{1,2})[./-](\d{1,2})[./-]((?:19|20)\d{2})\b")
DATE_DMY = re.compile(r"\b(\d{1,2})(?:st|nd|rd|th)?\s+(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?,?\s+((?:19|20)\d{2})\b", re.I)
DATE_MDY = re.compile(r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+((?:19|20)\d{2})\b", re.I)
CASE_NO_BROAD = re.compile(
    r"\b(?:C\.?P\.?|I\.?A\.?|M\.?A\.?|C\.?A\.?|T\.?A\.?|I\.?B\.?|Company Petition|Company Appeal|Comp\.?\s*App\.?|"
    r"Civil Appeal|SLP|Writ Petition|W\.?P\.?)\b[^.;:]{0,40}?\d+\s*(?:of|/)\s*(?:19|20)\d{2}(?:\s*\))?", re.I)
NCLAT_OUTCOME = re.compile(
    r"\b(this (?:appellate )?tribunal|the appellate tribunal|nclat|the present appeal|this appeal|the appeal)\b"
    r".{0,120}\b(allowed|dismissed|set aside|upheld|affirmed|disposed|held that|holds that|rejected)\b", re.I)
NCLT = re.compile(r"\b(NCLT|Adjudicating Authority|National Company Law Tribunal)\b", re.I)
CITIES = ["New Delhi", "Delhi", "Mumbai", "Chennai", "Kolkata", "Ahmedabad", "Hyderabad", "Bengaluru", "Bangalore",
          "Chandigarh", "Allahabad", "Prayagraj", "Guwahati", "Jaipur", "Kochi", "Cuttack", "Indore", "Amaravati"]
NEUTRALISE = [(re.compile(r"\berred\s+in\b", re.I), "was justified in"), (re.compile(r"\b(rightly|wrongly|correctly)\s+", re.I), ""),
              (re.compile(r"\bincorrectly\s+", re.I), "")]
SUFFIX = re.compile(r"\b(m/s\.?|mr\.?|mrs\.?|ms\.?|shri|smt\.?|dr\.?|ltd\.?|limited|pvt\.?|private|&\s*anr\.?|&\s*ors\.?|"
                    r"and\s+anr\.?|and\s+ors\.?|and\s+others|through\b.*|represented\s+by\b.*)", re.I)

PROCEEDING_RULES = [   # most specific first; first match wins
    ({"IBC_2016_SEC_95", "IBC_2016_SEC_96", "IBC_2016_SEC_97", "IBC_2016_SEC_99", "IBC_2016_SEC_100"}, "PERSONAL_GUARANTOR_95_100"),
    ({"IBC_2016_SEC_29A"}, "SEC29A_ELIGIBILITY"),
    ({"IBC_2016_SEC_30", "IBC_2016_SEC_31"}, "RESOLUTION_PLAN_APPROVAL"),
    ({"IBC_2016_SEC_12A"}, "SEC12A_WITHDRAWAL"),
    ({f"IBC_2016_SEC_{n}" for n in (43, 44, 45, 46, 47, 48, 49, 50, 51, 66)}, "AVOIDANCE_43_66"),
    ({"IBC_2016_SEC_33", "IBC_2016_SEC_34", "IBC_2016_SEC_35", "IBC_2016_SEC_53"}, "LIQUIDATION"),
    ({"IBC_2016_SEC_9", "IBC_2016_SEC_8"}, "SEC9_ADMISSION"),
    ({"IBC_2016_SEC_7"}, "SEC7_ADMISSION"),
    ({"IBC_2016_SEC_10"}, "SEC10_ADMISSION"),
    ({"IBC_2016_SEC_60"}, "SEC60_5_JURISDICTION"),
    ({"IBC_2016_SEC_14"}, "MORATORIUM_SEC14"),
]
APPLICATION_TYPE = {"SEC7_ADMISSION": "SEC7", "SEC9_ADMISSION": "SEC9", "SEC10_ADMISSION": "SEC10",
                    "RESOLUTION_PLAN_APPROVAL": "SEC31_PLAN", "LIQUIDATION": "LIQUIDATION", "SEC12A_WITHDRAWAL": "SEC12A"}
ROLE_RULES = [
    (r"insolvency and bankruptcy board|\bibbi\b", "IBBI", "STATUTORY_BODY"),
    (r"\bliquidator\b", "LIQUIDATOR", "LIQUIDATOR"),
    (r"resolution professional|\b(?:i?rp)\b", "RESOLUTION_PROFESSIONAL", "RESOLUTION_PROFESSIONAL"),
    (r"committee of creditors|\bcoc\b", "COC", "COC"),
    (r"\bepfo\b|provident fund|commissioner|income tax|gst|customs|state of |union of india|government|"
     r"department|municipal|electricity|authority\b", "STATUTORY_AUTHORITY", "GOVERNMENT"),
    (r"\bunion\b|workmen|employees|workers", "WORKMEN_EMPLOYEES", "OTHER"),
    (r"homebuyer|allottee|home buyer", "HOMEBUYERS", "OTHER"),
    (r"\bbank\b|finance|financial|asset reconstruction|\barc\b|nbfc|capital|credit|investments?\b", "FINANCIAL_CREDITOR", "BANK"),
]


# ---- small helpers --------------------------------------------------------------------------------------

def _dates(text: str) -> list[dt.date]:
    out = []
    for d, m, y in DATE_NUM.findall(text):
        out.append((int(y), int(m), int(d)))
    for d, mon, y in DATE_DMY.findall(text):
        out.append((int(y), MONTHS[mon.lower()[:3]], int(d)))
    for mon, d, y in DATE_MDY.findall(text):
        out.append((int(y), MONTHS[mon.lower()[:3]], int(d)))
    res = []
    for y, m, d in out:
        try:
            res.append(dt.date(y, m, d))
        except ValueError:
            continue
    return res


LABEL = re.compile(r"^(?:\d+\.\s*)?[A-Z][A-Z /&-]{3,40}:\s*")     # summary labels like "PROCEDURAL HISTORY: "


def _sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.;])\s+(?=[A-Z(\[])", text or "")
    return [LABEL.sub("", p.strip(" ;")) for p in parts if len(p.strip()) > 15]


def _core_name(side: str) -> str:
    name = SUFFIX.sub(" ", side or "")
    name = re.sub(r"[()\[\],]", " ", name)
    return re.sub(r"\s+", " ", name).strip(" .&-")


def _party_patterns(core: str) -> list[re.Pattern]:
    words = core.split()
    forms = [core]
    if len(words) >= 3:
        forms.append(" ".join(words[:2]))
    return [re.compile(r"(?<![A-Za-z])" + r"\s+".join(map(re.escape, f.split())) + r"(?![A-Za-z])", re.I)
            for f in sorted(set(forms), key=len, reverse=True) if len(f) >= 4]


APPLICANT_BY = r"(?:filed|instituted|preferred|moved)\s+by\s+the\s+{side}|{side}\s+(?:had\s+)?(?:filed|instituted|preferred)"


def _role_and_kind(name: str, facts: str, side: str, ptype: str = "OTHER") -> tuple[str, str]:
    low = name.lower()
    for pat, role, kind in ROLE_RULES:
        if re.search(pat, low):
            return role, kind
    # the side that filed the s.7 / s.9 application below is the financial / operational creditor
    side_word = "appellant" if side == "APPELLANT" else "respondent"
    filed_by_side = re.search(APPLICANT_BY.format(side=side_word), facts, re.I)
    if ptype == "SEC9_ADMISSION" and (filed_by_side or re.search(side_word + r"[^.;]{0,60}operational creditor", facts, re.I)):
        return "OPERATIONAL_CREDITOR", "COMPANY"
    if ptype == "SEC7_ADMISSION" and (filed_by_side or re.search(side_word + r"[^.;]{0,60}financial creditor", facts, re.I)):
        return "FINANCIAL_CREDITOR", "COMPANY"
    individual = bool(re.search(r"\b(mr|mrs|ms|shri|smt|dr)\b\.?", low)) or not re.search(
        r"\b(ltd|limited|pvt|private|llp|corporation|company|industries|enterprises|infra\w*|developers?)\b", low)
    if individual:
        if side == "APPELLANT" and re.search(r"suspended (board|director)|promoter|ex-director|former director", facts, re.I):
            return "SUSPENDED_DIRECTOR_PROMOTER", "INDIVIDUAL"
        return "OTHER", "INDIVIDUAL"
    if side == "APPELLANT" and re.search(r"operational creditor", facts, re.I) and re.search(re.escape(name.split()[0]), facts):
        return "OPERATIONAL_CREDITOR", "COMPANY"
    return "OTHER", "COMPANY"


def _neutral_issue(text: str) -> str | None:
    t = text
    for pat, rep in NEUTRALISE:
        t = pat.sub(rep, t)
    t = re.sub(r"\s+", " ", t).strip()
    return None if ISSUE_OUTCOME_WORDS.search(t) else t


def _proceeding_type(statutes: set[str]) -> str:
    for keys, ptype in PROCEEDING_RULES:
        if keys & statutes:
            return ptype
    return "OTHER"


# ---- build one case -------------------------------------------------------------------------------------

class Skip(Exception):
    pass


def build_case(ref: dict, uid: str) -> tuple[dict, dict, dict]:
    decision = dt.date.fromisoformat(ref["decision_date"])
    title = ref["title"]
    sides = re.split(r"\s+(?:vs?\.?|versus)\s+", title, maxsplit=1, flags=re.I)
    if len(sides) != 2:
        raise Skip("title has no 'v.'")
    facts_raw = ref.get("material_facts", "")

    statutes = set(ref.get("statutes", []))
    ptype = _proceeding_type(statutes)

    # parties and anonymisation
    parties, real_parties, patterns = [], [], []
    for side, raw in zip(("APPELLANT", "RESPONDENT"), sides):
        core = _core_name(raw)
        if len(core) < 3:
            raise Skip("party name too short to anonymise")
        token = f"[{side}_1]"
        role, kind = _role_and_kind(core, facts_raw, side, ptype)
        parties.append({"token": token, "kind": kind, "side": side, "role": role,
                        "description": f"{'appellant' if side == 'APPELLANT' else 'respondent'} ({role.lower().replace('_', ' ')})"})
        real_parties.append({"token": token, "name": core})
        patterns += [(p, token) for p in _party_patterns(core)]
    case_numbers: set[str] = set()

    def anon(text: str) -> str:
        for pat, token in patterns:
            text = pat.sub(token, text)
        for rx in (CASE_NO_BROAD, CASE_NUMBER_RE):
            for m in rx.finditer(text):
                case_numbers.add(m.group(0).strip())
            text = rx.sub("[CASE_NUMBER]", text)
        return re.sub(r"\s+", " ", text).strip()

    # chronology from dated sentences; drop sentences that state the NCLAT's own outcome
    events, impugned = [], None
    for sent in _sentences(facts_raw):
        if NCLAT_OUTCOME.search(sent):
            continue
        ds = [d for d in _dates(sent) if d < decision]
        if not ds:
            continue
        eid = f"E{len(events) + 1}"
        events.append({"id": eid, "date": ds[-1].isoformat(), "date_precision": "DAY",
                       "event": anon(sent)[:400], "src": SRC("material_facts")})
        if NCLT.search(sent):
            impugned = (eid, ds[-1], sent)          # latest NCLT sentence wins
    if not events:
        raise Skip("no dated facts")
    if impugned is None:
        raise Skip("no NCLT order found in the facts")

    low = impugned[2].lower()
    outcome_below = ("ADMITTED" if "admit" in low else "PLAN_APPROVED" if "approv" in low else
                     "REJECTED" if re.search(r"reject|dismiss", low) else "ALLOWED" if "allow" in low else "NOT_STATED")
    city = next((c for c in CITIES if c.lower() in impugned[2].lower()), None)
    bench_city = {"Delhi": "NEW_DELHI", "Bangalore": "BENGALURU", "Prayagraj": "ALLAHABAD"}.get(city, (city or "UNKNOWN").upper().replace(" ", "_"))

    # Only the impugned-order date is reliable enough to be a typed fact: Stage A checks claims against typed facts,
    # and heuristic default/filing dates (tried and measured) produced wrong values, i.e. false flags.
    typed = {"impugned_order_date": {"value": impugned[1].isoformat(), "ref": impugned[0], "verified": False}}

    issues = []
    for t in ref.get("legal_issues", []):
        n = _neutral_issue(anon(t))
        if n and len(n) > 15:
            prov = from_text(n)
            issues.append({"id": f"I{len(issues) + 1}", "text": n[:600], "provisions": [prov[0]] if prov else []})
    if not issues:
        raise Skip("no neutral issues")

    grounds = [{"id": f"G{i + 1}", "issue": x["id"], "heading": ("Contests the impugned order on: " + x["text"])[:240], "src": SRC("legal_issues")}
               for i, x in enumerate(issues)]
    contentions = [{"id": f"R{i + 1}", "issue": x["id"], "heading": ("Supports the impugned order on: " + x["text"])[:240], "src": SRC("legal_issues")}
                   for i, x in enumerate(issues)]
    respondent_roles = [p["role"] for p in parties if p["side"] == "RESPONDENT"]
    unspoiled = {
        "schema_version": "1.0", "case_uid": uid,
        "title_anon": "[APPELLANT_1] v. [RESPONDENT_1]", "forum": "NCLAT", "bench_city": ref.get("bench_city") or "UNKNOWN",
        "law_as_of": (decision - dt.timedelta(days=1)).isoformat(),
        "proceeding_type": ptype, "appellant_role": parties[0]["role"], "respondent_roles": respondent_roles,
        "parties": parties,
        "placeholders": [{"token": "[CASE_NUMBER]", "kind": "OTHER", "description": "a case or application number removed by anonymisation"}],
        "impugned_order": {"forum": "NCLT", "bench_city": bench_city, "date": impugned[1].isoformat(),
                           "application_type": APPLICATION_TYPE.get(ptype, "OTHER"), "outcome_below": outcome_below,
                           "reasoning_summary": anon(impugned[2])[:800], "src": SRC("material_facts")},
        "chronology": events, "typed_facts": typed, "record_documents": [], "issues": issues,
        "appellant_grounds": grounds, "respondent_contentions": contentions,
        "statutes_in_play": sorted({p for x in issues for p in x["provisions"]}),
        "appeal_scope": {"restricted_grounds": "SEC61_3" if ptype == "RESOLUTION_PLAN_APPROVAL" else
                         "SEC61_4" if ptype == "LIQUIDATION" else None, "record_closed_after_turn": 3},
        "record_conflicts": [],
    }

    label = ref["label"]
    won = (True if label in ("ALLOWED", "PARTLY_ALLOWED") else
           REMAND_COUNTS_AS_WIN if label == "ALLOWED_REMANDED" else False if label == "DISMISSED" else None)
    ground_truth = {
        "schema_version": "1.0", "case_uid": uid, "decision_date": decision.isoformat(), "label": label, "appellant_won": won,
        "outcome_detail": "silver: label from the reference summary",
        "issue_findings": [{"issue": x["id"], "finding": "NOT_MAPPED", "src": SRC("ratio_decidendi")} for x in issues],
        "ratio_decidendi": ref.get("ratio_decidendi") or "(none in reference)",
        "operative_order_verbatim": ref.get("operative_order") or "(none in reference)",
        "submissions_full": {"appellant": "Not available in the reference summary."},
        "authorities_cited_by_parties": [],
    }

    # leakage: drop chronology events that share 8 words with the decision; drop the case if the core text still does
    sealed = _ngrams(" ".join([ground_truth["ratio_decidendi"], ground_truth["operative_order_verbatim"]]))
    keep = [e for e in events if not (_ngrams(e["event"]) & sealed)]
    if len(keep) != len(events):
        kept_ids = {e["id"] for e in keep}
        if impugned[0] not in kept_ids:
            raise Skip("impugned-order sentence overlaps the decision text")
        unspoiled["chronology"] = keep
        unspoiled["typed_facts"] = {k: v for k, v in typed.items() if v["ref"] in kept_ids}
    if _ngrams(json.dumps(unspoiled, ensure_ascii=False)) & sealed:
        raise Skip("unspoiled text overlaps the decision text")

    sha = hashlib.sha256(json.dumps(ref, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()
    split = "train" if decision.year <= 2023 else "dev"
    manifest = {
        "schema_version": "1.0", "case_uid": uid,
        "real": {"title": title, "appeal_numbers": ref.get("appeal_numbers") or ["(unknown)"], "parties": real_parties,
                 "bench_members": [], "other_identifiers": sorted(case_numbers)},
        "sources": [{"doc": "REFERENCE_SUMMARY", "url": f"reference:{ref['case_uid']}", "sha256": sha, "pages": 1}],
        "overlap_with_reference_db": {"reference_case_uids": [ref["case_uid"]], "raw_precedent_ids": ref.get("source", {}).get("raw_precedent_ids", [])},
        "in_scope": True, "split": split,
        "strata": {"proceeding_type": ptype, "appellant_role": parties[0]["role"], "year": decision.year},
        "build": {"method": "SILVER_AUTO", "drafted_by": "lexarena.ingest.build_silver"},
        "qa": {"notes": "Silver: auto-built from an LLM-written reference summary; roles, proceeding type and typed facts "
                        "are heuristic; grounds are issue-level headings; not for reported results."},
    }
    # per-record schema validation (cross-file rules run later on the whole directory)
    PublicUnspoiled.model_validate(unspoiled)
    PublicGroundTruth.model_validate(ground_truth)
    PublicManifest.model_validate(manifest)
    return unspoiled, ground_truth, manifest


# ---- build all ------------------------------------------------------------------------------------------

def build(reference: list[dict], out_dir: Path) -> dict:
    skips: collections.Counter = collections.Counter()
    records = {}
    seen_appeals: set[str] = set()
    eligible = [r for r in reference if r.get("ibc") and dt.date.fromisoformat(r["decision_date"]) <= LAST_SILVER_DATE]
    for n, ref in enumerate(sorted(eligible, key=lambda r: (r["decision_date"], r["case_uid"])), start=1):
        appeals = {re.sub(r"\W", "", a.lower()) for a in ref.get("appeal_numbers", [])}
        if appeals & seen_appeals:
            skips["appeal number already used by an earlier case"] += 1
            continue
        uid = f"PC-S{n:05d}"
        try:
            records[uid] = build_case(ref, uid)
            seen_appeals |= appeals
        except Skip as e:
            skips[str(e)] += 1
        except ValueError as e:                    # pydantic validation
            skips[f"schema: {str(e).splitlines()[0][:80]}"] += 1

    def write():
        out_dir.mkdir(parents=True, exist_ok=True)
        for i, name in enumerate(("unspoiled", "ground_truth", "manifest")):
            (out_dir / f"{name}.jsonl").write_text("".join(json.dumps(r[i], ensure_ascii=False) + "\n" for r in records.values()),
                                                   encoding="utf-8")
        splits = out_dir / "splits"
        splits.mkdir(exist_ok=True)
        for sp in ("train", "dev"):
            (splits / f"{sp}.txt").write_text("".join(u + "\n" for u, r in records.items() if r[2]["split"] == sp), encoding="utf-8")
        (splits / "test.txt").write_text("", encoding="utf-8")

    write()
    for _ in range(3):                             # drop cases that fail cross-file validation, then re-check
        errors = [p for p in validate_dir(out_dir) if p.level == "ERROR"]
        bad = {p.case_uid for p in errors if p.case_uid in records}
        if not bad:
            break
        for p in errors:
            if p.case_uid in records:
                skips[f"validator: {p.message[:70]}"] += 1
        for uid in bad:
            records.pop(uid, None)
        write()
    final_errors = [p for p in validate_dir(out_dir) if p.level == "ERROR"]
    stats = {"reference_cases": len(reference), "eligible_ibc_until_2024": len(eligible), "built": len(records),
             "train": sum(r[2]["split"] == "train" for r in records.values()),
             "dev": sum(r[2]["split"] == "dev" for r in records.values()),
             "validator_errors": len(final_errors),
             "proceeding_types": dict(collections.Counter(r[0]["proceeding_type"] for r in records.values()).most_common()),
             "appellant_roles": dict(collections.Counter(r[0]["appellant_role"] for r in records.values()).most_common()),
             "labels": dict(collections.Counter(r[1]["label"] for r in records.values()).most_common()),
             "skipped": dict(skips.most_common())}
    return stats


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--out", type=Path, default=None)
    args = p.parse_args()
    s = Settings()
    out = args.out or (s.data_dir / "silver")
    reference = [json.loads(x) for x in s.reference_path.read_text(encoding="utf-8").splitlines() if x.strip()]
    stats = build(reference, out)
    rep = s.data_dir / "reports" / "silver_build.md"
    rep.parent.mkdir(parents=True, exist_ok=True)
    rep.write_text("# Silver public DB build report\n\nGenerated by `python -m lexarena.ingest.build_silver`. Silver cases are "
                   "for train/dev only (CLAUDE.md §6.6.4a).\n\n```json\n" + json.dumps(stats, indent=1) + "\n```\n", encoding="utf-8")
    print(json.dumps(stats, indent=1))
    print("wrote", out, "and", rep)


if __name__ == "__main__":
    main()
