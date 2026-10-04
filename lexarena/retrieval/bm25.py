"""BM25 with a legal tokenizer: section, article, rule and regulation references become single tokens
("Section 29A", "s. 29A", "Sec.29A" -> sec_29a), so exact provision numbers match."""
import math
import re
from collections import Counter, defaultdict

REF = re.compile(r"\b(?:(section|sec|s|article|art|rule|r|regulation|reg)\.?\s*(\d+[a-z]{0,2}))\b", re.I)
REF_KIND = {"section": "sec", "sec": "sec", "s": "sec", "article": "art", "art": "art", "rule": "rule", "r": "rule",
            "regulation": "reg", "reg": "reg"}
STOP = set("the a an of to in and or for on by with as is was be been are that this which from at it its into "
           "under such any not no whether shall may has have had".split())


def tokenize(text: str) -> list[str]:
    text = REF.sub(lambda m: f" {REF_KIND[m.group(1).lower()]}_{m.group(2).lower()} ", text or "")
    return [t for t in re.findall(r"[a-z]+_[0-9a-z]+|[a-z0-9]+", text.lower()) if t not in STOP and len(t) > 1]


class BM25:
    def __init__(self, docs: list[str], k1: float = 1.5, b: float = 0.75):
        self.k1, self.b = k1, b
        self.tf: list[Counter] = [Counter(tokenize(d)) for d in docs]
        self.len = [sum(c.values()) for c in self.tf]
        self.avg = (sum(self.len) / len(self.len)) if self.len else 0.0
        self.post: dict[str, list[int]] = defaultdict(list)
        for i, c in enumerate(self.tf):
            for t in c:
                self.post[t].append(i)
        n = len(docs)
        self.idf = {t: math.log(1 + (n - len(p) + 0.5) / (len(p) + 0.5)) for t, p in self.post.items()}

    def scores(self, query: str, allowed: set[int] | None = None) -> dict[int, float]:
        out: dict[int, float] = defaultdict(float)
        for t in set(tokenize(query)):
            idf = self.idf.get(t)
            if idf is None:
                continue
            for i in self.post[t]:
                if allowed is not None and i not in allowed:
                    continue
                f = self.tf[i][t]
                out[i] += idf * f * (self.k1 + 1) / (f + self.k1 * (1 - self.b + self.b * self.len[i] / (self.avg or 1)))
        return out
