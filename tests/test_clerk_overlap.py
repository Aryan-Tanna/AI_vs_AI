"""Precedent overlap check (SPEC B1, D-019, D-020, D-056) and the memorisation verdict. Placeholder names only."""

from __future__ import annotations

from lexarena.clerk.overlap import appeal_numbers, find_overlaps, probe_identified
from lexarena.schemas.clerk import NamedEntity

GENERIC = ["ltd", "pvt", "limited", "private", "bank", "of", "india", "the", "and"]


def party(name: str, role: str | None = "RESPONDENT_1") -> NamedEntity:
    return NamedEntity.model_validate({"name": name, "variants": [], "kind": "COMPANY", "cause_title_role": role})


def prec(pid: str, title: str, appeal: str, decided: str = "2003-01-01") -> dict[str, str]:
    return {
        "precedent_id": pid,
        "precedent_uid": f"{pid}#u",
        "case_title": title,
        "appeal_number": appeal,
        "decision_date": decided,
    }


def test_appeal_numbers_are_read_in_both_common_forms() -> None:
    assert appeal_numbers("Company Appeal (AT) (Insolvency) No. 972 of 2020 & I.A. No. 31/2021") == {
        ("972", "2020"),
        ("31", "2021"),
    }


def test_same_parties_or_same_corporate_debtor_are_excluded() -> None:
    parties = [party("Zorvex Quillon Bank", "APPELLANT"), party("Pellam Tarsh Seeds Pvt Ltd")]
    payloads = [
        prec("P-1", "Zorvex Quillon Bank vs. Pellam Tarsh Seeds Pvt Ltd", "<appeal> No. 5 of 2001"),
        prec("P-2", "Another Creditor vs. Pellam Tarsh Seeds Pvt. Ltd.", "<appeal> No. 9 of 2004"),
        prec("P-3", "Unrelated Mills vs. Qarno Vell Ltd", "<appeal> No. 7 of 2002"),
    ]
    found = find_overlaps(payloads, parties, case_numbers=set(), generic_words=GENERIC)
    assert {o.precedent_id for o in found} == {"P-1", "P-2"}
    assert next(o for o in found if o.precedent_id == "P-2").reason.startswith("party")


def test_a_shared_appeal_number_with_a_shared_party_word_is_excluded() -> None:
    payloads = [prec("P-4", "Pellam Holdings vs. Someone", "Company Appeal No. 972 of 2020")]
    found = find_overlaps(
        payloads, [party("Pellam Tarsh Seeds")], case_numbers={("972", "2020")}, generic_words=GENERIC
    )
    assert [o.precedent_id for o in found] == ["P-4"]


def test_a_shared_appeal_number_alone_is_not_enough() -> None:
    """Numbers like '972 of 2020' recur across benches and kinds of case."""
    payloads = [prec("P-5", "Different Parties vs. Others", "C.P. No. 972 of 2020")]
    assert (
        find_overlaps(payloads, [party("Pellam Tarsh Seeds")], case_numbers={("972", "2020")}, generic_words=GENERIC)
        == []
    )


def test_generic_words_never_match_on_their_own() -> None:
    payloads = [prec("P-6", "State Bank of India vs. Someone Else", "<appeal>")]
    assert find_overlaps(payloads, [party("Bank of India")], case_numbers=set(), generic_words=GENERIC) == []


def test_the_probe_counts_as_identified_only_when_it_names_a_real_party_or_number() -> None:
    parties = [party("Pellam Tarsh Seeds")]
    assert probe_identified("This looks like Pellam Tarsh v. a bank", parties, {("972", "2020")}, GENERIC)
    assert probe_identified("Appeal No. 972 of 2020", parties, {("972", "2020")}, GENERIC)
    assert not probe_identified("A limitation dispute between a bank and a company", parties, set(), GENERIC)
