# Worked example: segmenting a judgment into the public case DB

Source: *Deloitte Haskins & Sells LLP v. Union of India* (with Kalpesh Mehta and Udayan Sen v. Union of India),
NCLAT Principal Bench, Company Appeal (AT) Nos. 255, 284 & 285 of 2024, decided 28.02.2025
(Indian Kanoon title: "Udayan Sen vs Union Of India"). Rules: CLAUDE.md §6.6.7.

**This case would not enter the Phase-1 public DB.** It is a Companies Act matter (ss. 212, 223; CP under
ss. 241/242), not IBC, and it arises from a widely reported group-level fraud investigation, so the facts
identify it even after anonymisation. It is used here only because it shows most of the traps.

## 1. Paragraph map

| Para | Content | Goes to | Note |
|---|---|---|---|
| Header (pp. 1–2) | Three appeal numbers, impugned order details, parties, counsel | `manifest.real`; unspoiled keeps forum, bench city, impugned order forum/bench/date | Three connected appeals, one judgment → **one case** |
| "Author / Bench" line, signature | Coram: Chairperson + Member (Technical) | `manifest.real` only | Judge identity is a bias signal |
| 1 | Appeals against the NCLT order rejecting three applications | `unspoiled.impugned_order` | |
| 2.1 | Investigation, CP filing, reports, complaint, impleadment, earlier appeals | `unspoiled.chronology` | Earlier NCLAT/SC outcomes (04.03.2020, 28.02.2024) are procedural history of *other* proceedings: allowed |
| 2.2 | What the appellants' applications sought; what the NCLT held | `unspoiled.impugned_order` | NCLT's holding is the order under appeal: allowed |
| 3 | Counsel who argued | dropped | Senior-counsel identity bias |
| 4 | Appellant's submissions | headings → unspoiled; full text → `ground_truth.submissions_full` | |
| 5 | Respondent's submissions | headings → unspoiled; full text → sealed | Indian Kanoon's labels have no separate "Respondent's Arguments" class, so we classify per paragraph |
| 6 | "Both relied on SC judgments" | dropped | |
| 7 | Four issues framed by the bench | `unspoiled.issues` after neutrality rewrite | Originals in `manifest.qa.issues_original` |
| 8 | "Issues (i)–(iii) taken together" | `ground_truth.bench_framing` | The bench's grouping is reasoning |
| 9–11 | Mostly record facts (report dates, complaint, MA prayers, compilation, CA 65 prayers) **inside the reasoning section** | facts → `chronology` / `record_documents`; bench observations → sealed | Para 11 also contains a respondent *submission* ("served in soft copy…") → a contention heading, not a fact |
| 12–18 | Statutory text of ss. 211, 212, 223; notes on clauses of the 2019 Amendment Bill | not copied; provisions from the parties' submissions → `statutes_in_play`; notes on clauses → `bench_framing.interpretive_aids` | The text comes from the law DB `as_of`; the bench's choice of what to quote is reasoning |
| 19–27 | Precedents relied on by each side, with the bench's reading | `ground_truth.authorities_cited_by_parties` | Sealed: used to measure retrieval recall |
| 28–38 | Reasoning | `ground_truth.issue_findings`, `ratio_decidendi` | |
| 39 | Appeals dismissed; parties bear own costs | `ground_truth.label`, `operative_order_verbatim`, `directions` | |

## 2. Problems in the record itself (all from the judgment text)

| Field | Conflict | Handling |
|---|---|---|
| First interim SFIO report | 30.11.2018 (para 2.1; later in para 9) vs 01.11.2018 (earlier in para 9) | `typed_facts` with `values: [both], conflict: true`; Stage A accepts either, with a CONFLICT note |
| Compilation date | 07.02.2024 (para 2.2, issue ii, para 11) vs 17.02.2024 (issue iii) | Same |
| Which MA was filed after the 2nd report / under s.212(14A) | Para 17 says MA 2071; para 29 says MA 2070 (para 9: MA 2071 = impleadment, MA 2070 = attachment) | `record_conflicts` note; anonymised as [IMPLEADMENT_APPLICATION] / [ATTACHMENT_APPLICATION] |
| CA vs IA | "IA No. 65 of 2024" (para 36) vs "CA No. 65 of 2024" elsewhere | Normalise to one application token |
| Timing | Attachment application dated 08.06.2019 (para 11); s.212(14A) inserted w.e.f. 15.08.2019 (para 16) | Both reach the agents: the date via the record, the provision's start date via `get_provision(as_of)`. Whether that matters is for the advocates to argue and the bench to decide |

