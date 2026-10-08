# Step 7 acceptance: THEMIS-LOCAL layer 1

Arguments: 42 (34 honest, 8 mutated).
False rejections (honest with any hard error): 0 of 34 = 0.0%.
Mutations caught with the expected code: 7 of 8.

| # | Case | Kind | Expected hard | Hard | Warnings | As expected |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | DEV_0001 | HONEST | - | - | - | yes |
| 2 | DEV_0001 | HONEST | - | - | - | yes |
| 3 | DEV_0001 | HONEST | - | - | - | yes |
| 4 | DEV_0001 | HONEST | - | - | - | yes |
| 5 | DEV_0001 | HONEST | - | - | - | yes |
| 6 | DEV_0001 | HONEST | - | - | WARN_PREREQUISITE_UNADDRESSED | yes |
| 7 | DEV_0001 | HONEST | - | - | - | yes |
| 8 | DEV_0001 | HONEST_NUMERIC | - | - | WARN_PREREQUISITE_UNADDRESSED | yes |
| 9 | DEV_0001 | MUTATED | ERR_TIMELINE_MISSTATED | ERR_TIMELINE_MISSTATED | WARN_PREREQUISITE_UNADDRESSED | yes |
| 10 | DEV_0001 | HONEST_NUMERIC | - | - | - | yes |
| 11 | DEV_0001 | MUTATED | ERR_TIMELINE_MISSTATED | - | - | **no** |
| 12 | DEV_0001 | HONEST_NUMERIC | - | - | WARN_PREREQUISITE_UNADDRESSED | yes |
| 13 | DEV_0001 | MUTATED | ERR_TIMELINE_MISSTATED | ERR_TIMELINE_MISSTATED | WARN_PREREQUISITE_UNADDRESSED | yes |
| 14 | DEV_0001 | HONEST_NUMERIC | - | - | - | yes |
| 15 | DEV_0001 | MUTATED | ERR_TIMELINE_MISSTATED | ERR_TIMELINE_MISSTATED | - | yes |
| 16 | DEV_0001 | PRE_THRESHOLD | - | - | THRESHOLD_NOT_VERIFIABLE, UNMAPPED, WARN_PREREQUISITE_UNADDRESSED | yes |
| 17 | DEV_0002 | HONEST | - | - | WARN_CONDITION_NOT_IN_STATUTE, WARN_PREREQUISITE_UNADDRESSED | yes |
| 18 | DEV_0002 | HONEST | - | - | - | yes |
| 19 | DEV_0002 | HONEST | - | - | THRESHOLD_NOT_VERIFIABLE, UNMAPPED, WARN_PREREQUISITE_UNADDRESSED | yes |
| 20 | DEV_0002 | HONEST | - | - | - | yes |
| 21 | DEV_0002 | HONEST | - | - | UNMAPPED | yes |
| 22 | DEV_0002 | HONEST | - | - | THRESHOLD_NOT_VERIFIABLE, UNMAPPED, WARN_PREREQUISITE_UNADDRESSED | yes |
| 23 | DEV_0003 | HONEST | - | - | - | yes |
| 24 | DEV_0003 | HONEST | - | - | - | yes |
| 25 | DEV_0003 | HONEST | - | - | - | yes |
| 26 | DEV_0003 | HONEST | - | - | - | yes |
| 27 | DEV_0003 | HONEST | - | - | - | yes |
| 28 | DEV_0003 | HONEST | - | - | - | yes |
| 29 | DEV_0003 | HONEST | - | - | - | yes |
| 30 | DEV_0003 | HONEST | - | - | - | yes |
| 31 | DEV_0003 | HONEST | - | - | - | yes |
| 32 | DEV_0003 | HONEST | - | - | - | yes |
| 33 | DEV_0003 | HONEST | - | - | - | yes |
| 34 | DEV_0003 | HONEST | - | - | - | yes |
| 35 | DEV_0003 | HONEST_NUMERIC | - | - | WARN_PREREQUISITE_UNADDRESSED | yes |
| 36 | DEV_0003 | MUTATED | ERR_TIMELINE_MISSTATED | ERR_TIMELINE_MISSTATED | WARN_PREREQUISITE_UNADDRESSED | yes |
| 37 | DEV_0003 | HONEST_NUMERIC | - | - | - | yes |
| 38 | DEV_0003 | MUTATED | ERR_TIMELINE_MISSTATED | ERR_TIMELINE_MISSTATED | - | yes |
| 39 | DEV_0003 | HONEST_NUMERIC | - | - | - | yes |
| 40 | DEV_0003 | MUTATED | ERR_TIMELINE_MISSTATED | ERR_TIMELINE_MISSTATED | - | yes |
| 41 | DEV_0003 | HONEST_NUMERIC | - | - | - | yes |
| 42 | DEV_0003 | MUTATED | ERR_TIMELINE_MISSTATED | ERR_TIMELINE_MISSTATED | - | yes |

## Arguments and details

