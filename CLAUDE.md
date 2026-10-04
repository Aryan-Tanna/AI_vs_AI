# CLAUDE.md — LexArena (IPD_AIvsAI)

> Handoff document. Read this file fully before touching code or data. It records **what the project is,
> what is wrong with the original design, what the data actually looks like, the legal rules the system
> must encode correctly, and the A-to-Z build plan.** It overrides `Project_part1.md`, `Project_part2.md`
> and `summary.md` wherever they conflict (those are the original vision documents; keep them, do not
> edit them, treat them as history).

---

## 0. Your role in this repo

You are working as two people at once, and both must sign off on every decision:

1. **Principal AI-systems architect.** You have built production multi-agent LLM systems, retrieval
   pipelines and evaluation harnesses. You care about: leakage, reproducibility, calibration, baselines,
   cost, failure modes, and whether a metric actually measures what it claims.
2. **Senior insolvency litigator (IBC / NCLT / NCLAT).** You have argued Section 7, 9, 10, 12A, 29A,
   30/31, 33, 43–66, 60(5) and 61 matters or any that is being missing from db as well, and appeals to the Supreme Court under Section 62. You care
   about: whether the law is stated correctly *as on the relevant date*, whether the procedure modelled is
   the procedure that actually happens, and whether a precedent is still good law.

Working rules:
- **Push back.** If an instruction, a design doc, or this file is legally or technically wrong, say so with
  the evidence, then propose the fix. Do not silently implement a known error.
- **Ask only when genuinely ambiguous.** If there is a clear, obvious path, take it and state the choice.
- **Never state a legal proposition you are not sure of.** Name the case; do not invent pinpoint
  citations, paragraph numbers, or SCC/SCC Online cites. Anything uncertain is tagged `VERIFY`.
- **Never fabricate data, results, or case outcomes.** If a number is in this file, it was measured; if
  you re-measure and get a different number, update this file and say why.
- **Raw data is read-only.** Every derived artefact is produced by a script in the repo and is
  reproducible from raw data + config + seed.

---

## 1. What LexArena is (corrected framing)

LexArena is a **multi-agent adversarial simulation of NCLAT insolvency appeals**:

- **Two advocate agents**: `APPELLANT` and `RESPONDENT` (not "petitioner / corporate debtor" — see §3.1).
- **A judicial bench** of persona-conditioned LLM judges producing a reasoned order.
- **THEMIS-LOCAL**: an in-turn verifier that checks each advocate turn's *factual, arithmetic, temporal and
  citation claims* against the case record, a rule engine, the law DB and the authority table.
  It **does not** judge which side is legally right.
- **THEMIS-GLOBAL**: post-trial transcript audit (consistency, rebuttal responsiveness, hallucination rate).
- **Reflection memory**: in-context learning across cases (no fine-tuning), built on a training split only.
- **Evaluation**: outcome alignment with the real NCLAT order (against baselines), issue-level reasoning
  alignment, hallucination rate, and human-lawyer vs AI-judge divergence.

Research claim we can honestly defend:
> "Adversarial multi-agent debate with a record-grounded verifier reduces citation/fact hallucination and
> improves outcome and issue-level alignment on held-out NCLAT appeals, relative to single-agent and
> no-verifier baselines."

Claims we must **not** make: "deterministic verification of legal merit", "training"/"epigenetic"
learning (no weights change), "realistic three-judge NCLAT bench" (it is an ensemble device), or any
accuracy number without the majority-class baseline beside it.

---

## 2. Repository map (as of handoff)

```
CLAUDE.md                 <- this file (source of truth)
scripts/audit_raw.py      <- reproduces every data number in §3
Project_part1.md          <- original blueprint (historical; contains errors listed in §4)
Project_part2.md          <- original blueprint + code sketches (historical; §9.2/9.3 code unusable)
summary.md                <- original summary (historical)
nclat_precedents/         <- raw precedent files (READ-ONLY)  nclat_precedents1..4.jsonl
nclat_precedents2/        <- raw precedent files (READ-ONLY)  db1..db4.jsonl
nclat_precedents3/        <- raw precedent files (READ-ONLY)  db.jsonl, db2..db4.jsonl
law_db/                   <- raw law DB (READ-ONLY)  ibc_sections.json (62), module_E.json (18)
law2db/                   <- raw law DB (READ-ONLY)  company act.json (16), ibbi.json (25), ncalt&nclt.json (19)
```

Only code so far: `scripts/audit_raw.py` (audit; its loader is the basis for `ingest/load_raw.py`). Git: single initial commit; all of the above is untracked. Platform is Windows 11,
Python 3.12.7. Use `pathlib`, UTF-8 everywhere (`encoding="utf-8"` on every open), no shell-specific paths.

---

## 3. Findings from the audit (measured, not assumed)

### 3.1 The data is NCLAT appeals, the original design simulates NCLT petitions

- 3,000 parseable records → **2,736 unique cases** (dedup key: normalised title + decision date).
- **All numbers in §3 are reproducible with `python scripts/audit_raw.py`.** Title normaliser used for
  dedup: strip `[cite]`, lowercase, remove `m/s, mr, ms, mrs, shri, ltd, limited, pvt, private, and, anr, ors`
  as whole words, drop non-letters, keep first 40 chars.
- Every record is an **NCLAT appeal**. Label = appeal outcome:
  `DISMISSED 1,770 · ALLOWED 918 · REJECTED 39 · DISPOSED 5 · WITHDRAWN 3 · MODIFIED 1`.
- Only **1,310** unique cases cite IBC s.7 or s.9. **614** cite no IBC provision at all (Companies Act
  s.241/242 oppression, s.248/252 strike-off/restoration, CA 1956 s.397/398/433/434 legacy matters).
