"""Authority lookup for citation checks (CLAUDE.md §6.4, §8.3).

Sources: the reference DB (NCLAT decisions, exact dates) and the SC seed (data/seed/sc_landmarks.json, year
only, unverified). This is a stand-in for the authority table (build step J): it can say whether an authority
is known and whether it post-dates the cutoff, but treatment (reversed/overruled as of a date) is only the
undated source flag until step J.
"""
import datetime as dt
import json
import re
from dataclasses import dataclass
from pathlib import Path

from rapidfuzz import fuzz, process

NOISE = re.compile(r"\b(m/s|ltd|limited|pvt|private|the|and|anr|ors|others|another|co|company|corp|corporation|inc|"
                   r"llp|india|of|for|through|its|rp|irp)\b")
MATCH_THRESHOLD = 85


def norm_title(t: str) -> str:
    t = (t or "").lower().replace("&", " and ")
    t = re.sub(r"\b(vs?\.?|versus)\b", " v ", t)
    t = re.sub(r"[^a-z0-9 ]", " ", t)
    return re.sub(r"\s+", " ", NOISE.sub(" ", t)).strip()


@dataclass
class AuthorityStatus:
    query: str
    found: bool
    source: str | None = None           # REFERENCE | SC_SEED
    uid: str | None = None
    title: str | None = None
    date: str | None = None             # exact date (reference DB) or None
    year: int | None = None
    anachronistic: bool = False         # decided on/after the cutoff
    same_year_unknown: bool = False     # seed year equals cutoff year: cannot tell
    treatment_note: str | None = None
    verified: bool = False
    match_score: float = 0.0
    proposition: str | None = None

    def to_dict(self) -> dict:
        return self.__dict__.copy()


class AuthorityRegistry:
    def __init__(self, reference_cases: list[dict], seed: list[dict]):
        self.entries: list[dict] = []
        for c in reference_cases:
            self.entries.append({"source": "REFERENCE", "uid": c["case_uid"], "title": c["title"],
                                 "date": c["decision_date"], "year": int(c["decision_date"][:4]),
                                 "overruled": c.get("is_overruled_raw", False),
                                 "proposition": (c.get("propositions") or [None])[0]})
        for s in seed:
            self.entries.append({"source": "SC_SEED", "uid": s["uid"], "title": s["title"], "date": None,
                                 "year": s["year"], "overruled": False, "proposition": s.get("proposition")})
        self.keys = [norm_title(e["title"]) for e in self.entries]

    @classmethod
    def load(cls, reference_path: Path, seed_path: Path) -> "AuthorityRegistry":
        cases = ([json.loads(x) for x in reference_path.read_text(encoding="utf-8").splitlines() if x.strip()]
                 if reference_path.exists() else [])
        seed = json.loads(seed_path.read_text(encoding="utf-8"))["authorities"] if seed_path.exists() else []
        return cls(cases, seed)

    def _best(self, q: str, source: str | None) -> tuple[dict, float] | None:
        idx = [i for i, e in enumerate(self.entries) if source is None or e["source"] == source]
        hit = process.extractOne(q, [self.keys[i] for i in idx], scorer=fuzz.token_sort_ratio, score_cutoff=MATCH_THRESHOLD)
        return (self.entries[idx[hit[2]]], hit[1]) if hit else None

    def status(self, title: str, cutoff: dt.date, court: str | None = None) -> AuthorityStatus:
        """`court`: SC or NCLAT when the citation says so. The same parties often appear in an NCLAT decision and
        the Supreme Court appeal from it, so the court decides which record is meant; without it, the SC seed
        is preferred and the alternative is noted."""
        q = norm_title(title)
        st = AuthorityStatus(query=title, found=False)
        if not q:
            return st
        court = (court or "").upper()
        if court == "SC":
            best = self._best(q, "SC_SEED")
        elif court == "NCLAT":
            best = self._best(q, "REFERENCE")
        else:
            best = self._best(q, "SC_SEED") or self._best(q, "REFERENCE")
            if best and best[0]["source"] == "SC_SEED" and self._best(q, "REFERENCE"):
                st.treatment_note = "An NCLAT decision with the same parties also exists; the SC judgment is assumed"
        if best is None:
            return st
        e, score = best
        hit = (None, score)
        st.found, st.source, st.uid, st.title, st.year = True, e["source"], e["uid"], e["title"], e["year"]
        st.date, st.match_score, st.proposition = e["date"], hit[1], e["proposition"]
        if e["date"]:
            st.anachronistic = dt.date.fromisoformat(e["date"]) >= cutoff
        else:
            st.anachronistic = e["year"] > cutoff.year
            st.same_year_unknown = e["year"] == cutoff.year
        if e["overruled"]:
            st.treatment_note = "Source DB marks this decision as overruled (undated, unverified)"
        st.verified = False
        return st
