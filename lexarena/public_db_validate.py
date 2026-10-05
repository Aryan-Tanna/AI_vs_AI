"""Validate a public case DB directory (CLAUDE.md §6.6, build step PB1).

Reads unspoiled / ground_truth / manifest as `<name>.jsonl` (one record per line) or `<name>.json` (one record).
Per-record schema rules live in lexarena/schemas/public_case.py; this module adds the cross-file rules:
issue coverage, dates, split, scope, page references, anonymisation, leakage, duplicates.
"""
import datetime as dt
import json
import re
from dataclasses import dataclass
from pathlib import Path

from pydantic import ValidationError

from lexarena.schemas.public_case import PublicGroundTruth, PublicManifest, PublicUnspoiled

FILES = {"unspoiled": PublicUnspoiled, "ground_truth": PublicGroundTruth, "manifest": PublicManifest}
NGRAM = 8
CASE_NUMBER_RE = re.compile(
    r"\b(?:C\.?P\.?|M\.?A\.?|I\.?A\.?|C\.?A\.?|T\.?A\.?)\s*(?:\(IB\)\s*)?No\.?\s*\d+|Company Appeal|\(AT\)\s*\(Ins", re.I)
ISSUE_OUTCOME_WORDS = re.compile(r"\b(erred|rightly|wrongly|correctly|dismissed|upheld|set aside|no error|otiose)\b", re.I)
NON_IBC = {"COMPANIES_ACT_241_242", "COMPANIES_ACT_STRIKE_OFF"}


@dataclass
class Problem:
    case_uid: str
    level: str          # ERROR | WARN
    message: str

    def __str__(self) -> str:
        return f"{self.level:5} {self.case_uid}: {self.message}"


def _load(dir_: Path, name: str) -> list[dict]:
    jl, js = dir_ / f"{name}.jsonl", dir_ / f"{name}.json"
    if jl.exists():
        return [json.loads(line) for line in jl.read_text(encoding="utf-8").splitlines() if line.strip()]
    if js.exists():
        return [json.loads(js.read_text(encoding="utf-8"))]
    return []


def _words(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.lower())


def _ngrams(text: str, n: int = NGRAM) -> set[tuple[str, ...]]:
    w = _words(text)
    return {tuple(w[i:i + n]) for i in range(len(w) - n + 1)}


def _srcs(obj) -> list[dict]:
    """Every src entry anywhere in a nested dict/list."""
    out = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k == "src" and isinstance(v, list):
                out += [s for s in v if isinstance(s, dict)]
            else:
                out += _srcs(v)
    elif isinstance(obj, list):
        for v in obj:
            out += _srcs(v)
    return out


def expected_split(year: int) -> str:
    return "train" if year <= 2023 else "dev" if year == 2024 else "test"


