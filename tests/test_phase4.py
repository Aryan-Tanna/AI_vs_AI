"""Phase 4: THEMIS-GLOBAL, bench aggregation, bias swap, metrics, evaluator — fake data, no model calls."""
import asyncio
import json
from pathlib import Path

from lexarena.bench.aggregator import aggregate
from lexarena.bench.bias import swap_report, swap_transcript
from lexarena.config import ROOT, Settings
from lexarena.eval.metrics import binary_metrics, bootstrap_ci, flag_stats, majority_predictor, mcnemar, metadata_predictor
from lexarena.law.authorities import AuthorityRegistry
from lexarena.law.provisions import LawStore
from lexarena.llm.agent import AgentResult
from lexarena.public_db import UnspoiledCase
from lexarena.sources.base import SourceInfo
from lexarena.sources.registry import SourceRegistry
from lexarena.themis.global_ import _strip_verdicts, deterministic_audit, run_global

EXAMPLE = ROOT / "docs" / "schema" / "example"


def case():
    return UnspoiledCase.model_validate(json.loads((EXAMPLE / "unspoiled.json").read_text(encoding="utf-8")))


class _Law:
    info = SourceInfo("law", "law")

    def __init__(self):
        self.store = LawStore.load(ROOT)

    def get(self, provision, as_of):
        return self.store.get(provision, as_of)


class _Seed:
    info = SourceInfo("seed", "authority", court="SC")

    def __init__(self):
        self.reg = AuthorityRegistry([], [{"uid": "SC-BK", "title": "B.K. Educational Services v. Parag Gupta", "year": 2018}])

    def search(self, *a, **k):
        return []

    def status(self, title, cutoff):
        return self.reg.status(title, cutoff, "SC")


def registry():
    return SourceRegistry("eval", [_Seed()], [_Law()], {}, [])


def turn(n, side, claims, flags=()):
    return {"turn": n, "speaker": side, "stage": "s", "prose": f"turn {n}", "flags": list(flags),
            "themis": {"status": "PASSED"}, "claims_extracted": {"claims": claims}}


# ---- THEMIS-GLOBAL -------------------------------------------------------------------------------------

def test_claim_drift_and_reused_flagged_citation_are_found():
    tr = [
        turn(1, "APPELLANT", [{"id": "C1", "kind": "DATE", "text": "Default 31.12.2015", "fact_key": "date_of_default", "date": "2015-12-31"},
                              {"id": "C2", "kind": "AUTHORITY", "text": "Fake v. Case", "authority_title": "Fake v. Case"}],
             flags=[{"code": "ERR_UNVERIFIED_AUTHORITY", "claim": "Fake v. Case", "evidence": "x", "stage": "A"}]),
        turn(2, "RESPONDENT", []),
        turn(3, "APPELLANT", [{"id": "C1", "kind": "DATE", "text": "Default 31.03.2016", "fact_key": "date_of_default", "date": "2016-03-31"},
                              {"id": "C2", "kind": "AUTHORITY", "text": "Fake v. Case again", "authority_title": "Fake v. Case"}]),
    ]
    rep = deterministic_audit(case(), tr, registry())
    assert rep["claim_drift"][0]["side"] == "APPELLANT" and rep["claim_drift"][0]["fact"] == "date_of_default"
    assert rep["flagged_citations_reused"] == [{"side": "APPELLANT", "turn": 3, "authority": "Fake v. Case"}]
    assert rep["per_side"]["APPELLANT"]["flag_counts"] == {"ERR_UNVERIFIED_AUTHORITY": 1}
    # Stage A is re-run on the published claims: the 31.03.2016 default contradicts the record
    assert any(f["code"] == "ERR_FACT_MISMATCH" and f["turn"] == 3 for f in rep["per_side"]["APPELLANT"]["stage_a_findings"])


def test_verdict_wording_is_stripped_from_audit_findings():
    notes = []
    kept = _strip_verdicts("The respondent never answered G2 (turn 1). The appellant has the stronger case.", notes)
    assert kept == "The respondent never answered G2 (turn 1)." and notes


def test_global_llm_output_is_side_symmetric_and_filtered():
    class Fake:
        async def run(self, spec, prompt):
            return AgentResult({"issues": [
                {"issue": "I1", "appellant": {"unanswered_points": [], "contradictions": []},
                 "respondent": {"unanswered_points": ["Did not answer that the balance sheet was unsigned (turn 1). Appeal should be allowed."],
                                "contradictions": []}},
                {"issue": "I9", "appellant": {"unanswered_points": ["x"], "contradictions": []},
                 "respondent": {"unanswered_points": [], "contradictions": []}}]}, "", 1, {}, None, [], "s", "fake")
    rep = asyncio.run(run_global(case(), [turn(1, "APPELLANT", [])], registry(), Fake(), "salt"))
    assert [i["issue"] for i in rep["issues"]] == ["I1"]                            # unknown issue dropped
    assert rep["issues"][0]["respondent"]["unanswered_points"] == ["Did not answer that the balance sheet was unsigned (turn 1)."]
    assert set(rep["issues"][0]) == {"issue", "appellant", "respondent"}


# ---- bench ---------------------------------------------------------------------------------------------

def judgment(label, won, finding="f"):
    return {"judgment": {"issue_decisions": [{"issue": "I1", "finding": finding, "reasons": "r", "record_refs": ["E4"],
                                              "authorities_relied": []}], "label": label, "appellant_won": won, "summary": label},
            "flags": []}


