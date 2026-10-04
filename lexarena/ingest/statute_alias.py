"""One canonical statute ID scheme (CLAUDE.md §3.3, build step D).

Canonical form: ACT_YEAR_UNIT_NUMBER[_SUBCLAUSE], e.g. IBC_2016_SEC_7, IBC_2016_SEC_61_2,
COMPANIES_ACT_2013_SEC_241, LIMITATION_ACT_1963_ART_137, NCLAT_RULES_2016_RULE_11.
`canon()` returns (section_id, full_id): section_id drops the sub-clause for lookups; full_id keeps it.
"""
import re

CITE = re.compile(r"\s*\[cite:[^\]]*\]")

PREFIX_ALIASES = [
    (r"^CA2013_SEC_?", "COMPANIES_ACT_2013_SEC_"),
    (r"^CA_2013_SEC_?", "COMPANIES_ACT_2013_SEC_"),
    (r"^CA1956_SEC_?", "COMPANIES_ACT_1956_SEC_"),
    (r"^CA_1956_SEC_?", "COMPANIES_ACT_1956_SEC_"),
    (r"^NCLAT_RULES_?2016_R(?:ULE)?_?", "NCLAT_RULES_2016_RULE_"),
    (r"^NCLT_RULES_?2016_R(?:ULE)?_?", "NCLT_RULES_2016_RULE_"),
    (r"^IBBI_CIRP_REG(?:ULATIONS)?(?:_2016)?_REG_?", "IBBI_CIRP_REGULATIONS_2016_REG_"),
    (r"^IBBI_CIRP_REG_?", "IBBI_CIRP_REGULATIONS_2016_REG_"),
    (r"^CONTRACT_ACT_1872", "INDIAN_CONTRACT_ACT_1872"),
    (r"^ARBITRATION_ACT_1996", "ARBITRATION_AND_CONCILIATION_ACT_1996"),
    (r"^CRPC_?1973", "CRPC_1973"),
]
UNIT = re.compile(r"^(?P<section>.*?_(?:SEC|RULE|ART|REG|ORDER|ARTICLE)_[0-9]+[A-Z]*)(?P<sub>(?:_[0-9A-Z]+)*)$")


def canon(raw: str) -> tuple[str, str]:
    s = CITE.sub("", raw or "").strip().upper()
    s = re.sub(r"[\s\-./()]+", "_", s).strip("_")
    s = re.sub(r"_+", "_", s)
    for pat, rep in PREFIX_ALIASES:
        if re.match(pat, s):
            s = re.sub(pat, rep, s, count=1)
            break
    s = re.sub(r"_SECTION_", "_SEC_", s)
    m = UNIT.match(s)
    if not m:
        return s, s
    return m.group("section"), s


def is_ibc(section_id: str) -> bool:
    return section_id.startswith("IBC_2016_")


ACTS = [
    (r"insolvency and bankruptcy code|\bibc\b|\bcode\b", "IBC_2016"),
    (r"limitation act", "LIMITATION_ACT_1963"),
    (r"companies act,? 1956", "COMPANIES_ACT_1956"),
    (r"companies act", "COMPANIES_ACT_2013"),
    (r"code of criminal procedure|cr\.?\s*p\.?\s*c", "CRPC_1973"),
    (r"nclat rules", "NCLAT_RULES_2016"),
    (r"nclt rules", "NCLT_RULES_2016"),
]
TEXT_REF = re.compile(r"\b(section|sec|s|article|art|rule|regulation|reg)\.?\s*(\d+[A-Z]{0,2})((?:\s*\(\s*[0-9a-zA-Z]+\s*\))*)", re.I)
UNIT_OF = {"section": "SEC", "sec": "SEC", "s": "SEC", "article": "ART", "art": "ART", "rule": "RULE",
           "regulation": "REG", "reg": "REG"}


def from_text(text: str, default_act: str = "IBC_2016") -> tuple[str, str] | None:
    """'Section 61(2) of the IBC' -> ('IBC_2016_SEC_61', 'IBC_2016_SEC_61_2'); 'Article 137 of the Limitation Act'
    -> LIMITATION_ACT_1963_ART_137. Returns None if no reference is found. Already-canonical IDs pass through."""
    if re.match(r"^[A-Z0-9_]+_(SEC|ART|RULE|REG|ORDER)_\d", (text or "").strip().upper()):
        return canon(text)
    m = TEXT_REF.search(text or "")
    if not m:
        return None
    unit = UNIT_OF[m.group(1).lower()]
    act = next((code for pat, code in ACTS if re.search(pat, text, re.I)),
               "LIMITATION_ACT_1963" if unit == "ART" else default_act)
    subs = re.findall(r"\(\s*([0-9a-zA-Z]+)\s*\)", m.group(3) or "")
    full = f"{act}_{unit}_{m.group(2).upper()}" + "".join(f"_{s.upper()}" for s in subs)
    return canon(full)
