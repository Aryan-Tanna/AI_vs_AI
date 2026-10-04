"""Proceeding-specific legal framework given to advocates (CLAUDE.md §5). Both sides receive the same text:
it states the governing tests, never which side they favour. Authorities named here are still checked with
authority_status before citing, and their dates against the cutoff."""

ROLE_DESCRIPTION = {
    "FINANCIAL_CREDITOR": "a financial creditor", "OPERATIONAL_CREDITOR": "an operational creditor",
    "SUSPENDED_DIRECTOR_PROMOTER": "a suspended director / promoter of the corporate debtor",
    "SHAREHOLDER": "a shareholder", "CORPORATE_DEBTOR": "the corporate debtor",
    "RESOLUTION_PROFESSIONAL": "the resolution professional", "LIQUIDATOR": "the liquidator",
    "RESOLUTION_APPLICANT": "a resolution applicant", "COC": "the committee of creditors",
    "STATUTORY_AUTHORITY": "a statutory authority", "WORKMEN_EMPLOYEES": "workmen / employees",
    "HOMEBUYERS": "homebuyers (allottees)", "PERSONAL_GUARANTOR": "a personal guarantor", "IBBI": "the IBBI",
    "OTHER": "another stakeholder",
}

COMMON = ("Limitation for s.7/s.9 applications: Article 137, three years from default, extended only by an "
          "acknowledgment or part-payment made before expiry (s.18/s.19), subject to s.14, s.5 and the Supreme Court "
          "COVID exclusion. The s.4 threshold is the one in force on the filing date. s.10A bars applications for "
          "defaults between 25.03.2020 and 24.03.2021. Use the rules_* tools for every date calculation.")

FRAMEWORK = {
    "SEC7_ADMISSION": "Admission turns on a financial debt, a default above the threshold, a complete application, and "
                      "limitation. There is no general discretion to refuse admission on viability or hardship "
                      "(Innoventive; Vidarbha was confined to its own facts in M. Suresh Kumar Reddy).",
    "SEC9_ADMISSION": "Operational creditor: demand notice under s.8; the application may be filed only after 10 days "
                      "from delivery; it must be rejected if a plausible, pre-existing dispute exists (Mobilox). The "
                      "tribunal does not decide the merits of the dispute, only whether it is real and pre-existing.",
    "SEC10_ADMISSION": "Corporate applicant: the application must meet s.10 and the threshold; s.10A applies to defaults in its window.",
    "RESOLUTION_PLAN_APPROVAL": "The commercial wisdom of the CoC is not open to review; scrutiny is limited to compliance "
                                "with s.30(2) (K. Sashidhar; CoC of Essar Steel). An approved plan binds all stakeholders "
                                "(Ghanashyam Mishra).",
    "SEC29A_ELIGIBILITY": "Eligibility of resolution applicants is governed by s.29A (ArcelorMittal).",
    "SEC60_5_JURISDICTION": "s.60(5)(c) covers only disputes arising solely from or relating to the insolvency "
                            "(Gujarat Urja Vikas Nigam); public-law decisions are outside it (Embassy Property).",
    "APPEAL_LIMITATION_CONDONATION": "s.61(2): 30 days from pronouncement where the party was present or aware "
                                     "(V. Nagarajan), plus up to 15 days on sufficient cause; no power beyond 45 days.",
    "MORATORIUM_SEC14": "The s.14 moratorium protects the corporate debtor, not personal guarantors (V. Ramakrishnan).",
    "PERSONAL_GUARANTOR_95_100": "Personal guarantor insolvency follows Part III, ss.95-100 (Dilip B. Jiwrajka; Lalit Kumar Jain).",
}

SEC61_3 = ("This is an appeal against approval of a resolution plan: under s.61(3) it lies only on the grounds that "
           "(i) the plan contravenes the law in force; (ii) the resolution professional committed a material "
           "irregularity during the CIRP; (iii) operational creditors' debts are not provided for as the Board "
           "specifies; (iv) CIRP costs are not provided for in priority; or (v) the plan does not meet other criteria "
           "specified by the Board. Arguments outside these grounds are out of scope.")
SEC61_4 = "This is an appeal against a liquidation order: under s.61(4) it lies on material irregularity or fraud."


def framework_for(proceeding_type: str, restricted_grounds: str | None) -> str:
    parts = [FRAMEWORK.get(proceeding_type, ""), COMMON]
    if restricted_grounds == "SEC61_3":
        parts.append(SEC61_3)
    elif restricted_grounds == "SEC61_4":
        parts.append(SEC61_4)
    return "\n".join(p for p in parts if p)


def side_description(side: str, appellant_role: str, respondent_roles: list[str]) -> str:
    if side == "APPELLANT":
        return f"the appellant, {ROLE_DESCRIPTION.get(appellant_role, 'a stakeholder')}"
    roles = ", ".join(ROLE_DESCRIPTION.get(r, r.lower()) for r in respondent_roles) or "the respondents"
    return f"the respondents ({roles})"