def test_aggregator_majority_label_and_dissent():
    agg = aggregate({"textualist": judgment("ALLOWED_REMANDED", True), "purposive": judgment("ALLOWED", True),
                     "proceduralist": judgment("DISMISSED", False)})
    assert agg["appellant_won"] is True and not agg["unanimous"]
    assert agg["label"] == "ALLOWED_REMANDED"                  # tie between majority labels -> persona order
    assert [d["persona"] for d in agg["dissent"]] == ["proceduralist"]
    assert set(agg["issues"]["I1"]) == {"textualist", "purposive", "proceduralist"}


def test_side_swap_exchanges_labels_everywhere():
    tr = swap_transcript([{"turn": 1, "speaker": "APPELLANT", "prose": "The Appellant says the respondent erred."}])
    assert tr[0]["speaker"] == "RESPONDENT" and tr[0]["prose"] == "The Respondent says the appellant erred."
    rep = swap_report({"issues": [{"issue": "I1", "appellant": {"a": 1}, "respondent": {"r": 1}}]})
    assert rep["issues"][0]["appellant"] == {"r": 1}


# ---- metrics -------------------------------------------------------------------------------------------

def test_binary_metrics_and_baselines():
    m = binary_metrics([(True, True), (False, False), (False, True), (False, False)])
    assert m["accuracy"] == 0.75 and m["balanced_accuracy"] == 0.75 and m["confusion"] == {"tp": 1, "tn": 2, "fp": 0, "fn": 1}
    assert majority_predictor([False, False, True])({}) is False
    meta = metadata_predictor([("SEC7_ADMISSION", "SUSPENDED_DIRECTOR_PROMOTER", False)] * 3 + [("SEC9_ADMISSION", "OTHER", True)] * 3)
    assert meta({"proceeding_type": "SEC9_ADMISSION", "appellant_role": "OTHER"}) is True
    assert meta({"proceeding_type": "SEC7_ADMISSION", "appellant_role": "SUSPENDED_DIRECTOR_PROMOTER"}) is False
    lo, hi = bootstrap_ci([(True, True), (False, False)] * 10)
    assert lo <= hi
    assert mcnemar([True, True, False], [False, False, False], [True, True, False])["a_only_correct"] == 2


def test_flag_stats_rates():
    st = flag_stats([{"turns": [turn(1, "APPELLANT", [], [{"code": "ERR_UNKNOWN_RECORD_REF"}]), turn(2, "RESPONDENT", [])]}])
    assert st["APPELLANT"]["unsupported_fact_rate"] == 1.0 and st["RESPONDENT"]["unsupported_fact_rate"] == 0.0


def test_evaluator_scores_a_run_against_sealed_ground_truth(tmp_path):
    from lexarena.eval.evaluate import evaluate
    db = tmp_path / "db"
    (db / "splits").mkdir(parents=True)
    u = json.loads((EXAMPLE / "unspoiled.json").read_text(encoding="utf-8"))
    g = json.loads((EXAMPLE / "ground_truth.json").read_text(encoding="utf-8"))
    rows_u, rows_g = [], []
    for i, won in enumerate([False, False, True, False]):                      # PC-T0..T2 train, PC-T3 dev
        uid = f"PC-T{i}"
        rows_u.append(json.dumps({**u, "case_uid": uid}))
        rows_g.append(json.dumps({**g, "case_uid": uid, "appellant_won": won, "label": "ALLOWED" if won else "DISMISSED"}))
    (db / "unspoiled.jsonl").write_text("\n".join(rows_u), encoding="utf-8")
    (db / "ground_truth.jsonl").write_text("\n".join(rows_g), encoding="utf-8")
    (db / "splits" / "train.txt").write_text("PC-T0\nPC-T1\nPC-T2\n", encoding="utf-8")
    (db / "splits" / "dev.txt").write_text("PC-T3\n", encoding="utf-8")
    run = tmp_path / "runs" / "r1" / "PC-T3"
    run.mkdir(parents=True)
    (run / "verdict.json").write_text(json.dumps({"label": "DISMISSED", "appellant_won": False}), encoding="utf-8")
    (run / "baseline.json").write_text(json.dumps({"prediction": {"appellant_won": True}}), encoding="utf-8")
    res = evaluate(Settings(public_db_dir=db, runs_dir=tmp_path / "runs", data_dir=tmp_path / "data"), "r1", "dev")
    assert res["cases_scored"] == 1 and res["outcome"]["system"]["accuracy"] == 1.0
    assert res["outcome"]["single_llm"]["accuracy"] == 0.0 and res["outcome"]["majority"]["accuracy"] == 1.0
    assert (tmp_path / "runs" / "r1" / "metrics.md").exists()


def test_runtime_code_never_imports_ground_truth():
    runtime = [p for d in ("agents", "tools", "themis", "bench", "orchestrator", "sources", "llm", "session")
               for p in (ROOT / "lexarena" / d).glob("*.py")] + [ROOT / "lexarena" / "public_db.py"]
    offenders = [p.name for p in runtime if "ground_truth" in p.read_text(encoding="utf-8") and "eval" in p.read_text(encoding="utf-8")
                 and "lexarena.eval" in p.read_text(encoding="utf-8")]
    assert offenders == []
