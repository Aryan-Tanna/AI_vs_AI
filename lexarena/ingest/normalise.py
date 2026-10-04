"""Clean and normalise raw reference records (build step B)."""
import re

from lexarena.ingest.statute_alias import CITE, canon, is_ibc

LABELS = {"DISMISSED": "DISMISSED", "REJECTED": "DISMISSED", "ALLOWED": "ALLOWED", "DISPOSED": "DISPOSED",
          "WITHDRAWN": "WITHDRAWN", "MODIFIED": "PARTLY_ALLOWED"}
REMAND = re.compile(r"\b(remand|remit|restor(?:e|ed) (?:to|back)|sent back|reconsider afresh|fresh consideration)", re.I)
PARTLY = re.compile(r"\b(partly|partially|in part|modified|to the extent)\b", re.I)
ISSUE_SPLIT = re.compile(r"\s*(?:\((?:[ivxlc]+|\d+|[a-z])\)|(?<!\w)\d+\.)\s+")
RATIO_SPLIT = re.compile(r"(?:^|\s)(?=\d+\.\s+[A-Z][A-Z /&-]{3,}:)")


def strip_cites(obj):
    if isinstance(obj, str):
        return CITE.sub("", obj).strip()
    if isinstance(obj, list):
        return [strip_cites(x) for x in obj]
    if isinstance(obj, dict):
        return {k: strip_cites(v) for k, v in obj.items()}
    return obj


def label_of(final_order: str, operative_order: str) -> tuple[str, str]:
    """Returns (label, source). Raw labels never say PARTLY_ALLOWED / ALLOWED_REMANDED; read the operative order."""
    base = LABELS.get((final_order or "").strip().upper(), "UNKNOWN")
    if base == "ALLOWED" and REMAND.search(operative_order or ""):
        return "ALLOWED_REMANDED", "operative_order"
    if base == "ALLOWED" and PARTLY.search(operative_order or ""):
        return "PARTLY_ALLOWED", "operative_order"
    return base, "final_order"


def bench_city(bench: str, forum: str) -> str:
    text = f"{bench} {forum}".lower()
    if "chennai" in text:
        return "CHENNAI"
    if "delhi" in text or "principal" in text:
        return "NEW_DELHI"
    return "UNKNOWN"


def split_issues(text) -> list[str]:
    if isinstance(text, list):
        return [t for t in (str(x).strip() for x in text) if t]
    parts = [p.strip(" ;") for p in ISSUE_SPLIT.split(text or "") if p and p.strip(" ;")]
    return parts or ([text.strip()] if text and text.strip() else [])


def split_ratio(text: str) -> list[str]:
    """Numbered propositions ("1. ABSTRACT LEGAL RULE: ...") when present, else ~600-char sentence groups."""
    text = (text or "").strip()
    parts = [p.strip() for p in RATIO_SPLIT.split(text) if p.strip()]
    if len(parts) > 1:
        return parts
    sentences = re.split(r"(?<=[.;])\s+(?=[A-Z])", text)
    chunks, cur = [], ""
    for s in sentences:
        if cur and len(cur) + len(s) > 600:
            chunks.append(cur.strip())
            cur = ""
        cur += " " + s
    if cur.strip():
        chunks.append(cur.strip())
    return chunks


def appeal_keys(appeal_number: str) -> set[str]:
    """Every 'number/year' pair in an appeal string (consolidated appeals carry several), qualified by bench and
    appeal type, because numbering restarts per bench (Chennai vs Principal) and per type (insolvency, company,
    competition)."""
    up = (appeal_number or "").upper()
    kind = ("COMPETITION" if "COMPETITION" in up else "INS" if "INS" in up else "COMPANY") + \
           ("|CH" if re.search(r"\bCH\b|CHENNAI", up) else "")
    return {f"{kind}|{int(n)}/{y}" for n, y in re.findall(r"(\d{1,5})\s*(?:of|/)\s*((?:19|20)\d{2})", appeal_number or "")}


def normalise(rec: dict) -> dict:
    r = strip_cites(rec)
    label, label_source = label_of(r.get("final_order", ""), r.get("operative_order", ""))
    statutes = [canon(s) for s in r.get("statutes_cited", []) if isinstance(s, str) and s.strip()]
    sections = sorted({s for s, _ in statutes})
    return {
        "title": r.get("case_title", ""),
        "appeal_number": r.get("appeal_number", ""),
        "decision_date": r.get("decision_date", ""),
        "bench_city": bench_city(r.get("bench", ""), r.get("forum", "")),
        "label": label, "label_source": label_source,
        "statutes": sections,
        "statutes_full": sorted({f for _, f in statutes}),
        "ibc": any(is_ibc(s) for s in sections),
        "material_facts": r.get("material_facts", ""),
        "legal_issues": split_issues(r.get("legal_issues", "")),
        "ratio_decidendi": r.get("ratio_decidendi", ""),
        "propositions": split_ratio(r.get("ratio_decidendi", "")),
        "operative_order": r.get("operative_order", ""),
        "summary": r.get("summary", ""),
        "is_overruled_raw": bool(r.get("is_overruled")),
        "precedent_id": r.get("precedent_id", ""),
        "_file": rec.get("_file", ""),
    }