- Most-cited IBC sections (by #unique cases): 61 (872), 7 (841), 9 (619), 5 (446), 60 (404), 30 (385),
  31 (373), 8 (356), 14 (323), 3 (286), 53 (207), 33 (204), 238 (155), 25, 18, 29A, 10, 12, 4, 21, 65, 35, 95, 12A, 66 …
- Appellant can be: suspended director/promoter, financial creditor, operational creditor, RP/liquidator,
  resolution applicant, CoC, statutory authority (EPFO, tax, electricity), workmen/union, homebuyers,
  personal guarantor. The fixed "LEX-P = creditor / LEX-D = corporate debtor" mapping is wrong for most
  of the corpus.

**Decision:** simulate **Appellant vs Respondent over an impugned NCLT order**. Store `proceeding_type`
and `appellant_role` per case. Phase-1 scope = IBC cases only; Companies Act matters are out of scope
until the IBC pipeline works end to end.

### 3.2 Raw file defects

| Defect | Measurement | Handling |
|---|---|---|
| Not valid JSONL | Mixed: JSON arrays, pretty-printed arrays, multiple records glued on one line, broken delimiters | Robust loader using `json.JSONDecoder.raw_decode` (see §7.1) |
| Unrecoverable records | 3,005 `"precedent_id"` occurrences, 3,000 parsed → **5 lost** | Log them by file/offset; re-source manually later |
| Duplicates | **246 groups, 264 extra copies** (labels agree within groups — good) | Dedup; keep the longest/most complete record; record `source_files` |
| `precedent_id` collisions | **157 IDs** map to *different* cases (e.g. `2024_NCLAT_CH_32`); malformed IDs like `2024_NCLAT_DEL_172588877`, mixed `CH/CHE/CHN`, `DEL/NEW_DELHI` | Never use `precedent_id` as a key. Mint `case_uid` (§6.1) |
| `[cite: N]` artefacts | In **1,607** records, incl. inside `final_order` (`"DISMISSED[cite: 14]"`) and `forum`; in **24** law-DB entries | Strip with `\s*\[cite:[^\]]*\]` before anything else |
| Bench strings | "Principal Bench New Delhi" / "Principal Bench, New Delhi" / "New Delhi" / with member names | Normalise to `{bench_city, bench_members[]}` |
| Structured dates | `material_dates` present in **13** of 2,736 cases | Extraction pass (Phase 0, step 4) |
| `is_overruled` | 37 `true`; demonstrably incomplete — *Standard Chartered Bank v. Satish Kumar Gupta (RP of Essar Steel)*, NCLAT 04.07.2019, is `false`, but the Supreme Court reversed it in *CoC of Essar Steel v. Satish Kumar Gupta* (15.11.2019) | Rebuild from an authority/treatment table (§6.4) |
| Year distribution (unique) | 2016:10, 2017:348, 2018:155, 2019:46, 2020:469, 2021:504, 2022:156, 2023:145, 2024:340, 2025:367, 2026:196 | Drives the train/test split (§9) |
| Record fields | `precedent_id, case_title, appeal_number, forum, bench, decision_date, final_order, is_overruled, statutes_cited, material_facts, legal_issues, ratio_decidendi, operative_order, summary` (+ rare `material_dates`) | Partition into unspoiled vs ground truth (§6.1) |

Median field sizes: material_facts ≈1,450 chars, legal_issues ≈300, ratio ≈1,100, operative_order ≈220,
summary ≈720.

Note on "outcome language" in `material_facts`: ~133 records mention orders being "set aside", etc. On
inspection these are mostly the **procedural history below** (NCLT orders, earlier remands), which in an
appeal is legitimately part of the facts. Do not treat that as leakage; *do* run the leakage checks in §9.3.

### 3.3 Law DB defects

- 140 entries across 5 files; schema: `_id, statute_id, act_name, section_number, section_title,
  jurisdiction_type, forum_level, statutory_summary, core_judicial_inquiry, intersecting_statute_ids,
  diagnostic_checklist{applicant_eligibility, financial_threshold, mandatory_prerequisites,
  statutory_bars, saving_exceptions}, procedural_timelines, audit_error_codes`.
- **No verbatim statutory text.** Entries are LLM-written summaries. A "Textualist" judge reading a
  paraphrase is a contradiction. Add bare text from India Code / official Gazette.
- **No temporal versioning.** IBC has been amended repeatedly (2017, 2018, 2019, 2020 ×2, 2021). The law
  must be retrievable *as on* a date.
- **Wrong as encoded:** `IBC_2016_SEC_4` hard-codes `minimum_amount: 10000000` with no date logic (§5.1).
- **Two ID schemes**: law DB uses `CA2013_SEC241`, `NCLAT_RULES2016_R11`; precedents use
  `COMPANIES_ACT_2013_SEC_241`, `CA_2013_…`, `NCLAT_RULES_2016_RULE_11`, sub-clause suffixes
  (`IBC_2016_SEC_61_2`). Raw resolution 53%; **59% after alias mapping; 89% for IBC citations alone.**
- **Missing high-use provisions:** IBC s.10A (cited by 47 cases), 238A (53), 36 (78), 95–100 (personal
  guarantor; ~300 citations combined), 240A; Limitation Act s.12, 14, 19; NCLT Rules 2016 r.11 (126);
  CA 2013 s.2, 59, 212, 213, 248, 252; CA 1956 s.397/398/402/433/434.
- `PMLA_2002_SEC_8` duplicated. 181 `intersecting_statute_ids` (after aliasing) point to IDs that do not exist.

### 3.4 Defects in the original design documents

| Location | Problem | Fix |
|---|---|---|
| Part2 §5.3 Z3 code | Asserts `petition_admissible == True`; a legitimate-but-weak position (e.g. "limitation saved by s.18") becomes UNSAT → zero score → forced retry. The gate decides the merits, and Track A then measures the gate. | Gate checks **claims against the record**, never the legal conclusion (§8.3) |
| L4L predicates | Inputs (dates, amounts) do not exist in structured form | Phase-0 extraction with human verification |
| `≥ 10^7` | Threshold depends on filing date; applies to amount *in default* | §5.1 |
| `Δt ≤ 1095` | Limitation Act computes by British calendar (s.25) — "3 years", not 1,095 days; ignores COVID exclusion, s.14, s.5 | §5.2 |
| `∨ HasSection18Ack` | Acknowledgment must be **before expiry** and restarts limitation from its date | §5.2 |
| `¬FraudulentInitiation` | s.65 is a penalty provision, not an admission condition under s.7 | Remove |
| s.9 `Δt_notice ≥ 10` | s.9(1): filing only "after the expiry of" 10 days from delivery | `filing_date > delivery_date + 10 days` |
| s.9 `t_dispute < t_notice` | *Mobilox*: test is a plausible, pre-existing dispute, not merely date order | Date order is a necessary pre-filter only; plausibility is for the bench |
| Pragmatist judge | Refusing admission on viability is wrong in law (§5.6); commercial wisdom of CoC is non-justiciable | Narrow the persona (§8.5) |
| `S_local = S_smt·(0.3 S_rule + 0.7 S_llm)`, θ=0.70 | 70 % LLM-scored → not "deterministic"; weights/threshold uncalibrated | Hard checks are pass/fail with error codes; soft score calibrated on labelled turns |
| τ_C = 0.75, τ_dedup = 0.90 (bge-small) | bge cosine scores are compressed in-domain; thresholds arbitrary. Docs inconsistent (bge-small vs BGE-M3) | Calibrate on labelled pairs (§8.2, §8.6) |
| Memory dedup 0.90 | Embeddings are weak on negation: "X **is** financial debt" ≈ "X is **not** financial debt" | NLI/LLM contradiction check before merge |
| `W = Severity × Frequency` | Unbounded, no decay, wrong lessons never die, global top-K pinning ignores relevance | §8.6 |
| Reflection lessons | Over-generalise from one loss (e.g. "never treat deferred consideration as financial debt" — not a safe rule; *Orator Marketing* (SC 2021) shows financial-debt characterisation is fact-specific) | Ground each lesson in a ratio + provision scope; validate on held-out cases |
| Part2 §9.2 ingestion | Labels every case `ADMITTED`; ratio = `text[250:1200]`; dataset name unverified | Delete; not used |
| Part2 §9.3 clerk | Truncates judgments at 14,000 chars (judgments run 20–80 pages; operative order is at the end) | Not needed now — the curated DB replaces it. If PDFs are ingested later: chunk, section-detect, never truncate |
| Track A | No baseline; ~65 % of cases are dismissals | Report vs majority class; balanced accuracy, macro-F1 |
| Citation verification | Precedent DB is NCLAT-only; every Supreme Court cite (*Mobilox*, *Innoventive* …) would be flagged as hallucinated | Authority table with SC landmarks (§6.4) |
| Case count / models | "500 cases" vs ~2,736; GPT-4o-mini + Gemini named inconsistently | This file is the source of truth; models are config |
| Vocabulary | "Encrypted" ground truth, "epigenetic", "training reward" | Process isolation; "in-context learning"; "score" |

---

## 4. Leakage — the single biggest threat to validity

Three channels, all must be closed:

1. **Self-retrieval.** The case being simulated sits in the precedent store with its own ratio.
   Retrieval must exclude: the case itself, all its duplicates (by `case_uid` cluster), any case whose
   ratio cites it as "the impugned/same matter", and **every authority decided on or after the simulated
   case's NCLAT decision date** (temporal cutoff = NCLAT decision date, exclusive — authorities decided
   between the NCLT order and the NCLAT decision were legitimately available to the appellate bench).
