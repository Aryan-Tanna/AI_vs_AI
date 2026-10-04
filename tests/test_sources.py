"""Dynamic sources: config-driven registry, generic JSONL DBs, eval/live mode rules, web permissions."""
import datetime as dt
import json

import pytest

from lexarena.ingest.build_reference import apply_mapping
from lexarena.sources.registry import SourceRegistry, register_source_type

D = dt.date


def write_config(tmp_path, body: str):
    p = tmp_path / "sources.yaml"
    p.write_text(body, encoding="utf-8")
    return p


@pytest.fixture
def other_db(tmp_path):
    rows = [{"doc_id": "X1", "case_name": "Kappa Ltd v. Lambda Bank", "judgment_date": "2019-03-01", "holding": "Balance sheet entry is an acknowledgment under section 18."},
            {"doc_id": "X2", "case_name": "Mu v. Nu", "judgment_date": "2023-03-01", "holding": "Balance sheet acknowledgment section 18 later view."}]
    (tmp_path / "other.jsonl").write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
    return tmp_path


GENERIC = """
authority_sources:
  - name: other_court
    type: generic_jsonl
    path: other.jsonl
    court: HC
    fields: {id: doc_id, title: case_name, date: judgment_date, text: [holding]}
law_sources: []
web:
  law_fetch_domains: [indiacode.nic.in]
  law_fetch_modes: [eval, live]
  case_law_search_modes: [live]
"""


def test_any_jsonl_db_is_searchable_with_a_mapping_and_respects_cutoff(other_db):
    reg = SourceRegistry.from_config(write_config(other_db, GENERIC), "eval", root=other_db)
    hits = reg.search("balance sheet acknowledgment section 18", cutoff=D(2020, 1, 1), exclude=set())
    assert [h["title"] for h in hits] == ["Kappa Ltd v. Lambda Bank"]          # the 2023 decision is after the cutoff
    assert hits[0]["source"] == "other_court" and hits[0]["court"] == "HC"
    assert reg.authorities.status("Kappa v. Lambda Bank", D(2020, 1, 1)).found


def test_eval_mode_rejects_sources_that_ignore_the_cutoff(tmp_path):
    cfg = write_config(tmp_path, """
authority_sources:
  - {name: open_api, type: generic_jsonl, path: x.jsonl, fields: {title: t, date: d, text: [x]}, respects_cutoff: false}
""")
    with pytest.raises(ValueError, match="cannot be enabled in eval"):
        SourceRegistry.from_config(cfg, "eval", root=tmp_path)
    assert SourceRegistry.from_config(cfg, "live", root=tmp_path).authority_sources       # fine in live mode


def test_web_permissions_by_mode(other_db):
    cfg = write_config(other_db, GENERIC)
    tools, rules = SourceRegistry.from_config(cfg, "eval", root=other_db).web_permissions()
    assert tools == ["WebFetch"] and rules == ["WebFetch(domain:indiacode.nic.in)", "WebFetch(domain:www.indiacode.nic.in)"]
    tools, rules = SourceRegistry.from_config(cfg, "live", root=other_db).web_permissions()
    assert "WebSearch" in tools and "WebSearch" in rules


def test_custom_source_type_plugs_in(tmp_path):
    from lexarena.law.authorities import AuthorityStatus
    from lexarena.sources.base import SourceInfo

    class Api:
        def __init__(self, cfg, root):
            self.info = SourceInfo(cfg["name"], "authority", court="SC")

        def search(self, query, *, cutoff, exclude, provisions, k):
            return [{"title": "From an API", "decision_date": "2001-01-01", "text": "t"}]

        def status(self, title, cutoff):
            return AuthorityStatus(query=title, found=False)

    register_source_type("my_api", Api)
    reg = SourceRegistry.from_config(write_config(tmp_path, "authority_sources:\n  - {name: api, type: my_api}\n"), "eval", root=tmp_path)
    assert reg.search("anything", cutoff=D(2020, 1, 1), exclude=set())[0]["title"] == "From an API"


def test_unknown_authority_is_a_note_in_live_mode():
    import json as _j
    from pathlib import Path
    from lexarena.config import ROOT
    from lexarena.law.authorities import AuthorityRegistry
    from lexarena.law.provisions import LawStore
    from lexarena.public_db import UnspoiledCase
    from lexarena.themis.claims import ClaimSet
    from lexarena.themis.stage_a import StageA
    case = UnspoiledCase.model_validate(_j.loads((ROOT / "docs/schema/example/unspoiled.json").read_text(encoding="utf-8")))
    claim = ClaimSet.model_validate({"claims": [{"id": "C1", "kind": "AUTHORITY", "text": "x", "authority_title": "Web Only v. Case"}]})
    live = StageA(case, LawStore.load(ROOT), AuthorityRegistry([], []), mode="live").run(claim)
    ev = StageA(case, LawStore.load(ROOT), AuthorityRegistry([], []), mode="eval").run(claim)
    assert live.findings == [] and "unverified" in live.notes[0]["note"]
    assert [f.code for f in ev.findings] == ["ERR_UNVERIFIED_AUTHORITY"]


def test_ingest_field_mapping():
    raw = {"id": "A1", "name": "P v. Q", "date": "2020-01-01", "outcome": "DISMISSED", "_file": "f"}
    out = apply_mapping(raw, {"case_title": "name", "decision_date": "date", "final_order": "outcome"}, id_field="id")
    assert out["case_title"] == "P v. Q" and out["decision_date"] == "2020-01-01" and out["precedent_id"] == "A1"


def test_project_config_loads_in_both_modes():
    from lexarena.config import ROOT
    for mode in ("eval", "live"):
        reg = SourceRegistry.from_config(ROOT / "config" / "sources.yaml", mode)
        assert {s.info.name for s in reg.authority_sources} >= {"sc_seed", "nclat_reference"}
        assert "mode=" + mode in reg.describe()
