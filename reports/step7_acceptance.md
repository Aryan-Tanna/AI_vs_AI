# Step 7 acceptance: THEMIS-LOCAL layer 1

Arguments: 26 (22 honest, 4 mutated).
False rejections (honest with any hard error): 0 of 22 = 0.0%.
Mutations caught with the expected code: 4 of 4.

| # | Case | Kind | Expected hard | Hard | Warnings | As expected |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | DEV_0002 | HONEST | - | - | WARN_PREREQUISITE_UNADDRESSED | yes |
| 2 | DEV_0002 | HONEST | - | - | UNMAPPED | yes |
| 3 | DEV_0002 | HONEST | - | - | THRESHOLD_NOT_VERIFIABLE, UNMAPPED, WARN_PREREQUISITE_UNADDRESSED | yes |
| 4 | DEV_0002 | HONEST | - | - | - | yes |
| 5 | DEV_0002 | HONEST | - | - | UNMAPPED | yes |
| 6 | DEV_0002 | HONEST | - | - | THRESHOLD_NOT_VERIFIABLE, UNMAPPED, WARN_PREREQUISITE_UNADDRESSED | yes |
| 7 | DEV_0003 | HONEST | - | - | - | yes |
| 8 | DEV_0003 | HONEST | - | - | - | yes |
| 9 | DEV_0003 | HONEST | - | - | - | yes |
| 10 | DEV_0003 | HONEST | - | - | - | yes |
| 11 | DEV_0003 | HONEST | - | - | - | yes |
| 12 | DEV_0003 | HONEST | - | - | - | yes |
| 13 | DEV_0003 | HONEST | - | - | - | yes |
| 14 | DEV_0003 | HONEST | - | - | - | yes |
| 15 | DEV_0003 | HONEST | - | - | - | yes |
| 16 | DEV_0003 | HONEST | - | - | - | yes |
| 17 | DEV_0003 | HONEST | - | - | - | yes |
| 18 | DEV_0003 | HONEST | - | - | - | yes |
| 19 | DEV_0003 | HONEST_NUMERIC | - | - | WARN_PREREQUISITE_UNADDRESSED | yes |
| 20 | DEV_0003 | MUTATED | ERR_TIMELINE_MISSTATED | ERR_TIMELINE_MISSTATED | WARN_PREREQUISITE_UNADDRESSED | yes |
| 21 | DEV_0003 | HONEST_NUMERIC | - | - | WARN_PREREQUISITE_UNADDRESSED | yes |
| 22 | DEV_0003 | MUTATED | ERR_TIMELINE_MISSTATED | ERR_TIMELINE_MISSTATED | WARN_PREREQUISITE_UNADDRESSED | yes |
| 23 | DEV_0003 | HONEST_NUMERIC | - | - | - | yes |
| 24 | DEV_0003 | MUTATED | ERR_TIMELINE_MISSTATED | ERR_TIMELINE_MISSTATED | - | yes |
| 25 | DEV_0003 | HONEST_NUMERIC | - | - | WARN_PREREQUISITE_UNADDRESSED | yes |
| 26 | DEV_0003 | MUTATED | ERR_TIMELINE_MISSTATED | ERR_TIMELINE_MISSTATED | WARN_PREREQUISITE_UNADDRESSED | yes |

## Arguments and details

**1. DEV_0002 HONEST**: The Resolution Plan must address and consider the claims of all stakeholders, including Operational Creditors, under Section 30(2) and the CIRP Regulations.


**2. DEV_0002 HONEST**: The CoC did not consider the claim of the Appellant or propose any payment to the Operational Creditor, rendering the plan invalid.


**3. DEV_0002 HONEST**: Under Section 30(2)(b), Operational Creditors are only entitled to the minimum liquidation value, which in this case is nil.


**4. DEV_0002 HONEST**: A Resolution Plan can only be interfered with if it violates Section 30(2)(b) of the IBC, which is not the case here.


**5. DEV_0002 HONEST**: The Adjudicating Authority erred in approving the Resolution Plan because it failed to consider or propose any payment to the Operational Creditor, which violates the requirement to address the claims of all stakeholders.


**6. DEV_0002 HONEST**: Under Section 30(2)(b), operational creditors are only entitled to a minimum of what they would receive in the event of liquidation. Since the liquidation value for operational creditors in this case is nil, the CoC did not err in approving a plan with nil payment.


**7. DEV_0003 HONEST**: The mere fact that the assignor was a related party does not make the assignee a related party, and an assignee does not suffer from the same deficiencies as the assignor.