2. **Model memorisation.** Frontier LLMs have likely read 2017–2023 NCLAT judgments.
   - Held-out test set = cases decided **after the newest model's training cutoff** used in the run
     (the 2025–2026 cases — 563 unique — are the natural pool; confirm per model).
   - **Contamination probe**: give the model only `case_title + appeal_number`, ask for the outcome and
     ratio. Accuracy materially above the base rate ⇒ contaminated; report it.
   - **Anonymise** what advocates and judges see: party names → role tokens (`[CORPORATE_DEBTOR]`,
     `[FINANCIAL_CREDITOR_1]`), appeal/CP numbers removed. **Do not shift dates** — that breaks limitation.
3. **Memory leakage.** Reflection memory is built on the training split only and **frozen** before any
   test-split run. Lessons extracted from ground truth must never be written while test cases are running.

Also: the unspoiled payload must not contain `ratio_decidendi`, `operative_order`, `summary`,
`final_order`, `is_overruled`. `legal_issues` is allowed (issues are framed before decision) but must
pass the neutrality check in §6.2.

---

## 5. Legal rules the system must encode correctly

Every rule below gets a unit test built from real cases in the DB. Items marked `VERIFY` must be checked
against the primary source (statute text / Gazette / SC judgment) before the rule is merged.

### 5.1 Minimum default (IBC s.4)
- ₹1,00,000 originally; raised to **₹1,00,00,000 by notification dated 24.03.2020** (S.O. 1205(E) — `VERIFY` number).
- Applied **prospectively**: the threshold in force on the **date the application was filed** governs
  (courts/tribunals have held it prospective — `VERIFY` forum and case name before citing it anywhere).
- Threshold applies to the **amount of default**, not the total claim.
- For s.7 the default may be to *any* financial creditor (Explanation to s.7(1)), not only the applicant.
- Real-estate allottee / class-creditor provisos to s.7(1) (100 or 10 %, whichever is less), inserted by
  the 2020 Amendment w.e.f. 28.12.2019; upheld in *Manish Kumar v. Union of India* (SC 2021).

### 5.2 Limitation for s.7 / s.9 applications
- Article 137, Limitation Act: **3 years from the date of default** (*B.K. Educational Services v. Parag
  Gupta*, SC 2018).
- Compute in calendar years (Limitation Act s.25, British calendar); exclude the day of default (s.12).
- **Acknowledgment (s.18)**: must be in writing, signed, and made **before the period expires**; a fresh
  period runs from the date of signing. Chainable. Balance-sheet entries can amount to acknowledgment
  (*Asset Reconstruction Co. v. Bishal Jaiswal*, SC 2021) — whether a given entry does is a fact question.
- **Part-payment (s.19)**: fresh period from date of payment, **only if the payment is made before the
  period expires** and is acknowledged in the handwriting of / a writing signed by the payer.
- **s.14 exclusion** (bona fide proceedings in a wrong forum) and **s.5 condonation** apply to s.7
  applications (*Sesh Nath Singh v. Baidyabati Sheoraphuli Co-op Bank*, SC 2021). s.238A applies the
  Limitation Act to IBC proceedings.
- **COVID exclusion**: Supreme Court suo motu order — period **15.03.2020 to 28.02.2022 excluded**; where
  limitation would have expired in that window, a 90-day period from 01.03.2022, or the longer actual
  balance remaining (`VERIFY` exact wording of the final order of 10.01.2022).
- Recovery certificate / decree can give a fresh cause (*Dena Bank v. C. Shivakumar Reddy*, SC 2021) — `VERIFY` scope before encoding.
- Personal guarantor default and acknowledgment interplay: *Laxmi Pat Surana v. Union Bank*, SC 2021 — `VERIFY` scope.