def validate_dir(dir_: Path, allow_synthetic: bool = False) -> list[Problem]:
    problems: list[Problem] = []
    parsed: dict[str, dict[str, object]] = {name: {} for name in FILES}
    raw: dict[str, dict[str, dict]] = {name: {} for name in FILES}

    for name, model in FILES.items():
        for i, rec in enumerate(_load(dir_, name), start=1):
            uid = rec.get("case_uid", f"<{name} line {i}>")
            if uid in raw[name]:
                problems.append(Problem(uid, "ERROR", f"duplicate case_uid in {name}"))
            raw[name][uid] = rec
            try:
                parsed[name][uid] = model.model_validate(rec)
            except ValidationError as e:
                for err in e.errors():
                    loc = ".".join(str(x) for x in err["loc"])
                    problems.append(Problem(uid, "ERROR", f"{name}: {loc}: {err['msg']}"))

    uids = set().union(*(raw[n].keys() for n in FILES))
    if not uids:
        return [Problem("-", "ERROR", f"no records found in {dir_}")]
    for uid in sorted(uids):
        missing = [n for n in FILES if uid not in raw[n]]
        if missing:
            problems.append(Problem(uid, "ERROR", f"missing from {', '.join(missing)}"))

    seen_appeals: dict[str, str] = {}
    for uid in sorted(uids):
        u, g, m = (parsed[n].get(uid) for n in FILES)
        if not (u and g and m):
            continue
        assert isinstance(u, PublicUnspoiled) and isinstance(g, PublicGroundTruth) and isinstance(m, PublicManifest)
        err = lambda msg: problems.append(Problem(uid, "ERROR", msg))  # noqa: E731
        warn = lambda msg: problems.append(Problem(uid, "WARN", msg))  # noqa: E731

        if m.build.method == "SILVER_AUTO" and m.split == "test":
            err("silver (auto-built) cases may not be in the test split")
        if m.build.method == "SYNTHETIC_TEMPLATE" and not allow_synthetic:
            err("synthetic template record in a real DB directory")

        # issues: every framed issue has exactly one finding; no finding for an unknown issue
        issue_ids = [i.id for i in u.issues]
        found = [f.issue for f in g.issue_findings]
        for i in issue_ids:
            if found.count(i) != 1:
                err(f"issue {i} has {found.count(i)} findings (need exactly 1)")
        for f in set(found) - set(issue_ids):
            err(f"finding for unknown issue {f}")

        # dates, split, strata, scope
        if u.law_as_of != g.decision_date - dt.timedelta(days=1):
            err(f"law_as_of {u.law_as_of} should be decision_date - 1 day ({g.decision_date - dt.timedelta(days=1)})")
        if m.strata.year != g.decision_date.year:
            err(f"strata.year {m.strata.year} != decision year {g.decision_date.year}")
        if m.split != expected_split(g.decision_date.year):
            err(f"split '{m.split}' but decision year {g.decision_date.year} belongs to '{expected_split(g.decision_date.year)}'")
        if (m.strata.proceeding_type, m.strata.appellant_role) != (u.proceeding_type, u.appellant_role):
            err("manifest.strata does not match unspoiled proceeding_type/appellant_role")
        if u.proceeding_type in NON_IBC and m.in_scope:
            err(f"{u.proceeding_type} is not IBC but in_scope=true")
        if u.impugned_order.date >= g.decision_date:
            err("impugned order dated on/after the NCLAT decision")
        late = [e.id for e in u.chronology if e.date and e.date >= g.decision_date]
        if late:
            err(f"chronology events on/after the decision date: {late}")

        # page references resolve against the source PDFs
        pages = {s.doc: s.pages for s in m.sources}
        for name, rec in (("unspoiled", raw["unspoiled"][uid]), ("ground_truth", raw["ground_truth"][uid])):
            for s in _srcs(rec):
                doc = s.get("doc", "JUDGMENT")
                if doc not in pages:
                    err(f"{name}: src cites {doc} but manifest has no such source")
                elif s.get("page", 0) > pages[doc]:
                    err(f"{name}: src page {s.get('page')} > {doc} pages {pages[doc]}")

        # anonymisation: nothing from manifest.real may appear in unspoiled
        u_text = json.dumps(raw["unspoiled"][uid], ensure_ascii=False)
        u_lower = u_text.lower()
        identifiers = ([p.name for p in m.real.parties] + m.real.bench_members + m.real.appeal_numbers
                       + m.real.other_identifiers)
        for ident in identifiers:
            if len(ident) >= 4 and ident.lower() in u_lower:
                err(f"identifier from manifest.real appears in unspoiled: {ident!r}")
        if hit := CASE_NUMBER_RE.search(u_text):
            err(f"case/application number pattern in unspoiled: {hit.group(0)!r}")

        # leakage: no 8-word overlap between unspoiled and the decision's reasoning
        sealed = " ".join([g.ratio_decidendi, g.operative_order_verbatim]
                          + [f.holding or "" for f in g.issue_findings])
        overlap = _ngrams(u_text) & _ngrams(sealed)
        if overlap:
            err(f"{len(overlap)} {NGRAM}-gram(s) shared with ground truth, e.g. {' '.join(sorted(overlap)[0])!r}")
        for i in u.issues:
            if w := ISSUE_OUTCOME_WORDS.search(i.text):
                err(f"issue {i.id} is not neutral (contains {w.group(0)!r})")

        # duplicates across cases (connected appeals must be one case)
        for a in m.real.appeal_numbers:
            key = re.sub(r"\W", "", a.lower())
            if key in seen_appeals and seen_appeals[key] != uid:
                err(f"appeal number {a!r} also in {seen_appeals[key]}; connected appeals must be one case")
            seen_appeals[key] = uid

        if m.split == "test" and not m.contamination_probe:
            warn("test case without a contamination probe result")
        if not m.qa.facts_verified:
            warn("qa.facts_verified is false")

    # split lists, if present, must agree with the manifest
    for split in ("train", "dev", "test"):
        path = dir_ / "splits" / f"{split}.txt"
        if path.exists():
            for uid in (ln.strip() for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()):
                m = parsed["manifest"].get(uid)
                if m is None:
                    problems.append(Problem(uid, "ERROR", f"listed in splits/{split}.txt but has no manifest"))
                elif m.split != split:
                    problems.append(Problem(uid, "ERROR", f"listed in splits/{split}.txt but manifest says {m.split}"))
    return problems