The last row is the kind of point the as-of law DB exists for. The pipeline must not resolve it either way.

## 3. Resulting `unspoiled.jsonl` record (abridged)

```jsonc
{
  "case_uid": "PC-EXAMPLE",
  "title_anon": "[APPELLANT_1] and others v. [CENTRAL_GOVERNMENT] and others",
  "forum": "NCLAT", "bench_city": "NEW_DELHI",
  "law_as_of": "2025-02-27",
  "proceeding_type": "COMPANIES_ACT_241_242",          // out of Phase-1 scope
  "appellant_role": "OTHER",                            // [APPELLANT_1] audit firm; [APPELLANT_2], [APPELLANT_3] individuals
  "respondent_roles": ["STATUTORY_AUTHORITY"],
  "parties": [
    {"token": "[APPELLANT_1]", "kind": "LLP", "description": "audit firm, impleaded in the company petition"},
    {"token": "[APPELLANT_2]", "kind": "INDIVIDUAL", "description": "impleaded in the company petition"},
    {"token": "[APPELLANT_3]", "kind": "INDIVIDUAL", "description": "impleaded in the company petition"},
    {"token": "[GROUP_HOLDING_CO]", "kind": "COMPANY", "description": "infrastructure development and finance group"},
    {"token": "[FINANCE_SUBSIDIARY]", "kind": "COMPANY", "description": "financial services subsidiary investigated"}
  ],
  "impugned_order": {
    "forum": "NCLT", "bench_city": "MUMBAI", "date": "2024-07-22",
    "application_type": "INTERLOCUTORY_APPLICATIONS_IN_ATTACHMENT_APPLICATION",
    "outcome_below": "APPLICATIONS_REJECTED",
    "reasoning_summary": "The appellants' three applications objected to the admissibility of the second SFIO report, to the compilation of documents underlying it, and to an amended prayer clause of the company petition. The NCLT rejected them, holding that the second SFIO report, or a compilation of extracts from it, can be considered for interim relief and for final declaration.",
    "src": [{"doc": "JUDGMENT", "page": 3, "para": "2.2"}, {"doc": "JUDGMENT", "page": 4, "para": "2.2"}]
  },
  "chronology": [
    {"id": "E1", "date": null, "event": "Central Government directs SFIO under s.212 to investigate the affairs of [GROUP_HOLDING_CO] and subsidiaries", "src": [{"page": 3, "para": "2.1"}]},
    {"id": "E2", "date": "2018-10-01", "event": "Company petition filed by the Central Government under ss.241-242; NCLT supersedes the board of [GROUP_HOLDING_CO]", "src": [{"page": 3, "para": "2.1"}, {"page": 8, "para": "10"}]},
    {"id": "E3", "date": "2018-11-30", "event": "SFIO first interim report", "conflict_ref": "first_interim_report_date", "src": [{"page": 3, "para": "2.1"}]},
    {"id": "E4", "date": "2019-05-28", "event": "SFIO second investigation report (re [FINANCE_SUBSIDIARY]) submitted to the Central Government", "src": [{"page": 3, "para": "2.1"}]},
    {"id": "E5", "date": "2019-05-29", "event": "Central Government direction under s.212(14) to initiate prosecution", "src": [{"page": 3, "para": "2.1"}]},
    {"id": "E6", "date": "2019-05-30", "event": "Criminal complaint filed before the Special Judge", "src": [{"page": 6, "para": "9"}]},
    {"id": "E7", "date": "2019-06-08", "event": "[ATTACHMENT_APPLICATION] filed by the Central Government in the company petition, based on the second report", "src": [{"page": 8, "para": "11"}]},
    {"id": "E8", "date": "2019-07-18", "event": "NCLT allows [IMPLEADMENT_APPLICATION] (individual entities charged on the basis of the second report); [APPELLANT_1] impleaded as a respondent", "src": [{"page": 3, "para": "2.1"}]},
    {"id": "E9", "date": "2019-11-25", "event": "NCLT allows the Central Government's amendment application", "src": [{"page": 3, "para": "2.1"}]},
    {"id": "E10", "date": "2020-03-04", "event": "NCLAT dismisses appeals against the impleadment order (earlier proceeding)", "src": [{"page": 3, "para": "2.1"}]},
    {"id": "E11", "date": "2024-02-07", "event": "[ATTACHMENT_APPLICATION] listed for arguments; Central Government tenders compilation of documents underlying the second report", "conflict_ref": "compilation_date", "src": [{"page": 3, "para": "2.1"}, {"page": 8, "para": "11"}]},
    {"id": "E12", "date": "2024-02-16", "event": "[APPELLANT_1] applies for a declaration that the compilation is inadmissible and for a stay of the attachment application", "src": [{"page": 8, "para": "11"}, {"page": 9, "para": "11"}]},
    {"id": "E13", "date": "2024-02-20", "event": "NCLT grants liberty to amend the company petition in terms of the 25.11.2019 order", "src": [{"page": 3, "para": "2.1"}]},
    {"id": "E14", "date": "2024-02-28", "event": "Appeals before the Supreme Court against the 04.03.2020 order withdrawn", "src": [{"page": 3, "para": "2.1"}]},
    {"id": "E15", "date": "2024-07-22", "event": "Impugned NCLT order", "src": [{"page": 2, "para": "1"}]}
  ],
  "typed_facts": {
    "impugned_order_date": {"value": "2024-07-22", "ref": "E15"},
    "first_interim_report_date": {"values": ["2018-11-30", "2018-11-01"], "conflict": true,
                                  "src": [{"page": 3, "para": "2.1"}, {"page": 6, "para": "9"}]},
    "compilation_date": {"values": ["2024-02-07", "2024-02-17"], "conflict": true,
                         "src": [{"page": 6, "para": "7(ii)"}, {"page": 6, "para": "7(iii)"}]},
    "appeal_filing_date": {"value": null}
  },
  "record_documents": [
    {"id": "D1", "kind": "APPLICATION", "date": "2019-06-08", "gist": "[ATTACHMENT_APPLICATION]: extend earlier interim orders to added respondents; permit examination of unusual transactions from 01.10.2018"},
    {"id": "D2", "kind": "COMPILATION", "date": "2024-02-07", "gist": "Note of the investigation report and documents forming part of the second SFIO report"},
    {"id": "D3", "kind": "APPLICATION", "date": "2024-02-16", "gist": "[APPELLANT_1]: declare compilation inadmissible; stay attachment application"}
  ],
  "issues": [
    {"id": "I1", "text": "Whether an SFIO investigation report under s.212(12) is admissible in evidence, having regard to s.223(5) read with s.212(15) of the Companies Act, 2013."},
    {"id": "I2", "text": "Whether the second SFIO report and the compilation tendered before the NCLT can be looked into in deciding the attachment application, having regard to the deeming provision in s.212(15)."},
    {"id": "I3", "text": "Whether the pleadings in the company petition and the attachment application are sufficient for reliance on the SFIO report and the compilation."},
    {"id": "I4", "text": "Whether the impugned order is sustainable in law."}
  ],
  "appellant_grounds": [
    {"id": "G1", "issue": "I1", "heading": "s.212(15) deems the report a police report under s.173 CrPC; such a report is not legal evidence, and the fiction is not limited to framing charges"},
    {"id": "G2", "issue": "I1", "heading": "s.223(5) excludes s.212 reports from the evidentiary route in s.223(4)"},
    {"id": "G3", "issue": "I3", "heading": "The compilation is neither pleaded nor annexed; a summary procedure requires notice of the case to be met"},
    {"id": "G4", "issue": "I2", "heading": "Admissibility was never decided in the impleadment proceedings; no res judicata or constructive res judicata"}
  ],
  "respondent_contentions": [
    {"id": "R1", "issue": "I2", "heading": "The scheme of s.212, including s.212(14A), contemplates reliance on the SFIO report in Tribunal proceedings"},
    {"id": "R2", "issue": "I1", "heading": "The deeming fiction in s.212(15) is confined to its context and language"},
    {"id": "R3", "issue": "I1", "heading": "s.223(5) only takes SFIO reports out of the s.223 authentication procedure"},
    {"id": "R4", "issue": "I3", "heading": "The attachment application is interim, pleadings are sufficient, and the report was served on the appellants in 2019"}
  ],
  "statutes_in_play": ["COMPANIES_ACT_2013_SEC_212_14A", "COMPANIES_ACT_2013_SEC_212_15", "COMPANIES_ACT_2013_SEC_214", "COMPANIES_ACT_2013_SEC_223_4", "COMPANIES_ACT_2013_SEC_223_5", "CRPC_1973_SEC_173"],
  "record_conflicts": [
    {"field": "first_interim_report_date", "note": "para 2.1 vs para 9"},
    {"field": "compilation_date", "note": "issue (ii) vs issue (iii)"},
    {"field": "application_identity", "note": "para 17 refers to MA 2071, para 29 to MA 2070, for the application under s.212(14A)"}
  ]
}
```

