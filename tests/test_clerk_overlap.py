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


def person(name: str, role: str | None) -> NamedEntity:
    return NamedEntity.model_validate({"name": name, "variants": [], "kind": "PERSON", "cause_title_role": role})


def test_a_person_matches_only_on_the_full_name() -> None:
    payloads = [
        prec("P-7", "Ashok Kumar Gulla vs. A Bank", "<n>"),
        prec("P-8", "Someone vs. Ashok Kumar Bhati", "<n>"),
    ]
    found = find_overlaps(
        payloads, [person("Ashok Kumar Bhati", "RESPONDENT_2")], case_numbers=set(), generic_words=GENERIC
    )
    assert [o.precedent_id for o in found] == ["P-8"]


def test_a_company_named_anywhere_counts_but_counsel_and_bench_never_do() -> None:
    debtor = NamedEntity.model_validate(
        {"name": "Vorn Rathe Steels Mills", "variants": [], "kind": "COMPANY", "cause_title_role": None}
    )
    payloads = [
        prec("P-9", "A Creditor vs. Vorn Rathe Steels Mills", "<n>"),
        prec("P-10", "Qelto Varn vs. Someone", "<n>"),
    ]
    counsel = person("Qelto Varn", None)
    found = find_overlaps(payloads, [debtor, counsel], case_numbers=set(), generic_words=GENERIC)
    assert [o.precedent_id for o in found] == ["P-9"]


def test_an_organisation_match_needs_its_leading_word() -> None:
    debtor = NamedEntity.model_validate(
        {"name": "Vorn Rathe Steels Rolling Mills", "variants": [], "kind": "COMPANY", "cause_title_role": None}
    )
    payloads = [
        prec("P-11", "Kelta Steel Rolling Mills vs. Someone", "<n>"),  # industry words only
        prec("P-12", "Rathe Powertech vs. Someone", "<n>"),  # a second word without the leading one
        prec("P-13", "A Creditor vs. Vorn Rathe Steels", "<n>"),
    ]
    found = find_overlaps(payloads, [debtor], case_numbers=set(), generic_words=GENERIC)
    assert [o.precedent_id for o in found] == ["P-13"]


def test_a_bank_or_authority_never_matches_on_its_name_alone() -> None:
    bank = NamedEntity.model_validate(
        {"name": "Zorvex Quillon Bank", "variants": [], "kind": "BANK", "cause_title_role": "APPELLANT"}
    )
    payloads = [
        prec("P-14", "Zorvex Quillon Bank vs. Some Debtor", "<appeal> No. 1 of 1999"),
        prec("P-15", "Zorvex Quillon Bank vs. Our Debtor", "<appeal> No. 972 of 2020"),
    ]
    found = find_overlaps(payloads, [bank], case_numbers={("972", "2020")}, generic_words=GENERIC)
    assert [o.precedent_id for o in found] == ["P-15"]


def test_a_person_matches_on_any_spelling_the_judgment_uses() -> None:
    rp = NamedEntity.model_validate(
        {"name": "Qorin Bhatacharya", "variants": ["Qorin Bhattacharya"], "kind": "PERSON", "cause_title_role": "R1"}
    )
    found = find_overlaps(
        [prec("P-16", "A Bank vs Qorin Bhattacharya", "<n>")], [rp], case_numbers=set(), generic_words=GENERIC
    )
    assert [o.precedent_id for o in found] == ["P-16"]