**8. DEV_0003 HONEST**: The insufficient stamping of the Assignment Deed is a curable defect and does not prevent the document from being considered.


**9. DEV_0003 HONEST**: The Assignment Deed was an assignment of an actionable claim and did not require registration.


**10. DEV_0003 HONEST**: The assignment transaction was not bonafide and was executed with the ulterior motive to sabotage the CIRP and gain control of the Corporate Debtor.


**11. DEV_0003 HONEST**: The Assignment Deed was not sufficiently stamped as required by the Maharashtra Stamp Act and could not be looked into.


**12. DEV_0003 HONEST**: The Assignment Deed transferred debt along with hypothecation and mortgage rights, requiring mandatory registration under Section 17 of the Registration Act.


**13. DEV_0003 HONEST**: The Assignment Deed dated 01.03.2019 was an assignment of an actionable claim and did not require registration under the Registration Act, 1908.


**14. DEV_0003 HONEST**: The insufficient stamping of the Assignment Deed under the Maharashtra Stamp Act is a curable defect and does not render the document inadmissible.


**15. DEV_0003 HONEST**: The assignee of a debt from a related party is not automatically disqualified as a related party under the first proviso to Section 21(2) of the IBC, 2016, as the assignment was a bona fide transaction for valuable consideration.


**16. DEV_0003 HONEST**: The Assignment Deed assigned the debt along with hypothecation and mortgage, so it was not merely an actionable claim and required registration under Section 17 of the Registration Act, 1908.


**17. DEV_0003 HONEST**: The Assignment Deed was not sufficiently stamped as required by the Maharashtra Stamp Act, and thus could not be looked into or admitted in evidence.


**18. DEV_0003 HONEST**: The assignment was not a bona fide transaction but a circuitous transaction entered into in bad faith to circumvent the related party disqualification under Section 21(2) of the IBC, 2016.


**19. DEV_0003 HONEST_NUMERIC**: The mere fact that the assignor was a related party does not make the assignee a related party, and an assignee does not suffer from the same deficiencies as the assignor. Further, under Section 7(4) of the Code the Adjudicating Authority is required to ascertain the existence of a default within 14 days of receipt of the application.


**20. DEV_0003 MUTATED**: The mere fact that the assignor was a related party does not make the assignee a related party, and an assignee does not suffer from the same deficiencies as the assignor. Further, under Section 7(4) of the Code the Adjudicating Authority is required to ascertain the existence of a default within 28 days of receipt of the application.

- hard: ERR_TIMELINE_MISSTATED IBC_2016_SEC_7: adjudication_window_days: stated 28; law 14

**21. DEV_0003 HONEST_NUMERIC**: The mere fact that the assignor was a related party does not make the assignee a related party, and an assignee does not suffer from the same deficiencies as the assignor. The Code allows the Adjudicating Authority 14 days from receipt to decide whether a default has occurred.


**22. DEV_0003 MUTATED**: The mere fact that the assignor was a related party does not make the assignee a related party, and an assignee does not suffer from the same deficiencies as the assignor. The Code allows the Adjudicating Authority 28 days from receipt to decide whether a default has occurred.

- hard: ERR_TIMELINE_MISSTATED IBC_2016_SEC_7: adjudication_window_days: stated 28; law 14

**23. DEV_0003 HONEST_NUMERIC**: The mere fact that the assignor was a related party does not make the assignee a related party, and an assignee does not suffer from the same deficiencies as the assignor. Under the proviso to Section 7(5) of the Code, the applicant must be given 7 days from notice to rectify any defect in the application.


**24. DEV_0003 MUTATED**: The mere fact that the assignor was a related party does not make the assignee a related party, and an assignee does not suffer from the same deficiencies as the assignor. Under the proviso to Section 7(5) of the Code, the applicant must be given 14 days from notice to rectify any defect in the application.

- hard: ERR_TIMELINE_MISSTATED IBC_2016_SEC_7: rectification_window_days: stated 14; law 7

**25. DEV_0003 HONEST_NUMERIC**: The mere fact that the assignor was a related party does not make the assignee a related party, and an assignee does not suffer from the same deficiencies as the assignor. A defective application under Section 7 may be cured within 7 days of the notice of the defect.


**26. DEV_0003 MUTATED**: The mere fact that the assignor was a related party does not make the assignee a related party, and an assignee does not suffer from the same deficiencies as the assignor. A defective application under Section 7 may be cured within 14 days of the notice of the defect.

- hard: ERR_TIMELINE_MISSTATED IBC_2016_SEC_7: rectification_window_days: stated 14; law 7
