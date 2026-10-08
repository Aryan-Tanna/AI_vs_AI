"""Clerk pseudonyms and pre-extraction scans (SPEC A4, H0, H5 rule 12, I3-9; D-056). Deterministic.

Placeholder names only, built from invented words (non-negotiable 1, D-033).
"""

from __future__ import annotations

import pytest

from lexarena.clerk.names import Pseudonymizer, acronym, assign_pseudonyms, residual_names
from lexarena.clerk.scan import citation_hits, court_voice_hits
from lexarena.schemas.clerk import NamedEntity

GENERIC = {"ltd", "limited", "pvt", "private", "bank", "of", "the", "and", "india", "m/s", "mr", "ms"}


def entity(name: str, kind: str = "COMPANY", variants: list[str] | None = None) -> NamedEntity:
    return NamedEntity.model_validate({"name": name, "variants": variants or [], "kind": kind})


ZORVEX = entity("Zorvex Quillon Bank of India", "BANK", ["Zorvex Bank", "ZQB"])
PELLAM = entity("Pellam Tarsh Seeds Pvt. Ltd.", "COMPANY", ["Pellam Tarsh"])
VANDU = entity("Mr. Ostrel Vandu", "PERSON", ["Ostrel Vandu", "Mr. Vandu"])


def pseudo(*entities: NamedEntity) -> Pseudonymizer:
    return Pseudonymizer(assign_pseudonyms(list(entities), case_key="CASE-X", seed=7), GENERIC)


def test_pseudonyms_are_fresh_per_case_and_stable_within_one() -> None:
    a = assign_pseudonyms([ZORVEX, PELLAM], case_key="CASE-X", seed=7)
    b = assign_pseudonyms([ZORVEX, PELLAM], case_key="CASE-X", seed=7)
    c = assign_pseudonyms([ZORVEX, PELLAM], case_key="CASE-Y", seed=7)
    assert a == b
    assert [p.pseudonym for p in a] != [p.pseudonym for p in c]
    assert len({p.pseudonym for p in a}) == 2


def test_pseudonym_names_the_kind_only() -> None:
    [bank, person] = assign_pseudonyms([ZORVEX, VANDU], case_key="CASE-X", seed=7)
    assert bank.pseudonym.startswith("Bank-") and person.pseudonym.startswith("Person-")


def test_every_variant_is_replaced_longest_first() -> None:
    p = pseudo(ZORVEX, PELLAM)
    [bank, company] = p.assigned
    text = "Zorvex Quillon Bank of India lent to Pellam Tarsh Seeds Pvt. Ltd.; Zorvex Bank later sued Pellam Tarsh."
    out = p.apply(text)
    assert out == (f"{bank.pseudonym} lent to {company.pseudonym}; {bank.pseudonym} later sued {company.pseudonym}.")


def test_case_prefixes_and_possessives_are_handled() -> None:
    p = pseudo(PELLAM)
    [company] = p.assigned
    out = p.apply("M/s. PELLAM TARSH SEEDS PVT. LTD. and Pellam Tarsh's director")
    assert out == f"{company.pseudonym} and {company.pseudonym}'s director"


def test_acronyms_are_replaced_case_sensitively_only() -> None:
    p = pseudo(ZORVEX)
    [bank] = p.assigned
    assert p.apply("the ZQB notice") == f"the {bank.pseudonym} notice"
    assert p.apply("zqb") == "zqb"
    assert acronym("Zorvex Quillon Bank of India") == "ZQBI"
    assert acronym("Zorvex Bank Of India") == "ZBI"  # function words never count, whatever their case


def test_names_inside_longer_words_are_untouched() -> None:
    p = pseudo(VANDU)
    assert p.apply("Vanduland and OstrelVandu") == "Vanduland and OstrelVandu"


def test_residual_scan_catches_a_name_the_variant_list_missed() -> None:
    """The scan reads the original names, not the variant list, so an unlisted form still shows."""
    p = pseudo(PELLAM)
    leaked = p.apply("Tarsh Seeds filed the appeal")  # "Tarsh Seeds" was never listed as a variant
    hits = residual_names(leaked, [PELLAM], GENERIC)
    assert hits == ["Tarsh", "Seeds"]


def test_residual_scan_ignores_generic_words_and_lower_case() -> None:
    assert residual_names("the bank of india and a private limited company", [ZORVEX, PELLAM], GENERIC) == []


@pytest.mark.parametrize(
    "text",
    [
        "This Tribunal has already held that the debt is due.",
        "We are of the view that the application is barred.",
        "The appeal is dismissed with no order as to costs.",
        "As held below, the claim is not maintainable.",
    ],
)
def test_court_voice_is_found(text: str) -> None:
    markers = ["this tribunal has already held", "we are of the view", "the appeal is dismissed", "as held below"]
    assert court_voice_hits(text, markers)


def test_a_lower_forum_outcome_is_not_court_voice() -> None:
    markers = ["we are of the view", "the appeal is dismissed"]
    assert court_voice_hits("The Adjudicating Authority dismissed the application on 01.01.2001.", markers) == []


@pytest.mark.parametrize(
    "text",
    [
        "relying on Qarno Vell v. Union of Zeth, (2001) 3 SCC 45",
        "as held in Pellam Tarsh vs. Ostrel Vandu (Supra)",
        "see 2001 SCC OnLine NCLAT 12",
    ],
)
def test_case_citations_are_found(text: str) -> None:
    assert citation_hits(text, authority_names=[])


def test_a_named_authority_is_found_even_without_a_citation_pattern() -> None:
    assert citation_hits("the principle in Qarno Vell applies", authority_names=["Qarno Vell"])
    assert citation_hits("the Creditor versus the Debtor dispute", authority_names=[]) == []