**1. DEV_0001 HONEST**: The Corporate Debtor acknowledged its liability through the One Time Settlement proposal dated 13th June, 2015, which extends the limitation period.


**2. DEV_0001 HONEST**: The limitation period began to run afresh from 6th November, 2015 when the OTS proposal was reiterated, making the Section 7 application filed on 19th September, 2018 within the three-year limitation period.


**3. DEV_0001 HONEST**: The provisions of the Limitation Act, 1963, including Section 18, apply to proceedings under the Insolvency and Bankruptcy Code, 2016.


**4. DEV_0001 HONEST**: The Section 7 application is barred by limitation as it was filed more than four years after the recorded date of default of 10th June, 2014.


**5. DEV_0001 HONEST**: The Adjudicating Authority did not err in rejecting the Section 7 application as being hit by limitation.


**6. DEV_0001 HONEST**: The One Time Settlement proposals dated 13th June, 2015 and 6th November, 2015 constitute an acknowledgment of liability under Section 18 of the Limitation Act, 1963, thereby extending the limitation period.


**7. DEV_0001 HONEST**: The application under Section 7 of the IBC is barred by limitation as it was filed more than three years after the date of default, and Section 18 of the Limitation Act cannot be used to extend the limitation period.


**8. DEV_0001 HONEST_NUMERIC**: The Corporate Debtor acknowledged its liability through the One Time Settlement proposal dated 13th June, 2015, which extends the limitation period. Further, under Section 7(4) of the Code the Adjudicating Authority is required to ascertain the existence of a default within 14 days of receipt of the application.


**9. DEV_0001 MUTATED**: The Corporate Debtor acknowledged its liability through the One Time Settlement proposal dated 13th June, 2015, which extends the limitation period. Further, under Section 7(4) of the Code the Adjudicating Authority is required to ascertain the existence of a default within 28 days of receipt of the application.

- hard: ERR_TIMELINE_MISSTATED IBC_2016_SEC_7: adjudication_window_days: stated 28; law 14

**10. DEV_0001 HONEST_NUMERIC**: The Corporate Debtor acknowledged its liability through the One Time Settlement proposal dated 13th June, 2015, which extends the limitation period. The Code allows the Adjudicating Authority 14 days from receipt to decide whether a default has occurred.


**11. DEV_0001 MUTATED**: The Corporate Debtor acknowledged its liability through the One Time Settlement proposal dated 13th June, 2015, which extends the limitation period. The Code allows the Adjudicating Authority 28 days from receipt to decide whether a default has occurred.


**12. DEV_0001 HONEST_NUMERIC**: The Corporate Debtor acknowledged its liability through the One Time Settlement proposal dated 13th June, 2015, which extends the limitation period. Under the proviso to Section 7(5) of the Code, the applicant must be given 7 days from notice to rectify any defect in the application.


**13. DEV_0001 MUTATED**: The Corporate Debtor acknowledged its liability through the One Time Settlement proposal dated 13th June, 2015, which extends the limitation period. Under the proviso to Section 7(5) of the Code, the applicant must be given 14 days from notice to rectify any defect in the application.

- hard: ERR_TIMELINE_MISSTATED IBC_2016_SEC_7: rectification_window_days: stated 14; law 7

**14. DEV_0001 HONEST_NUMERIC**: The Corporate Debtor acknowledged its liability through the One Time Settlement proposal dated 13th June, 2015, which extends the limitation period. A defective application under Section 7 may be cured within 7 days of the notice of the defect.


**15. DEV_0001 MUTATED**: The Corporate Debtor acknowledged its liability through the One Time Settlement proposal dated 13th June, 2015, which extends the limitation period. A defective application under Section 7 may be cured within 14 days of the notice of the defect.

- hard: ERR_TIMELINE_MISSTATED IBC_2016_SEC_7: rectification_window_days: stated 14; law 7

**16. DEV_0001 PRE_THRESHOLD**: The Corporate Debtor acknowledged its liability through the One Time Settlement proposal dated 13th June, 2015, which extends the limitation period. The application was filed when the minimum amount of default under Section 4 of the Code was one lakh rupees, and the default here is well above that minimum.


**17. DEV_0002 HONEST**: The Resolution Plan must address and consider the claims of all stakeholders, including Operational Creditors, under Section 30(2) and the CIRP Regulations.


**18. DEV_0002 HONEST**: The CoC did not consider the claim of the Appellant or propose any payment to the Operational Creditor, rendering the plan invalid.


**19. DEV_0002 HONEST**: Under Section 30(2)(b), Operational Creditors are only entitled to the minimum liquidation value, which in this case is nil.


**20. DEV_0002 HONEST**: A Resolution Plan can only be interfered with if it violates Section 30(2)(b) of the IBC, which is not the case here.


**21. DEV_0002 HONEST**: The Adjudicating Authority erred in approving the Resolution Plan because it failed to consider or propose any payment to the Operational Creditor, which violates the requirement to address the claims of all stakeholders.


