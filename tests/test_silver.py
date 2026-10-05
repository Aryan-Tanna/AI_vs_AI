"""Silver DB builder (no model calls): anonymisation, outcome-leak removal, splits, test-pool exclusion, validity."""
import json

from lexarena.ingest.build_silver import build
from lexarena.public_db_validate import validate_dir


def ref(uid, title, date, facts, issues, label="DISMISSED", statutes=("IBC_2016_SEC_9",), appeal="Company Appeal (AT) (Ins) No. 1 of 2020"):
    return {"case_uid": uid, "title": title, "decision_date": date, "bench_city": "NEW_DELHI", "label": label, "ibc": True,
            "statutes": list(statutes), "material_facts": facts, "legal_issues": issues,
            "ratio_decidendi": "A plausible pre-existing dispute bars admission of a Section 9 application under the Code.",
            "operative_order": "The appeal is dismissed. No costs.", "appeal_numbers": [appeal],
            "source": {"raw_precedent_ids": [uid]}}


FACTS = ("Alpha Steel Pvt. Ltd. supplied goods to Beta Builders Ltd. under purchase orders. "
         "Alpha Steel issued a demand notice under Section 8 on 05.01.2019. "
         "The Section 9 application filed by the Appellant in CP (IB) No. 55 of 2019 was rejected by NCLT Mumbai on 10.02.2020. "
         "This Appellate Tribunal dismissed the appeal holding that a dispute existed.")


def test_builds_valid_anonymised_case_without_outcome(tmp_path):
    refs = [ref("REF-1", "Alpha Steel Pvt. Ltd. vs. Beta Builders Ltd.", "2021-03-01", FACTS,
                ["Whether the NCLT erred in holding that a pre-existing dispute existed between the parties"])]
    stats = build(refs, tmp_path)
    assert stats["built"] == 1 and stats["validator_errors"] == 0
    u = json.loads((tmp_path / "unspoiled.jsonl").read_text(encoding="utf-8"))
    text = json.dumps(u)
    assert "Alpha Steel" not in text and "Beta Builders" not in text and "[APPELLANT_1]" in text
    assert "CP (IB) No. 55" not in text and "[CASE_NUMBER]" in text
    assert "Appellate Tribunal dismissed" not in text                     # the NCLAT's own outcome is dropped
    assert u["impugned_order"]["date"] == "2020-02-10" and u["impugned_order"]["outcome_below"] == "REJECTED"
    assert u["impugned_order"]["bench_city"] == "MUMBAI"
    assert "erred" not in u["issues"][0]["text"]                           # neutralised
    assert u["appellant_role"] == "OPERATIONAL_CREDITOR"                   # s.9 application filed by the appellant
    m = json.loads((tmp_path / "manifest.jsonl").read_text(encoding="utf-8"))
    assert m["split"] == "train" and m["build"]["method"] == "SILVER_AUTO"
    assert m["overlap_with_reference_db"]["reference_case_uids"] == ["REF-1"]   # excluded from its own retrieval
    assert [p.level for p in validate_dir(tmp_path)].count("ERROR") == 0


def test_test_pool_years_are_kept_out_and_2024_goes_to_dev(tmp_path):
    refs = [ref("REF-1", "Alpha Steel Pvt. Ltd. vs. Beta Builders Ltd.", "2024-05-01", FACTS, ["Whether a pre-existing dispute existed"]),
            ref("REF-2", "Gamma Ltd. vs. Delta Ltd.", "2025-05-01", FACTS.replace("Alpha Steel", "Gamma"),
                ["Whether a pre-existing dispute existed"], appeal="Company Appeal (AT) (Ins) No. 2 of 2025")]
    stats = build(refs, tmp_path)
    assert stats["eligible_ibc_until_2024"] == 1 and stats["dev"] == 1 and stats["train"] == 0
    assert (tmp_path / "splits" / "test.txt").read_text(encoding="utf-8") == ""


def test_case_without_nclt_order_is_skipped_with_reason(tmp_path):
    refs = [ref("REF-1", "Alpha Steel Pvt. Ltd. vs. Beta Builders Ltd.", "2021-03-01",
                "Alpha Steel issued a demand notice on 05.01.2019.", ["Whether a pre-existing dispute existed"])]
    stats = build(refs, tmp_path)
    assert stats["built"] == 0 and stats["skipped"] == {"no NCLT order found in the facts": 1}
