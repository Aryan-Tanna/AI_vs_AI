"""Reproducible audit of the raw precedent + law files. Numbers quoted in CLAUDE.md §3 come from here.

Run: python scripts/audit_raw.py
"""
import collections
import glob
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CITE = re.compile(r"\s*\[cite:[^\]]*\]")
STOP = re.compile(r"\b(m/s\.?|mr\.?|ms\.?|mrs\.?|shri|ltd|limited|pvt|private|and|anr|ors)\b")


def clean(s):
    return CITE.sub("", s).strip() if isinstance(s, str) else s


def iter_raw_records(path):
    txt = path.read_text(encoding="utf-8")
    dec, i, n = json.JSONDecoder(), 0, len(txt)
    while i < n:
        while i < n and txt[i] in " \t\r\n,[]":
            i += 1
        if i >= n:
            break
        try:
            obj, i = dec.raw_decode(txt, i)
        except json.JSONDecodeError as e:
            yield {"_parse_error": str(e), "_file": str(path), "_offset": i}
            nxt = txt.find("\n", i)
            i = n if nxt < 0 else nxt + 1
            continue
        for rec in obj if isinstance(obj, list) else [obj]:
            rec["_file"] = str(path)
            yield rec


def title_key(title):
    """Dedup normaliser: strip cite markers, honorifics/company suffixes, non-letters; first 40 chars."""
    return re.sub(r"[^a-z]", "", STOP.sub("", clean(title).lower()))[:40]


def canon_statute(s):
    s = clean(s).upper()
    s = re.sub(r"^(COMPANIES_ACT_2013|CA_2013|CA2013)_SEC_?", "CA2013_SEC", s)
    s = re.sub(r"^NCLAT_RULES_2016_RULE_", "NCLAT_RULES2016_R", s)
    for pat in (r"^(IBC_2016_SEC_\d+[A-Z]*)", r"^(CA2013_SEC\d+[A-Z]*)",
                r"^(LIMITATION_ACT_1963_(SEC|ART)_\d+)", r"^(IBBI_CIRP_REG_\d+[A-Z]*)",
                r"^(NCLAT_RULES2016_R\d+)"):
        m = re.match(pat, s)
        if m:
            return m.group(1)
    return s


def main():
    files = sorted(ROOT.glob("nclat_precedents*/*.jsonl"))
    raw_ids = sum(f.read_text(encoding="utf-8").count('"precedent_id"') for f in files)
    recs, errs = [], []
    for f in files:
        for r in iter_raw_records(f):
            (errs if "_parse_error" in r else recs).append(r)
    print(f"raw precedent_id occurrences {raw_ids} | parsed {len(recs)} | lost {raw_ids - len(recs)} | parse-error segments {len(errs)}")
    print("records with [cite] artefacts:", sum("[cite" in json.dumps(r) for r in recs))

    groups = collections.defaultdict(list)
    for r in recs:
        groups[(title_key(r["case_title"]), clean(r["decision_date"]))].append(r)
    dups = {k: v for k, v in groups.items() if len(v) > 1}
    print(f"unique cases {len(groups)} | dup groups {len(dups)} | extra copies {sum(len(v) - 1 for v in dups.values())}")
    print("dup groups with conflicting labels:", sum(len({clean(x['final_order']) for x in v}) > 1 for v in dups.values()))
    idmap = collections.defaultdict(set)
    for k, v in groups.items():
        for x in v:
            idmap[x["precedent_id"]].add(k)
    print("precedent_id collisions:", sum(len(v) > 1 for v in idmap.values()))

    U = [v[0] for v in groups.values()]
    print("labels:", collections.Counter(clean(x["final_order"]) for x in U))
    print("years:", sorted(collections.Counter(x["decision_date"][:4] for x in U).items()))
    print("material_dates present:", sum("material_dates" in x for x in U))
    cites = [[canon_statute(s) for s in x["statutes_cited"]] for x in U]
    print("no IBC statute:", sum(not any(c.startswith("IBC") for c in cs) for cs in cites))
    print("cite s.7 or s.9:", sum(any(c in ("IBC_2016_SEC_7", "IBC_2016_SEC_9") for c in cs) for cs in cites))
    sec = collections.Counter(c for cs in cites for c in set(cs) if c.startswith("IBC_2016_SEC_"))
    print("top IBC sections by #cases:", [(k.replace("IBC_2016_SEC_", ""), v) for k, v in sec.most_common(25)])

    law = [x for f in glob.glob(str(ROOT / "law_db/*.json")) + glob.glob(str(ROOT / "law2db/*.json"))
           for x in json.load(open(f, encoding="utf-8"))]
    law_ids = {canon_statute(x["_id"]) for x in law}
    allc = collections.Counter(c for cs in cites for c in cs)
    tot, hit = sum(allc.values()), sum(v for k, v in allc.items() if k in law_ids)
    ibc = {k: v for k, v in allc.items() if k.startswith("IBC")}
    print(f"law entries {len(law)} | statute cites resolvable after aliasing {hit}/{tot} = {hit / tot:.0%} | IBC only "
          f"{sum(v for k, v in ibc.items() if k in law_ids) / sum(ibc.values()):.0%}")
    dangling = {canon_statute(r) for x in law for r in x.get("intersecting_statute_ids", [])} - law_ids
    print("dangling intersecting ids after aliasing:", len(dangling))


if __name__ == "__main__":
    main()