**22. DEV_0002 HONEST**: Under Section 30(2)(b), operational creditors are only entitled to a minimum of what they would receive in the event of liquidation. Since the liquidation value for operational creditors in this case is nil, the CoC did not err in approving a plan with nil payment.


**23. DEV_0003 HONEST**: The mere fact that the assignor was a related party does not make the assignee a related party, and an assignee does not suffer from the same deficiencies as the assignor.


**24. DEV_0003 HONEST**: The insufficient stamping of the Assignment Deed is a curable defect and does not prevent the document from being considered.


**25. DEV_0003 HONEST**: The Assignment Deed was an assignment of an actionable claim and did not require registration.


**26. DEV_0003 HONEST**: The assignment transaction was not bonafide and was executed with the ulterior motive to sabotage the CIRP and gain control of the Corporate Debtor.


**27. DEV_0003 HONEST**: The Assignment Deed was not sufficiently stamped as required by the Maharashtra Stamp Act and could not be looked into.


**28. DEV_0003 HONEST**: The Assignment Deed transferred debt along with hypothecation and mortgage rights, requiring mandatory registration under Section 17 of the Registration Act.


**29. DEV_0003 HONEST**: The Assignment Deed dated 01.03.2019 was an assignment of an actionable claim and did not require registration under the Registration Act, 1908.


**30. DEV_0003 HONEST**: The insufficient stamping of the Assignment Deed under the Maharashtra Stamp Act is a curable defect and does not render the document inadmissible.


**31. DEV_0003 HONEST**: The assignee of a debt from a related party is not automatically disqualified as a related party under the first proviso to Section 21(2) of the IBC, 2016, as the assignment was a bona fide transaction for valuable consideration.


**32. DEV_0003 HONEST**: The Assignment Deed assigned the debt along with hypothecation and mortgage, so it was not merely an actionable claim and required registration under Section 17 of the Registration Act, 1908.


**33. DEV_0003 HONEST**: The Assignment Deed was not sufficiently stamped as required by the Maharashtra Stamp Act, and thus could not be looked into or admitted in evidence.


**34. DEV_0003 HONEST**: The assignment was not a bona fide transaction but a circuitous transaction entered into in bad faith to circumvent the related party disqualification under Section 21(2) of the IBC, 2016.


**35. DEV_0003 HONEST_NUMERIC**: The mere fact that the assignor was a related party does not make the assignee a related party, and an assignee does not suffer from the same deficiencies as the assignor. Further, under Section 7(4) of the Code the Adjudicating Authority is required to ascertain the existence of a default within 14 days of receipt of the application.


**36. DEV_0003 MUTATED**: The mere fact that the assignor was a related party does not make the assignee a related party, and an assignee does not suffer from the same deficiencies as the assignor. Further, under Section 7(4) of the Code the Adjudicating Authority is required to ascertain the existence of a default within 28 days of receipt of the application.

- hard: ERR_TIMELINE_MISSTATED IBC_2016_SEC_7: adjudication_window_days: stated 28; law 14

**37. DEV_0003 HONEST_NUMERIC**: The mere fact that the assignor was a related party does not make the assignee a related party, and an assignee does not suffer from the same deficiencies as the assignor. The Code allows the Adjudicating Authority 14 days from receipt to decide whether a default has occurred.


**38. DEV_0003 MUTATED**: The mere fact that the assignor was a related party does not make the assignee a related party, and an assignee does not suffer from the same deficiencies as the assignor. The Code allows the Adjudicating Authority 28 days from receipt to decide whether a default has occurred.

- hard: ERR_TIMELINE_MISSTATED IBC_2016_SEC_7: adjudication_window_days: stated 28; law 14

**39. DEV_0003 HONEST_NUMERIC**: The mere fact that the assignor was a related party does not make the assignee a related party, and an assignee does not suffer from the same deficiencies as the assignor. Under the proviso to Section 7(5) of the Code, the applicant must be given 7 days from notice to rectify any defect in the application.


**40. DEV_0003 MUTATED**: The mere fact that the assignor was a related party does not make the assignee a related party, and an assignee does not suffer from the same deficiencies as the assignor. Under the proviso to Section 7(5) of the Code, the applicant must be given 14 days from notice to rectify any defect in the application.

- hard: ERR_TIMELINE_MISSTATED IBC_2016_SEC_7: rectification_window_days: stated 14; law 7

**41. DEV_0003 HONEST_NUMERIC**: The mere fact that the assignor was a related party does not make the assignee a related party, and an assignee does not suffer from the same deficiencies as the assignor. A defective application under Section 7 may be cured within 7 days of the notice of the defect.


**42. DEV_0003 MUTATED**: The mere fact that the assignor was a related party does not make the assignee a related party, and an assignee does not suffer from the same deficiencies as the assignor. A defective application under Section 7 may be cured within 14 days of the notice of the defect.

- hard: ERR_TIMELINE_MISSTATED IBC_2016_SEC_7: rectification_window_days: stated 14; law 7