### 5.3 Section 10A bar
- No application under s.7/9/10 for a **default occurring on or after 25.03.2020, for one year (up to
  24.03.2021)**; the proviso bars filing for such defaults *ever*. Defaults before 25.03.2020 are not
  covered. Hard bar keyed on **date of default**. Law DB has no entry — add one.

### 5.4 Section 8 / 9 (operational creditor)
- Demand notice/invoice under s.8(1); corporate debtor has 10 days from **receipt** to point out a
  pre-existing dispute or pending suit/arbitration (s.8(2)).
- s.9(1): application only **after the expiry of 10 days from delivery** → `filing_date > delivery + 10d`.
- *Mobilox Innovations v. Kirusa Software* (SC 2017): reject if a **plausible, pre-existing** dispute
  exists; tribunal must not examine merits beyond seeing that the defence is not spurious/illusory.
  Rule engine checks only date ordering; plausibility is for the bench.

### 5.5 Section 7 admission
- On proof of debt + default (and a complete application, no disciplinary proceeding against proposed
  IRP), admission follows (*Innoventive Industries v. ICICI Bank*, SC 2017).
- *Vidarbha Industries v. Axis Bank* (SC 2022) read "may" in s.7(5)(a) as discretionary; *M. Suresh Kumar
  Reddy v. Canara Bank* (SC 2023) confined *Vidarbha* to its own facts. Net position: no general
  discretion to refuse admission on viability/hardship grounds.

### 5.6 Commercial wisdom and resolution plans
- CoC commercial wisdom is non-justiciable; tribunal review limited to s.30(2) compliance
  (*K. Sashidhar v. Indian Overseas Bank*, SC 2019; *CoC of Essar Steel v. Satish Kumar Gupta*, SC 2019).
- *Essar Steel* (SC) also: s.12 330-day outer limit is ordinarily binding but "mandatorily" was struck
  down — extension possible in exceptional cases.
- Approved plan binds all; un-included claims extinguished — "clean slate" (*Ghanashyam Mishra & Sons v.
  Edelweiss ARC*, SC 2021).
- s.29A eligibility: *ArcelorMittal India v. Satish Kumar Gupta* (SC 2018).

### 5.7 Appeals (the core of this dataset)
- **s.61(2)**: 30 days from the order; NCLAT may allow up to **15 further days** on sufficient cause;
  **no power beyond 45 days**. Limitation runs from **pronouncement** where the party is aware/present,
  not from receipt of certified copy (*V. Nagarajan v. SKS Ispat*, SC 2021). This is the most-cited
  provision (872 cases) and the best deterministic check in the system.
- **s.61(3)** — appeal against a s.31 approval order only on: (i) plan contravenes law in force;
  (ii) material irregularity by RP during CIRP; (iii) operational creditors' debts not provided for as
  specified by the Board; (iv) CIRP costs not provided for in priority; (v) plan fails other Board criteria.
- s.61(4): liquidation order — material irregularity or fraud. s.62: appeal to SC, 45 days + 15.
- Section 5 Limitation Act cannot extend beyond the s.61(2) cap.
- NCLT/NCLAT have no review power; recall under inherent power (NCLAT Rule 11 / NCLT Rule 11) on narrow
  grounds only.

### 5.8 Jurisdiction limits
- s.60(5)(c) residuary jurisdiction is confined to disputes arising *solely from or relating to* the
  insolvency (*Gujarat Urja Vikas Nigam v. Amit Gupta*, SC 2021); public-law matters go elsewhere
  (*Embassy Property Developments v. State of Karnataka*, SC 2019).
- Precedential hierarchy: Supreme Court binds all (Art. 141); NCLAT binds NCLT; NCLAT benches of equal
  strength bind each other unless referred to a larger bench.

### 5.9 Other landmarks to seed the authority table (all `VERIFY` treatment + date before use)
*Swiss Ribbons v. UoI* (2019, constitutionality, FC/OC distinction); *Pioneer Urban Land v. UoI* (2019,
homebuyers as FCs); *Anuj Jain (Jaypee Infratech)* (2020, preferential transactions / related-party
mortgages); *Phoenix ARC v. Spade Financial* (2021, related-party CoC exclusion); *Orator Marketing v.
Samtex Desinz* (2021, interest-free term loan as financial debt); *SBI v. V. Ramakrishnan* (2018,
moratorium and personal guarantors); *P. Mohanraj v. Shah Brothers Ispat* (2021, s.138 NI Act and
moratorium); *Lalit Kumar Jain v. UoI* (2021, personal guarantor notification upheld); *State Tax Officer
v. Rainbow Papers* (2022, statutory dues as secured — contested, track subsequent treatment);
*Dilip B. Jiwrajka v. UoI* (2023, Part III s.95–100 procedure).

Ethics/legal-practice constraints:
- Output is a **research simulation, not legal advice**. Every UI/export carries that notice.
- Party names in personal-guarantor and individual matters are personal data — anonymise in prompts,
  logs and any published artefact (Digital Personal Data Protection Act, 2023 considerations).
- Never present a simulated order as a real order; never generate anything styled as an official
  NCLT/NCLAT document.

---

## 6. Data model (target)

### 6.1 Canonical case record — `data/canonical/cases.jsonl`

```jsonc
{
  "case_uid": "NCLAT|DEL|CA(AT)(INS)|1528|2023",   // forum|bench|appeal type|number|year (normalised)
  "source": {"files": ["nclat_precedents/nclat_precedents1.jsonl"], "raw_precedent_ids": ["2024_NCLAT_DEL_1528"]},
  "forum": "NCLAT", "bench_city": "NEW_DELHI", "bench_members": [],
  "decision_date": "2024-01-19",
  "proceeding_type": "SEC61_APPEAL_LIMITATION",   // enum, see §6.3
  "appellant_role": "OTHER_STAKEHOLDER",          // enum
  "respondent_roles": ["RESOLUTION_PROFESSIONAL"],
  "in_scope": true,                                // IBC-only for Phase 1
  "unspoiled": {
    "material_facts": "...",                       // [cite] stripped, anonymised copy in "material_facts_anon"
    "legal_issues": ["...", "..."],
    "statutes_cited": ["IBC_2016_SEC_61", "LIMITATION_ACT_1963_SEC_14"],  // canonical IDs
    "typed_facts": { /* §6.2 */ }
  },
  "ground_truth": {
    "label": "DISMISSED",                          // ALLOWED | DISMISSED | PARTLY_ALLOWED | REMANDED | WITHDRAWN | DISPOSED
    "ratio_decidendi": "...", "operative_order": "...", "summary": "...",
    "authorities_relied": []                       // extracted later
  },
  "treatment": {"is_overruled": false, "overruled_by": null, "source": "authority_table_v1"},
  "split": "train",                                // train | dev | test
  "quality": {"dedup_cluster_size": 1, "typed_facts_verified": false, "issues_neutral": true}
}
```

