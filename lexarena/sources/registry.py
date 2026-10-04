"""SourceRegistry: builds the enabled sources from config/sources.yaml for the current mode and exposes one
search / status / provision interface to tools and THEMIS.

Modes:
  eval - evaluation runs on historical cases. Only sources that respect the cutoff; web restricted to fetching
         statutory material from the configured official domains; no case-law web search.
  live - new matters with no answer key: every enabled source, case-law web search, external MCP servers.
"""
import datetime as dt
from functools import lru_cache
from pathlib import Path

import yaml

from lexarena.config import ROOT, Settings
from lexarena.law.authorities import AuthorityStatus
from lexarena.law.provisions import ProvisionAnswer, resolve
from lexarena.sources.base import Mode
from lexarena.sources.builtin import BUILTIN_TYPES

_TYPES = dict(BUILTIN_TYPES)
RRF_K = 60


def register_source_type(name: str, factory) -> None:
    """Plug in a new storage kind (SQL, MongoDB, a REST API, ...): factory(cfg: dict, root: Path) -> source."""
    _TYPES[name] = factory


class _Authorities:
    def __init__(self, sources: list):
        self.sources = sources

    def status(self, title: str, cutoff: dt.date, court: str | None = None) -> AuthorityStatus:
        """First match in config order, restricted to the named court when the citation gives one."""
        court = (court or "").upper() or None
        pool = [s for s in self.sources if court is None or (s.info.court or "").upper() == court] or self.sources
        found: list[AuthorityStatus] = []
        for s in pool:
            st = s.status(title, cutoff)
            if st.found:
                st.source = s.info.name
                found.append(st)
        if not found:
            return AuthorityStatus(query=title, found=False)
        best = found[0]
        if len(found) > 1 and not best.treatment_note:
            best.treatment_note = f"Also matched in {', '.join(f.source for f in found[1:])}; {best.source} assumed"
        return best


class _Law:
    def __init__(self, sources: list):
        self.sources = sources

    def get(self, provision: str, as_of: dt.date) -> ProvisionAnswer:
        answers = [s.get(provision, as_of) for s in self.sources]
        found = [a for a in answers if a.found]
        if found:
            return found[0]
        return answers[0] if answers else ProvisionAnswer(resolve(provision)[1], False, None, note="No law source configured")


class SourceRegistry:
    def __init__(self, mode: Mode, authority_sources: list, law_sources: list, web: dict, mcp_servers: list[dict]):
        self.mode = mode
        self.authority_sources = authority_sources
        self.law_sources = law_sources
        self.authorities = _Authorities(authority_sources)
        self.law = _Law(law_sources)
        self.web = web
        self.mcp_servers = mcp_servers

    @classmethod
    def from_config(cls, path: Path, mode: Mode, root: Path = ROOT) -> "SourceRegistry":
        cfg = yaml.safe_load(path.read_text(encoding="utf-8")) or {}

        def build(entries: list[dict]) -> list:
            out = []
            for e in entries or []:
                if mode not in e.get("modes", ["eval", "live"]):
                    continue
                if mode == "eval" and not e.get("respects_cutoff", True):
                    raise ValueError(f"source '{e['name']}' does not respect the cutoff and cannot be enabled in eval mode")
                if e["type"] not in _TYPES:
                    raise ValueError(f"unknown source type '{e['type']}' for '{e['name']}'; known: {sorted(_TYPES)}")
                out.append(_TYPES[e["type"]](e, root))
            return out

        web = cfg.get("web", {}) or {}
        mcp = [m for m in cfg.get("mcp_servers", []) or [] if mode in m.get("modes", ["live"])
               and (mode == "live" or m.get("respects_cutoff", False))]
        return cls(mode, build(cfg.get("authority_sources")), build(cfg.get("law_sources")), web, mcp)

    # -- search across every enabled authority source, fused by reciprocal rank ------------------------------
    def search(self, query: str, *, cutoff: dt.date, exclude: set[str], provisions: tuple[str, ...] = (), k: int = 6) -> list[dict]:
        fused: dict[tuple, tuple[float, dict]] = {}
        for s in self.authority_sources:
            for rank, h in enumerate(s.search(query, cutoff=cutoff, exclude=exclude, provisions=provisions, k=k)):
                h = {**h, "source": s.info.name, "court": h.get("court") or s.info.court}
                key = (h["title"].lower(), str(h.get("decision_date")))
                score = 1.0 / (RRF_K + rank)
                if key in fused:
                    score += fused[key][0]
                fused[key] = (score, h if key not in fused else fused[key][1])
        ranked = sorted(fused.values(), key=lambda x: -x[0])[:k]
        return [{kk: v for kk, v in h.items() if kk not in ("case_uid", "score")} for _, h in ranked]

    # -- web capabilities for agents (Claude Code built-in tools, permission-scoped) -------------------------
    def web_permissions(self) -> tuple[list[str], list[str]]:
        """(built-in tools to enable, permission rules to allow) for the current mode."""
        tools, rules = [], []
        if self.mode in self.web.get("law_fetch_modes", []):
            domains = self.web.get("law_fetch_domains", [])
            if domains:
                tools.append("WebFetch")
                # the rule matches the exact host, so allow both the bare and the www. form
                rules += [f"WebFetch(domain:{h})" for d in domains for h in (d, d if d.startswith("www.") else f"www.{d}")]
        if self.mode in self.web.get("case_law_search_modes", []):
            tools += ["WebSearch", "WebFetch"]
            rules += ["WebSearch", "WebFetch"]
        return sorted(set(tools)), sorted(set(rules))

    def describe(self) -> str:
        auth = ", ".join(f"{s.info.name} ({s.info.court or 'mixed'})" for s in self.authority_sources) or "none"
        law = ", ".join(s.info.name for s in self.law_sources) or "none"
        tools, _ = self.web_permissions()
        web = ("official statutory sites only: " + ", ".join(self.web.get("law_fetch_domains", []))) if tools == ["WebFetch"] \
            else ("open web search" if "WebSearch" in tools else "none")
        return f"mode={self.mode}; authority sources: {auth}; law sources: {law}; web: {web}"


@lru_cache(maxsize=4)
def _cached(path: Path, mode: str, root: Path) -> SourceRegistry:
    return SourceRegistry.from_config(path, mode, root)


def get_registry(settings: Settings) -> SourceRegistry:
    return _cached(settings.sources_file, settings.mode, ROOT)