Notice what's absent: no names of parties, counsel or members; no application or case numbers; no
statute text; no authorities; no wording from paras 28–39.

## 4. Resulting `ground_truth.jsonl` record (abridged)

```jsonc
{
  "case_uid": "PC-EXAMPLE",
  "decision_date": "2025-02-28",
  "label": "DISMISSED", "appellant_won": false,
  "issue_findings": [
    {"issue": "I1", "finding": "ADMISSIBLE_IN_S212_14A_PROCEEDING", "holding": "The s.212(15) fiction treats the report as a s.173 report for framing charges; it does not make the report inadmissible for purposes of the Companies Act. s.223(5) only dispenses with the s.223(4) authentication requirement.", "src": [{"page": 21, "para": "30"}, {"page": 22, "para": "33"}]},
    {"issue": "I2", "finding": "CAN_BE_LOOKED_INTO", "holding": "The second report and the compilation are admissible and can be looked into for the s.212(14A) proceeding; the contrary reading would make s.212(14A) otiose.", "src": [{"page": 23, "para": "36"}]},
    {"issue": "I3", "finding": "NOT_A_GROUND_AT_THIS_STAGE", "holding": "What is pleaded and what is on record are matters for the merits of the applications.", "src": [{"page": 24, "para": "38"}, {"page": 25, "para": "38"}]},
    {"issue": "I4", "finding": "SUSTAINED", "src": [{"page": 25, "para": "39"}]}
  ],
  "operative_order_verbatim": "In view of the foregoing discussions, we are of the view that no grounds have been made out to interfere with the impugned order. All the appeals are dismissed. The parties shall bear their own cost.",
  "directions": ["Parties to bear their own costs"],
  "submissions_full": {"appellant": "<para 4>", "respondent": "<para 5>"},
  "authorities_cited_by_parties": [
    {"title": "Union of India v. Ranjit Kumar Saha", "by": "APPELLANT"},
    {"title": "Department of Customs v. Sharad Gandhi", "by": "APPELLANT"},
    {"title": "Bhavnagar University v. Palitana Sugar Mill (P) Ltd.", "by": "APPELLANT"},
    {"title": "State of Karnataka v. State of Tamil Nadu", "by": "APPELLANT"},
    {"title": "K. Veeraswami v. Union of India", "by": "APPELLANT"},
    {"title": "M.C. Mehta (Taj Corridor Scam) v. Union of India", "by": "APPELLANT"},
    {"title": "Bachhaj Nahar v. Nilima Mandal", "by": "APPELLANT"},
    {"title": "Mancheri Puthusseri Ahmed v. Kuthiravattam Estate Receiver", "by": "RESPONDENT"},
    {"title": "Prakash H. Jain v. Marie Fernandes", "by": "RESPONDENT"}
  ],
  "bench_framing": {
    "issue_grouping": "Issues (i)-(iii) decided together",
    "interpretive_aids": ["Notes on clauses, Clause 31, Companies (Amendment) Bill, 2019", "Hardeep Singh v. State of Punjab (relied on by the bench)"]
  }
}
```

## 5. Checks this record must pass before acceptance
- No unspoiled n-gram overlaps `issue_findings` or the operative order (e.g. "otiose", "no error has been committed").
- No names from the header in unspoiled; no "CP No.", "MA No.", "CA No." patterns.
- Every `src` resolves to a real page/para.
- Contamination probe: given only the anonymised facts, does a model name the group or the outcome? For a
  matter this widely reported, expect yes → exclude from test.