The ground-truth partition lives in a **separate file** (`ground_truth.jsonl`) keyed by `case_uid`;
runtime agents/judges are given a loader that physically cannot read it. THEMIS-GLOBAL/eval loads it
after the trial is sealed.

### 6.2 Typed facts (extraction target; every field nullable, every value carries evidence)

```jsonc
"typed_facts": {
  "date_of_default":        {"value": "2017-04-01", "evidence": "<quoted span>", "confidence": 0.9},
  "date_of_npa":            {...},
  "demand_notice_delivery": {...},
  "notice_of_dispute_date": {...},
  "acknowledgments":        [{"date": "...", "kind": "BALANCE_SHEET|LETTER|OTS|PART_PAYMENT", "evidence": "..."}],
  "nclt_filing_date":       {...},
  "impugned_order_date":    {...},
  "appeal_filing_date":     {...},
  "certified_copy_applied": {...},
  "amount_in_default_inr":  {...},
  "claim_amount_inr":       {...},
  "cirp_commencement_date": {...},
  "liquidation_order_date": {...}
}
```
Rules: value must be copied from or computed from a quoted span; `null` if absent — never inferred.
Ambiguous dates (DD.MM vs MM.DD) are resolved as DD.MM.YYYY (Indian convention) and flagged.

Neutrality check for `legal_issues`: LLM classifier + regex for answer-bearing phrasing ("whether the
NCLT *rightly* rejected…", "*erred*…"). Leading issues are rewritten neutrally, original kept in
`legal_issues_original`.

### 6.3 Enums
- `proceeding_type`: `SEC7_ADMISSION`, `SEC9_ADMISSION`, `SEC10_ADMISSION`, `SEC12A_WITHDRAWAL`,
  `MORATORIUM_SEC14`, `CLAIMS_VERIFICATION`, `COC_CONSTITUTION`, `RESOLUTION_PLAN_APPROVAL`,
  `SEC29A_ELIGIBILITY`, `LIQUIDATION`, `AVOIDANCE_43_66`, `SEC60_5_JURISDICTION`,
  `SEC61_APPEAL_LIMITATION`, `PERSONAL_GUARANTOR_95_100`, `IP_DISCIPLINARY`, `RECALL_REVIEW`,
  `COMPANIES_ACT_241_242`, `COMPANIES_ACT_STRIKE_OFF`, `OTHER`.
- `appellant_role`: `FINANCIAL_CREDITOR`, `OPERATIONAL_CREDITOR`, `SUSPENDED_DIRECTOR_PROMOTER`,
  `SHAREHOLDER`, `CORPORATE_DEBTOR`, `RESOLUTION_PROFESSIONAL`, `LIQUIDATOR`, `RESOLUTION_APPLICANT`,
  `COC`, `STATUTORY_AUTHORITY`, `WORKMEN_EMPLOYEES`, `HOMEBUYERS`, `PERSONAL_GUARANTOR`, `IBBI`, `OTHER`.

### 6.4 Authority table — `data/canonical/authorities.jsonl`
One row per authority (SC + NCLAT + High Courts as needed):
`authority_uid, court, title, date, citation_strings[] (only verified ones), propositions[] (short, each
with provision scope), treatment[] ({by_uid, kind: FOLLOWED|DISTINGUISHED|OVERRULED|REVERSED|STAYED,
date}), status_as_of(date) -> GOOD_LAW|REVERSED|OVERRULED|DOUBTED`.
`status_as_of` is computed at the same cutoff as §4 (NCLAT decision date, exclusive) (a 2018 NCLAT view was good law in 2018 even if
reversed in 2019 — the simulation must reflect the law as it stood).

### 6.5 Law DB v2 — `data/canonical/laws.jsonl`
Keep the existing checklist fields, add: `canonical_id`, `aliases[]`, `bare_text` (verbatim),
`versions[] ({effective_from, effective_to, bare_text, amending_instrument})`, `source_url`.
Lookup API: `get_provision(id, as_of=date)`.

---

## 7. Implementation conventions

### 7.1 Robust raw loader (proven on all 12 files)
```python
import json, re
from pathlib import Path

CITE = re.compile(r"\s*\[cite:[^\]]*\]")

def iter_raw_records(path: Path):
    txt = path.read_text(encoding="utf-8")
    dec, i, n = json.JSONDecoder(), 0, len(txt)
    while i < n:
        while i < n and txt[i] in " \t\r\n,[]":
            i += 1
        if i >= n:
            break
        try:
            obj, i = dec.raw_decode(txt, i)
        except json.JSONDecodeError as e:
            yield {"_parse_error": str(e), "_file": str(path), "_offset": i}
            nxt = txt.find("\n", i)
            i = n if nxt < 0 else nxt + 1
            continue
        for rec in (obj if isinstance(obj, list) else [obj]):
            rec["_file"] = str(path)
            yield rec
```
Strip `CITE` from **every string field** (including `final_order`, `forum`) before normalising.
Some parse-failure segments contain recoverable records after the broken one — a second pass that
searches for the next `{"precedent_id"` from the error offset recovers most of them.

### 7.2 Proposed package layout
```
lexarena/
  config/            settings.py (pydantic-settings), models.yaml, thresholds.yaml
  schemas/           pydantic models: Case, TypedFacts, Authority, Provision, Turn, Verdict, Lesson
  ingest/            load_raw.py, normalise.py, dedup.py, statute_alias.py, extract_typed_facts.py,
                     classify_proceeding.py, neutralise_issues.py, anonymise.py, split.py, build_all.py
  law/               provisions.py (as_of lookup), authorities.py (status_as_of)
  rules/             limitation.py, threshold.py, sec10a.py, sec9_notice.py, sec61_appeal.py, smt.py
  retrieval/         index.py (BM25 + dense), search.py (filters: leave-one-out, temporal cutoff), rerank.py
  agents/            advocate.py, prompts/, strategy.py
  themis/            local.py (claim extraction + checks), global_.py, error_codes.py
  bench/             personas.py, judge.py, aggregator.py
  memory/            reflect.py, store.py, select.py
  eval/              metrics.py, baselines.py, contamination_probe.py, human_study/
  orchestrator/      graph.py (state machine), run_case.py, run_batch.py
  llm/               client.py (provider-agnostic, retries, caching, cost + prompt-hash logging)
data/
  canonical/         cases.jsonl, ground_truth.jsonl, authorities.jsonl, laws.jsonl, splits/
  reports/           data_audit.md, extraction_qa.csv
runs/                <run_id>/ transcripts, audits, verdicts, metrics.json, config snapshot
tests/               unit tests per rule with real-case fixtures; ingest tests; leakage tests
```
Leave the raw folders where they are; reference them via config.

### 7.3 Engineering rules
- Python 3.12, `pydantic` v2 for every schema and every LLM structured output, `pytest`, `ruff`.
- All LLM calls go through `llm/client.py`: provider/model from config, temperature recorded, response
  cached by `(model, prompt_hash)`, tokens + cost logged per call, seed recorded where supported.
- Advocates and judges should use **different model families** where feasible (reduces self-preference
  bias); record which in every run.
- Storage: start with JSONL + a local Qdrant (embedded mode) — it's enough for ~3k cases. Add MongoDB only
  when concurrent runs or the human-review UI need it; keep a repository interface so the swap is local.
- Every run writes a frozen config snapshot and git SHA into `runs/<run_id>/`.
- Windows: no hard-coded `/tmp`; use `pathlib` and the configured data dir.

---

## 8. Target architecture (revised)

### 8.1 Case lifecycle
```
canonical case (unspoiled, anonymised)
  → Clerk: assemble case file (facts, neutral issues, typed facts, provisions as_of date)
  → Retrieval: authorities filtered (leave-one-out, temporal cutoff, good-law-as-of) → top-k
  → Debate (appeal-shaped turns, §8.4), every turn → THEMIS-LOCAL
  → Seal transcript
  → Bench: persona judges → aggregator → reasoned order + label + issue-wise findings
  → THEMIS-GLOBAL audit
  → Unseal ground truth → metrics
  → (train split only) Reflection → memory
```

### 8.2 Retrieval
- Index units: authority **propositions** (ratio split per issue) + issues + facts, not facts alone.
- Hybrid: BM25 (legal terms, section numbers matter) + dense (bge-m3 or bge-base; pick one, record it)
  + statute-ID filter + cross-encoder reranker.
- Hard filters: `uid ∉ dedup_cluster(case)`, `date < cutoff(case)`, `status_as_of(cutoff) == GOOD_LAW`
  (or include with an explicit "reversed on …" tag, never silently).
- Threshold: calibrated on a labelled set of (case, relevant authority) pairs drawn from the train split
  — e.g. authorities a ratio actually relies on. Choose τ to hit a target precision; report recall.
- Always include the controlling SC authority for the provision if one exists (rule-based, not similarity).

### 8.3 THEMIS-LOCAL (per turn)
1. **Claim extraction** (LLM, structured): dates, amounts, day-counts, provision references, authority
   citations with the proposition attributed to each, factual assertions about the record.
2. **Hard checks** (deterministic, pass/fail + error code):
   - Asserted date/amount ≠ record typed fact → `ERR_FACT_MISMATCH`.
   - Asserted arithmetic wrong (day counts, limitation expiry computed by `rules/`) → `ERR_ARITHMETIC`.
   - Cited provision doesn't exist / not in force on the relevant date → `ERR_PROVISION_NOT_IN_FORCE`.
   - Cited authority not in authority table → `ERR_UNVERIFIED_AUTHORITY`; decided after cutoff →
     `ERR_ANACHRONISTIC_AUTHORITY`; reversed as of cutoff and presented as good law → `ERR_BAD_LAW`.
   - Attributed proposition contradicts the stored propositions (NLI) → `ERR_MISATTRIBUTED_RATIO`.
3. **What it never does**: reject a turn because the agent's *legal position* would lose. An agent may
   argue limitation is saved; the gate only checks that the dates and acknowledgments it relies on are
   real and the arithmetic is right.
4. **Z3's role**: when typed facts are uncertain (null or ranged, e.g. "acknowledgment sometime in FY
   2018-19"), encode them as bounded variables and ask both `∃ assignment: within limitation` and
   `∀ assignment: within limitation`. Report `ALWAYS / POSSIBLY / NEVER`. That is a real reason to use an
   SMT solver; plain comparisons on known dates are plain Python.
5. On failure: return the error codes + evidence to the agent; max 2 retries; then publish with the flags
   visible to the opponent and the bench. Penalty is a count of hard-check failures, reported separately
   from the bench score (do not blend into one opaque number).
6. Soft grounding score (optional): LLM-graded 1–5 rubric, calibrated against ~200 lawyer-labelled turns
   before it is allowed to gate anything.

### 8.4 Debate structure (mirrors real NCLAT practice)
| Turn | Speaker | Real-world analogue |
|---|---|---|
| 1 | Appellant | Memo of appeal: grounds against the impugned order |
| 2 | Respondent | Reply affidavit |
| 3 | Appellant | Rejoinder |
| 4 | Appellant | Oral arguments (opening) |
| 5 | Respondent | Oral arguments |
| 6 | Appellant | Reply arguments |
| 7 | Bench | Questions to both sides (judge-generated, issue-targeted) |
| 8–9 | Respondent, Appellant | Answers to bench questions |
| 10–11 | Both | Short written submissions |
Scope of grounds is enforced by proceeding type (e.g. s.61(3) grounds only, for plan-approval appeals).
The record is closed: no new facts after turn 3 (as in an appeal confined to the record), except
facts the bench asks about.

### 8.5 Bench
- Personas (all bound by the same law; they differ in emphasis, not in which law applies):
  - **Textualist** — plain meaning of the provision as in force on the relevant date; reads `bare_text`.
  - **Purposive / Commercial** — purpose of the Code (time-bound resolution, value maximisation) *within
    the limits of §5.5–5.6*: never refuses admission on viability, never second-guesses CoC commercial
    wisdom; operates on interpretation, s.12A, s.29A, s.60(5) boundaries, equitable treatment within s.30(2).
  - **Proceduralist** — limitation, s.61 timelines, notice/service, record compliance, jurisdiction.
- Real NCLAT benches are usually two members (judicial + technical), sometimes three. Present the
  personas as an **ensemble for reasoning diversity**, not as realism.
- Each judge outputs, per framed issue: finding, reasons, authorities relied (must pass THEMIS checks),
  and a final label. Aggregator: majority on label; issue-wise reasoning merged; dissent recorded.
- Bias controls: side-swap test (swap appellant/respondent labels in the transcript), length-normalised
  scoring check, different model family from advocates.

### 8.6 Reflection memory
- Built **only on the train split**; frozen before dev/test runs.
- A lesson = `{text, scope: {provisions[], proceeding_types[], appellant_role?}, polarity, source_case_uid,
  grounded_in: authority_uid or ratio span, severity 1–5, uses, wins_when_used, losses_when_used,
  created_at, last_used_at}`.
- Merge only if cosine ≥ τ (calibrated) **and** an NLI check says "entailment" (not contradiction).
- Utility, not frequency: `score = severity × (wins_when_used + 1)/(uses + 2) × decay(age)`; lessons
  whose use correlates with losing are retired.
- Selection: retrieve by scope + relevance to the current case, then pack within the token budget. No
  global "banned anti-patterns" list.
- A lesson that states law must agree with the law DB / authority table as of the case date, else rejected.

---

## 9. Evaluation protocol

### 9.1 Splits
- `train`: decided ≤ 2023-12-31 · `dev`: 2024 · `test`: 2025–2026 (confirm all test cases are after the
  newest model cutoff; drop or flag any that aren't).
- Stratify reporting by `proceeding_type` and `appellant_role`.
- Dedup clusters never span splits.

### 9.2 Metrics
- **Outcome**: accuracy, **balanced accuracy, macro-F1**, always beside the **majority-class baseline
  (≈65 % "DISMISSED")** and a **single-LLM baseline** (one model reads the unspoiled case, predicts).
- **Issue-level alignment**: per framed issue, does the simulated finding match the real ratio? LLM-graded
  with a rubric, with ≥100 issues double-checked by a lawyer; report agreement (Cohen's κ).
- **Hallucination**: unverified/anachronistic/bad-law citations per 1,000 tokens, before and after THEMIS.
- **Fact fidelity**: `ERR_FACT_MISMATCH` + `ERR_ARITHMETIC` rate per turn.
- **Adversarial quality**: rebuttal responsiveness (does turn t+1 address the claims of turn t), cross-turn
  self-contradiction rate.
- **Memory effect**: dev metrics with memory frozen at 0, 100, 300, all train cases (learning curve).
- **Ablations**: no THEMIS · no retrieval · no memory · single judge vs bench · same vs different model
  family for judges.
- Report confidence intervals (bootstrap over cases).

### 9.3 Leakage / contamination tests (run before any reported number)
- Retrieval leakage test: for every test case, assert no retrieved item is in its dedup cluster or dated ≥ cutoff.
- Contamination probe per model (§4.2).
- Ground-truth isolation test: grep every prompt sent during a test run for ratio/operative-order substrings.

### 9.4 Human study (Track B)
- 3–5 practising IBC lawyers; 30–50 test cases; blind to AI verdict and real outcome.
- Each lawyer reads the same unspoiled case + transcript, gives label + issue-wise findings.
- Report: lawyer–lawyer agreement (Krippendorff's α), AI–lawyer agreement, AI–real-outcome agreement, and
  qualitative error taxonomy (statutory misread, wrong-date law, bad authority, procedure error, over-formalism, over-equity).

---

## 10. A-to-Z build plan

Status keys: `[ ]` todo · `[~]` in progress · `[x]` done. Update this section as you work.

### Phase 0 — Data foundation (nothing downstream is trustworthy until this is done)
- [ ] **A. Raw loader** (`ingest/load_raw.py`, §7.1). Recover the 5 lost records if possible; log the rest.
      *Accept*: 3,000+ records loaded; parse-error report written to `data/reports/data_audit.md`.
- [ ] **B. Clean & normalise**: strip `[cite]`; normalise `final_order` → label enum (`PARTLY_ALLOWED`
      and `REMANDED` do not exist in raw `final_order` — parse them from `operative_order`); bench → city +
      members; `forum`; dates ISO.
- [ ] **C. Dedup + `case_uid`**: cluster by normalised title + decision date (tiebreak: appeal number +
      bench); merge sources; mint `case_uid`. *Accept*: 2,736 ± small unique cases; zero `case_uid`
      collisions; report of the 157 old-ID collisions.
- [ ] **D. Statute alias map** (`ingest/statute_alias.py`): one canonical ID scheme; map both raw schemes;
      collapse sub-clauses to section for lookup while keeping the sub-clause. *Accept*: IBC citation
      resolution ≥ 89 % now, ≥ 98 % after step E.
- [ ] **E. Law DB v2**: add missing provisions (§3.3), verbatim bare text, version history for amended
      sections (at minimum s.4, 5(8), 7, 10A, 12, 12A, 29A, 30, 32A, 61, 238A, 240A), fix s.4 threshold
      logic, dedupe PMLA s.8, strip `[cite]`. Source: India Code / Gazette; record `source_url`.
- [ ] **F. Proceeding-type + appellant-role classification** (LLM + rules from statutes_cited; human
      check 100). *Accept*: ≥ 90 % agreement on the checked sample.
- [ ] **G. Typed-fact extraction** (§6.2) with evidence spans. Human-verify 50 cases stratified by
      proceeding type. *Accept*: ≥ 95 % precision on non-null dates; null when absent.
- [ ] **H. Issue neutrality pass** (§6.2).
- [ ] **I. Anonymisation** of unspoiled text (keep original in a non-runtime field).
- [ ] **J. Authority table v1** (§6.4): seed SC landmarks (§5) + all NCLAT cases; extract authorities
      relied on from each ratio; rebuild `is_overruled` via treatment. Must include: Essar NCLAT 2019 →
      REVERSED by SC 15.11.2019. Every SC entry verified by a human against the judgment.
- [ ] **K. Splits** (§9.1) + **contamination probe** baseline per candidate model.
- [ ] **L. Data audit report** regenerated by `ingest/build_all.py` (one command, reproducible).

### Phase 1 — Rule engine (deterministic, test-first)
- [ ] **M. `rules/`**: s.4 threshold by filing date; Art.137 limitation with s.12/s.25 calendar
      arithmetic, s.18 chained acknowledgments (before-expiry check), s.19, COVID exclusion, s.14
      exclusion periods, s.10A bar; s.8/s.9 notice timing; s.61(2) 30+15 cap from pronouncement; s.62.
- [ ] **N. Tests**: ≥ 5 real-case fixtures per rule from the DB (cases where the NCLAT decided the point),
      plus edge cases (leap years, acknowledgment one day after expiry, filing on day 10 vs 11, 46-day appeal).
- [ ] **O. `rules/smt.py`**: ALWAYS/POSSIBLY/NEVER evaluation over uncertain facts (§8.3.4).

### Phase 2 — Retrieval
- [ ] **P. Index** propositions/issues/facts; BM25 + dense + reranker.
- [ ] **Q. Filters**: leave-one-out cluster, temporal cutoff, status-as-of. Leakage unit tests.
- [ ] **R. Calibrate** τ on train pairs; report precision/recall.

### Phase 3 — Agents and THEMIS-LOCAL
- [ ] **S. LLM client** (provider-agnostic, caching, cost logs).
- [ ] **T. Advocate agents**: role-aware prompts by `appellant_role`/`proceeding_type`; turn schema
      (§8.4); structured output (claims list + prose).
- [ ] **U. THEMIS-LOCAL** (§8.3) with error codes; retry loop; flags visible to opponent/bench.
- [ ] **V. Orchestrator** state machine (LangGraph or plain Python — plain Python is fine and easier to test).
- [ ] **W. Smoke run** on 10 dev cases; lawyer reads every transcript; fix prompts.

### Phase 4 — Bench, global audit, metrics
- [ ] **X. Bench** personas (§8.5), aggregator, issue-wise order.
- [ ] **Y. THEMIS-GLOBAL** + `eval/metrics.py` + baselines + ablation runner.
- [ ] **Z.1 Dev evaluation** (full dev split) with baselines and CIs.

### Phase 5 — Memory, test, human study, write-up
- [ ] **Z.2 Reflection memory** on train (§8.6); learning curve on dev.
- [ ] **Z.3 Frozen test run** (one shot; no tuning after looking at test).
- [ ] **Z.4 Human study** (§9.4).
- [ ] **Z.5 Review UI** (Streamlit is enough): transcript viewer, THEMIS flags, bench order, ground-truth
      reveal, lawyer annotation form. Research-simulation disclaimer on every page.
- [ ] **Z.6 Paper/report + panel defence** (§11).

---

## 11. Panel defence — questions you will get, and honest answers

| Question | Answer |
|---|---|
| "Isn't 65 % accuracy trivial?" | Yes — that's the always-dismiss baseline; we report balanced accuracy and macro-F1 against it, plus a single-LLM baseline. |
| "How do you know the model didn't just remember the case?" | Test set is post-cutoff 2025–26 decisions; names anonymised; contamination probe reported per model. |
| "Why Z3 if you're comparing two dates?" | We don't use it for that. Z3 evaluates limitation/threshold when facts are uncertain or disputed — ALWAYS/POSSIBLY/NEVER — which plain comparison can't. |
| "Doesn't your verifier decide the case?" | No. It checks facts, arithmetic and citations against the record; it never rejects a legal position. |
| "A pragmatist judge refusing admission is wrong in law." | Agreed — persona is constrained to purposive interpretation within *Innoventive* / *Suresh Kumar Reddy* / *K. Sashidhar*. |
| "Are your precedents still good law?" | Authority table with treatment; status computed as of the simulated case's date; reversed authorities are tagged, never silently used. |
| "Which version of the statute?" | Provision lookup is `as_of(date)`; s.4 threshold keyed to filing date; s.10A keyed to default date. |
| "Is this learning or prompt stuffing?" | In-context learning; memory frozen before test; learning curve on dev shows the effect (or its absence — we report either). |
| "Three-judge bench isn't how NCLAT sits." | Correct; it's a reasoning ensemble. Real benches are typically judicial + technical members. |
| "Data quality?" | Audit report: 264 duplicates removed, 157 ID collisions fixed, cite artefacts stripped, typed facts human-verified on a stratified sample. |

---

## 12. Decisions log

| Date | Decision | Why |
|---|---|---|
| 2026-10-04 | Simulate NCLAT appeals (Appellant vs Respondent), not NCLT petitions | That is what the data is |
| 2026-10-04 | Phase-1 scope = IBC cases only (≈2,120 unique); Companies Act cases deferred | 614 non-IBC cases need a different law DB and rules |
| 2026-10-04 | THEMIS-LOCAL checks claims vs record; never legal merit | Otherwise the gate decides the case |
| 2026-10-04 | Test split = 2025–2026 decisions | Memorisation control |
| 2026-10-04 | JSONL + embedded Qdrant first; MongoDB later behind an interface | 3k cases don't need a cluster; faster iteration |
| 2026-10-04 | Original docs kept as history; this file is source of truth | Avoid silent conflicts |

## 13. Open questions (ask the project owner before deciding)
- Which LLM providers/models and budget are available? (Docs mention Gemini and GPT-4o-mini; the
  choice affects the test-split cutoff check.)
- Are 3–5 practising lawyers available for the human study and for verifying the authority table?
- Is there access to the original judgment PDFs (needed to re-check typed facts and to recover the
  5 lost records)?
- Deadline / which phases must be done for the next evaluation milestone?

## 14. Glossary
CIRP — corporate insolvency resolution process · CD — corporate debtor · FC/OC — financial/operational
creditor · RP/IRP — (interim) resolution professional · CoC — committee of creditors · AA — Adjudicating
Authority (NCLT) · NCLAT — appellate tribunal · PG — personal guarantor · L4L — logic-for-law predicates ·
Unspoiled — pre-decision case material visible to agents · Ground truth — the real order, sealed until
evaluation · Cutoff — date after which no authority may be used for a given simulated case.
