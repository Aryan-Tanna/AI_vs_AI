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
   30/31, 33, 43–66, 60(5), 61 and 95–100 matters (and any other IBC provision, including ones the law DB
   does not yet cover), and appeals to the Supreme Court under Section 62. You care
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
- **THEMIS-GLOBAL**: whole-transcript audit run **before the bench** (consistency, claim drift, rebuttal
  responsiveness, hallucination); its findings (never a verdict) are an input to the judges.
- **Reflection memory**: in-context learning across cases (no fine-tuning), built on a training split only.
- **Evaluation**: outcome alignment with the real NCLAT order (against baselines), issue-level reasoning
  alignment, hallucination rate, and human-lawyer vs AI-judge divergence.

**Two databases — do not confuse them:**

| | Reference DBs (exist) | Public case DB (to build) |
|---|---|---|
| What | `nclat_precedents*/` (≈2,736 unique NCLAT case summaries), `law_db/`, `law2db/` | ~500 NCLAT appeals built from the **original judgment + impugned-order PDFs** |
| Role | Retrieval store (precedents/authorities) and law lookup | The cases that are simulated, used for reflection memory (train) and scoring (dev/test) |
| Provenance | LLM-written summaries (`[cite: N]` artefacts), no source URLs | Every fact carries a source pointer (doc/page/para); human-verified |
| Spec | §3 (audit), §6.1, §6.4, §6.5 | §6.6 |

The reference DBs are **not** a training or evaluation set. Metrics are computed only on the public case
DB. Any public case that also appears in the reference DB must be excluded from its own retrieval (§4).

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
public_db/                <- (planned) public case DB, §6.6 — sources/, manifest.jsonl, unspoiled.jsonl,
                             ground_truth.jsonl, splits/
```

Code so far: `scripts/audit_raw.py` (audit; its loader is the basis for `ingest/load_raw.py`); the
`lexarena/` session runtime (§7.4): config, Claude-subscription agent backend, cache, usage ledger, job
queue, session runner, record tools, smoke/baseline/debate handlers, CLI; the public case DB schema +
validator (§6.6, `scripts/validate_public_db.py`, `scripts/export_schemas.py`); THEMIS-LOCAL gate control
flow (§8.3); the rule engine + Z3 (`lexarena/rules/`, build Phase 1); reference DB ingest (`ingest/`),
retrieval (`retrieval/`), law/authority lookups (`law/`), research tools (`tools/research.py`), THEMIS-LOCAL
Stage A/B + extractor wired into the debate handler (build Phases 0a, 2, 3). 94 tests in `tests/`.
Architecture in text + image: `docs/ARCHITECTURE.md`, `docs/architecture.png`. Git: the raw data and
docs are in the initial commit. Two raw filenames contain a space / `&` (`company act.json`,
`ncalt&nclt.json`); do not rename raw files — map them to clean IDs in config. Platform is Windows 11,
Python 3.13.5 (Anaconda; code targets ≥ 3.12). Use `pathlib`, UTF-8 everywhere (`encoding="utf-8"` on every open), no shell-specific paths.

---

## 3. Findings from the audit of the reference DBs (measured, not assumed)

Everything in §3 describes the **reference DBs**. It informs retrieval, law lookup and how the public
case DB is sampled; it is not the evaluation set.

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

**Decision:** simulate **Appellant vs Respondent over an impugned NCLT order**, matching the reference DB.
Store `proceeding_type` and `appellant_role` per case. The public case DB (§6.6) is IBC appeals only in
Phase 1; Companies Act matters are out of scope until the IBC pipeline works end to end (they stay in
the reference DB for retrieval).

Caution on s.61 counts: every IBC appeal is filed under s.61, so "872 cases cite s.61" reflects the appeal
route, not limitation disputes. Only ~180 of those cases have limitation/delay/condonation in their
issues, and the appeal filing date is usually absent from the summaries.

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
| Coarse labels | `final_order` is ALLOWED/DISMISSED, but **288** operative orders say remand/remit/restore and **126** say partly/modified | Public DB uses the finer label enum (§6.6.3) |
| Dedup misses | **22** appeal numbers map to >1 "unique" case; **21** dup groups merge consolidated appeals with different numbers | Cluster on appeal numbers too; `case_uid` holds `appeal_numbers[]` |
| `legal_issues` type | A single string in all records (not a list) | Split into issues during ingest |
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

1. **Self-retrieval.** A public case being simulated will often also sit in the reference precedent store
   with its own ratio. Retrieval must exclude: its reference-DB copies (via
   `manifest.overlap_with_reference_db`, §6.6.4) and all their duplicates (by `case_uid` cluster), any case whose
   ratio cites it as "the impugned/same matter", and **every authority decided on or after the simulated
   case's NCLAT decision date** (temporal cutoff = NCLAT decision date, exclusive — authorities decided
   between the NCLT order and the NCLAT decision were legitimately available to the appellate bench).
2. **Model memorisation.** Frontier LLMs have likely read 2017–2023 NCLAT judgments.
   - Public-DB test split = cases decided **after the newest model's training cutoff** used in the run
     (2025–2026 decisions are the natural pool; confirm per model and drop any that aren't).
   - **Contamination probe**: give the model only `case_title + appeal_number`, ask for the outcome and
     ratio. Accuracy materially above the base rate ⇒ contaminated; report it.
   - **Anonymise** what advocates and judges see: party names → role tokens (`[CORPORATE_DEBTOR]`,
     `[FINANCIAL_CREDITOR_1]`), appeal/CP numbers removed. **Do not shift dates** — that breaks limitation.
3. **Memory leakage.** Reflection memory is built on the training split only and **frozen** before any
   test-split run. Lessons extracted from ground truth must never be written while test cases are running.

Also: the public case's unspoiled payload (§6.6.2) must not contain the ratio, operative order, label,
bench findings, authorities the bench relied on, bench member names, or real party names. Issues are
allowed (framed before decision) but must pass the neutrality check in §6.2. Parties' grounds and
contentions are allowed only where the judgment records them separately from the bench's analysis.

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

§6.1–6.5 cover the **reference DBs** (retrieval/law lookup); §6.6 covers the **public case DB** (simulation
and evaluation). §6.2 typed facts and §6.3 enums are shared by both.

### 6.1 Canonical reference precedent record — `data/canonical/cases.jsonl`

Reference records are not simulated or scored, so they have no split. They keep their ratio in a
retrievable form; the leakage controls of §4 work through retrieval filters, not by hiding fields.

```jsonc
{
  "case_uid": "REF-3f9a2c1d",                      // hash of the dedup cluster (consolidated appeals break a number-based key)
  "appeal_numbers": ["CA(AT)(INS) 1528/2023"],     // normalised; one entry per connected appeal
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
  "public_case_uid": null,                         // set if this case is also in the public case DB (§6.6)
  "quality": {"dedup_cluster_size": 1, "typed_facts_verified": false, "issues_neutral": true}
}
```

(Field names `unspoiled` / `ground_truth` above just group the summary fields; for reference records
nothing is sealed. Sealing applies to the public case DB, §6.6.)

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

### 6.6 Public case DB — `public_db/` (simulation + evaluation corpus, ~500 cases)

Built from the **original NCLAT judgment and impugned NCLT order PDFs**, not from the reference-DB
summaries. Phase 1: IBC appeals only.

#### 6.6.1 Layout
```
public_db/
  sources/<case_uid>/            judgment.pdf, impugned_order.pdf (sha256 recorded in manifest)
  manifest.jsonl                 provenance, split, QA, overlap links      (build + eval only)
  unspoiled.jsonl                what advocates and judges see             (runtime)
  ground_truth.jsonl             the real NCLAT decision                   (eval only, sealed)
  splits/{train,dev,test}.txt    case_uid lists
```
All three JSONL files are keyed by `case_uid`. The runtime loader can only open `unspoiled.jsonl`;
THEMIS-GLOBAL/eval opens `ground_truth.jsonl` only after the transcript is sealed.

**Source of truth for the structure: `lexarena/schemas/public_case.py`** (Pydantic; the JSON below is an
abridged illustration). Field guide: `docs/schema/README.md`. JSON Schemas: `docs/schema/*.schema.json`
(`scripts/export_schemas.py`; a test fails if they are stale). Complete valid example: `docs/schema/example/`
(synthetic; rejected by the validator inside `public_db/`). Cross-file validator:
`python scripts/validate_public_db.py`. "Training" here means the train split feeds reflection memory and
prompt development; no model weights are trained.

Source pointers everywhere: `src: [{"doc": "JUDGMENT" | "IMPUGNED", "page": int, "para": str}]`.

#### 6.6.2 `unspoiled.jsonl` — everything that existed before the NCLAT decided; anonymised
```jsonc
{
  "case_uid": "PC-0001",                       // opaque; never encode bench/number (they identify the case)
  "schema_version": "1.0",
  "title_anon": "[FINANCIAL_CREDITOR_1] v. [SUSPENDED_DIRECTOR_1]",
  "forum": "NCLAT",
  "bench_city": "NEW_DELHI",                   // city only; member names hidden (they correlate with outcome)
  "law_as_of": "2024-01-18",                   // date for get_provision / status_as_of (= decision date − 1)
  "proceeding_type": "SEC7_ADMISSION",         // §6.3
  "appellant_role": "SUSPENDED_DIRECTOR_PROMOTER",
  "respondent_roles": ["FINANCIAL_CREDITOR", "RESOLUTION_PROFESSIONAL"],
  "parties": [{"token": "[CORPORATE_DEBTOR]", "kind": "COMPANY", "description": "real-estate developer"}],

  "impugned_order": {                          // the NCLT order under appeal — part of the record
    "forum": "NCLT", "bench_city": "NEW_DELHI", "date": "2023-08-10",
    "application_type": "SEC7", "outcome_below": "ADMITTED",
    "reasoning_summary": "…", "operative_part": "…", "src": [ ... ]
  },

  "chronology": [                              // backbone for typed facts and the rule engine
    {"id": "E1", "date": "2016-03-31", "date_precision": "DAY",   // DAY | MONTH | FY | RANGE
     "event": "Loan account classified NPA", "actor": "[FINANCIAL_CREDITOR_1]", "src": [ ... ]}
  ],

  "typed_facts": {                             // §6.2 fields; each value points to a chronology event or a src span
    "date_of_default":       {"value": "2016-03-31", "ref": "E1", "verified": true},
    "appeal_filing_date":    {"value": null},  // null when not on record — never inferred
    "amount_in_default_inr": {"value": 482000000, "src": [ ... ], "verified": true},
    "acknowledgments": [{"date": "2018-09-30", "kind": "BALANCE_SHEET", "src": [ ... ]}],
    "first_interim_report_date": {"values": ["2018-11-30", "2018-11-01"], "conflict": true,   // record disagrees
                                  "src": [ ... ]}   // Stage A accepts either value, with a CONFLICT note
  },
  "record_conflicts": [{"field": "first_interim_report_date", "note": "para 2.1 vs para 9"}],

  "record_documents": [{"id": "D1", "kind": "BALANCE_SHEET", "date": "2018-09-30", "gist": "…"}],
  "issues": [{"id": "I1", "text": "Whether the Section 7 application was within limitation.",
              "provisions": ["LIMITATION_ACT_1963_ART_137", "LIMITATION_ACT_1963_SEC_18"]}],
  "appellant_grounds":      [{"id": "G1", "issue": "I1", "heading": "…", "src": [ ... ]}],   // one line each;
  "respondent_contentions": [{"id": "R1", "issue": "I1", "heading": "…", "src": [ ... ]}],   // full text is sealed
  "statutes_in_play": ["IBC_2016_SEC_7", "IBC_2016_SEC_61"],      // canonical IDs, from the parties' submissions only
  "appeal_scope": {"restricted_grounds": null} // e.g. "SEC61_3" for appeals against plan approval
}
```

#### 6.6.3 `ground_truth.jsonl` — sealed
```jsonc
{
  "case_uid": "PC-0001",
  "decision_date": "2024-01-19",
  "label": "DISMISSED",      // ALLOWED | DISMISSED | PARTLY_ALLOWED | ALLOWED_REMANDED | WITHDRAWN | DISPOSED
  "appellant_won": false,    // binary for the headline metric; mapping of remands fixed in writing before any run
  "issue_findings": [{"issue": "I1", "finding": "WITHIN_LIMITATION", "holding": "…",
                      "provisions": [ ... ], "authorities_relied": [ ... ], "src": [ ... ]}],
  "ratio_decidendi": "…",
  "operative_order_verbatim": "…",
  "directions": ["…"],
  "dissent": null,
  "submissions_full": {"appellant": "…", "respondent": "…"},    // bench's summaries; for argument-coverage metric
  "authorities_cited_by_parties": [                              // for retrieval-recall metric (did agents find them?)
    {"title": "…", "by": "APPELLANT", "authority_uid": "…"}],
  "bench_framing": {"issue_grouping": "…", "interpretive_aids": ["notes on clauses …"]},
  "subsequent_history": [{"court": "SC", "date": "2024-05-02", "result": "SLP_DISMISSED"}]
}
```
The label is always the **NCLAT** order. A later Supreme Court reversal goes in `subsequent_history` and
is reported separately; it never replaces the label.

#### 6.6.4 `manifest.jsonl` — provenance, split, QA (never sent to an LLM at runtime)
```jsonc
{
  "case_uid": "PC-0001",
  "real": {"title": "…", "appeal_numbers": ["CA(AT)(Ins) 1528/2023"], "bench_members": ["…"]},
  "sources": [{"doc": "JUDGMENT", "url": "…", "sha256": "…", "pages": 24},
              {"doc": "IMPUGNED", "url": "…", "sha256": "…"}],
  "overlap_with_reference_db": {"reference_case_uids": ["REF-3f9a2c1d"], "raw_precedent_ids": ["2024_NCLAT_DEL_1528"]},
  "split": "test",
  "strata": {"proceeding_type": "SEC7_ADMISSION", "appellant_role": "SUSPENDED_DIRECTOR_PROMOTER", "year": 2024},
  "build": {"method": "LLM_DRAFT+HUMAN_REVIEW", "drafted_by": "<model-id>", "reviewed_by": "annotator_02",
            "reviewed_at": "YYYY-MM-DD"},
  "qa": {"facts_verified": true, "issues_neutral": true, "issues_original": ["Whether NCLT erred…"],
         "leakage_scan_passed": true, "anonymisation_checked": true},
  "contamination_probe": {"<model-id>": {"outcome_correct": false, "ratio_recalled": false}}
}
```

#### 6.6.5 Selection of the ~500
- Temporal split (§9.1): train 250 (≤ 2023) · dev 100 (2024) · test 150 (2025–26, after every model's cutoff).
- Target mix within IBC appeals (same in each split): s.7 admission 30 % · s.9 admission 20 % · resolution
  plan / CoC / s.30–31 15 % · claims / s.60(5) 12 % · liquidation 8 % · s.12A / s.29A / PG / other 15 %.
- Dev and test keep the **natural outcome ratio** (no rebalancing — it would distort baselines); train may
  be enriched with ALLOWED appeals.
- Eligible only if both PDFs are available **and** the judgment records the parties' submissions
  separately from the bench's analysis (otherwise grounds/contentions cannot be filled without leakage).
- Connected appeals decided by one judgment = one case; never split across train/dev/test.

#### 6.6.6 Build pipeline per case
1. Fetch PDFs; record URL + sha256.
2. LLM drafts unspoiled / ground truth / manifest from the PDFs, with `src` on every value.
3. Human verifies every typed fact and the issue wording; a lawyer checks a ≥ 50-case sample.
4. Automatic checks: every `src` resolves to a real page; no ratio/operative-order n-grams in unspoiled;
   no real names in unspoiled; schema validation.
5. Link overlap with the reference DB (`overlap_with_reference_db`; set `public_case_uid` on the reference record).
6. Contamination probe on test cases (§4.2).

#### 6.6.7 Segmentation map: judgment component → where it goes
Indian Kanoon judgments come with component labels (Facts, Issues, Petitioner's Arguments, Analysis of
the law, Precedent Analysis, Court's Reasoning, Conclusion). Treat them as a **hint, not ground truth**:
segment **per paragraph** ourselves, because facts also appear inside "reasoning" paragraphs, the
respondent's submissions may not have their own label, and a single paragraph can mix record facts with
the bench's view. Worked example: `docs/examples/public_case_example.md`.

| Component | Goes to | Transform | Why |
|---|---|---|---|
| Header: appeal nos., parties, counsel, coram | `manifest.real` | Unspoiled keeps only forum, bench city, impugned order's forum/bench/date. Counsel and coram names dropped entirely | Names identify the case; senior-counsel and judge identity bias |
| Facts (and fact sentences inside reasoning paras) | `unspoiled.chronology`, `typed_facts`, `record_documents` | Anonymise; one event per line with `src`; strip evaluative words ("rightly", "erroneously"); conflicting dates kept as `conflict` | Facts are pre-decision, but the bench chose and phrased them after deciding |
| What the impugned NCLT order held | `unspoiled.impugned_order` | Neutral summary of the order below | It's the order under appeal, part of the record |
| Issues framed by the bench | `unspoiled.issues` | Neutrality check (§6.2); original wording kept in `manifest.qa` | Framed after hearing; may echo one side's phrasing |
| Appellant's / respondent's arguments | `unspoiled` gets **one-line headings** per ground; full summaries → `ground_truth.submissions_full` | Headings only, same length and format for both sides | Full summaries are written by the winning side's judge: the losing side's may be strawmanned, and giving them turns the debate into a replay |
| Analysis of the law: statute text quoted | Not copied. `statutes_in_play` lists provisions from the **parties' submissions**; text comes from the law DB `as_of` | Provision IDs only | Which provisions the bench chose to quote, and interpretive aids it used (e.g. notes on clauses), are reasoning |
| Precedent analysis | `ground_truth.authorities_cited_by_parties` + `issue_findings` | Sealed | The authority list is strongly outcome-correlated; sealing it lets us measure whether agents find the right authorities |
| Court's reasoning | `ground_truth.issue_findings`, `ratio_decidendi` | Sealed | Outcome |
| Conclusion / operative order | `ground_truth.label`, `operative_order_verbatim`, `directions` | Sealed | Outcome |
| Source URL, page footer | `manifest.sources` | — | Provenance |

Bias rules that apply to everyone who reads the unspoiled file (advocates **and** judges):
- Both sides and all judges get the **same** unspoiled package. Judges additionally get the transcript and
  the THEMIS-GLOBAL report, never anything from `ground_truth`.
- Anonymisation removes parties, counsel, coram, and case/application numbers. Well-known matters (e.g.
  a group-wide fraud investigation widely reported) stay identifiable from the facts; the contamination probe
  (§4.2) flags them, and flagged cases are excluded from the test split.
- Leakage scan before a case is accepted: no n-gram overlap between unspoiled text and
  `ratio_decidendi` / `issue_findings`; no outcome words ("dismissed", "upheld", "no error") outside
  `impugned_order` and the procedural history of earlier proceedings.

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
  schemas/           pydantic models: Case, TypedFacts, Authority, Provision, Turn, Verdict, Lesson;
                     public_case.py (PublicUnspoiled, PublicGroundTruth, PublicManifest — §6.6)
  ingest/            load_raw.py, normalise.py, dedup.py, statute_alias.py, extract_typed_facts.py,
                     classify_proceeding.py, neutralise_issues.py, anonymise.py, split.py, build_all.py
  law/               provisions.py (as_of lookup), authorities.py (status_as_of)
  rules/             limitation.py, threshold.py, sec10a.py, sec9_notice.py, appeal.py, smt.py, dates.py,
                     constants.py, result.py — built
  retrieval/         index.py (BM25 + dense), search.py (filters: leave-one-out, temporal cutoff), rerank.py
  agents/            prompts.py (built); judge.py, case_builder.py, reflector.py (planned)
  tools/             registry.py (role → allowed tools), record.py (built); retrieval.py, law.py, rules.py,
                     memory.py, pdf.py (planned) — leakage filters enforced here
  session/           ledger.py (window state), jobs.py (SQLite queue), runner.py (window-aware runner) — built
  public_db.py       runtime reader for unspoiled.jsonl only — built
  cli.py             smoke / enqueue / run [--wait] / status — built
  themis/            local.py (claim extraction + checks), global_.py, error_codes.py
  bench/             personas.py, aggregator.py, order_writer.py
  memory/            reflect.py, store.py, select.py
  eval/              metrics.py, baselines.py, contamination_probe.py, human_study/
  orchestrator/      handlers.py (smoke, baseline, debate — built; bench/THEMIS steps planned)
  llm/               agent.py (Backend interface), claude_code.py (subscription backend), cache.py — built
data/
  canonical/         cases.jsonl, ground_truth.jsonl, authorities.jsonl, laws.jsonl, splits/
  reports/           data_audit.md, extraction_qa.csv
runs/                <run_id>/ transcripts, audits, verdicts, metrics.json, config snapshot
tests/               unit tests per rule with real-case fixtures; ingest tests; leakage tests
```
Leave the raw folders where they are; reference them via config.

### 7.3 Engineering rules
- Python ≥ 3.12, `pydantic` v2 for every schema and every LLM structured output, `pytest`, `ruff`.
- All model calls go through the `Backend` interface (`lexarena/llm/agent.py`) wrapped by `CachedBackend`
  (`llm/cache.py`): model from config per role, result cached by `(role, model, system, prompt, tools,
  schema, salt)`, usage logged per call to the ledger. Runtime code never imports the SDK directly.
- Usage: log tokens per case and per agent (the CLI's `cost_usd` is the API-equivalent figure; on a
  subscription nothing is billed, but it is the best proxy for how fast a window drains).
- Judges use a **different Claude model** from the advocates (e.g. advocates Sonnet, judges Opus). A
  different *family* is impossible on a Claude-only subscription; report this as a limitation and rely on
  the side-swap test (§8.5) to measure self-preference.
- Storage: start with JSONL + a local Qdrant (embedded mode) — it's enough for ~3k cases. Add MongoDB only
  when concurrent runs or the human-review UI need it; keep a repository interface so the swap is local.
- Every run writes a frozen config snapshot and git SHA into `runs/<run_id>/`.
- Windows: no hard-coded `/tmp`; use `pathlib` and the configured data dir.

### 7.4 Running on the Claude subscription (5-hour windows) — implemented
All model calls run on the project owner's **Claude Pro/Max subscription**, not a paid API key.
- **How:** `lexarena/llm/claude_code.py` uses the Claude Agent SDK, which drives the local Claude Code
  binary logged in with the subscription account. A Pro subscription is not an API key; if
  `ANTHROPIC_API_KEY` is set, Claude Code bills the API instead, so the backend **refuses to start** while it
  is set (override: `LEX_ALLOW_API_KEY=true`).
- **Terms:** Anthropic's Agent SDK docs say third-party developers may not offer claude.ai login or
  subscription rate limits in their products. This setup is the owner's own research runs on their
  own machine and account. Do not share one subscription login across team members or ship this
  backend to others; if the project needs that, switch the backend to an API key.
- **Limits:** usage counts against the account's **5-hour window** and **weekly caps** (`seven_day`,
  `seven_day_opus`, `seven_day_sonnet`), shared with claude.ai chat. The CLI emits a rate-limit event per
  window (status, resets_at; utilization appears once a warning fires); `session/ledger.py` persists them.
- **Pacing (`session/runner.py`):** jobs come from a durable SQLite queue (`data/state/jobs.sqlite3`).
  Before each job the runner checks the ledger: a rejected window → stop; utilization ≥
  `stop_at_utilization` (0.85) or an un-numbered warning → stop between jobs. A limit hit mid-job
  **releases** the job (no attempt counted) with its checkpoint intact.
- **Checkpointing:** every model call is a named step (`ctx.step`); completed steps are stored in the job's
  checkpoint and returned on resume, so a debate interrupted at turn 3 resumes at turn 3 in the next
  window. The result cache means a repeated call is free.
- **Commands:**
  ```
  python -m lexarena.cli smoke                         # 1 tiny Haiku call: auth, tools, isolation, window
  python -m lexarena.cli enqueue debate --split train --run-id train1
  python -m lexarena.cli run                           # one window: stop when ~85 % full or queue empty
  python -m lexarena.cli run --wait                    # sleep through resets until the queue is empty
  python -m lexarena.cli status                        # queue counts, window state, failures
  ```
- **Isolation (verified by the live smoke test, 2026-10-04):** agents get no built-in tools, no
  settings/CLAUDE.md/skills, only our in-process MCP tools, `permission_mode="dontAsk"`, and an empty
  `data/sandbox/` working directory. The smoke agent called its tool and could not read files.
- **Measured (2026-10-04, synthetic template case, 5-turn MVP debate with THEMIS-LOCAL):** 21 uncached
  calls (advocate 8 incl. 3 revisions, extractor 8, Stage B 5), ~$2.3 API-equivalent; Haiku extraction was
  the largest consumer (~170k output tokens) before extended thinking was turned off for the extractor and
  Stage B. Two debates plus smoke tests did not trigger a five-hour-window warning on this account. Re-measure
  on real dev cases (S2), including the bench, before sizing batches; plan per week, not per day.
- **Lessons from the first live runs (all fixed, with regression tests):** Haiku sometimes wraps structured
  output as `{"parameter": "<json>"}` — the backend unwraps it and agent output models are strict
  (`extra="forbid"`, answer fields required) so a malformed reply fails instead of validating as empty;
  strict schemas make the CLI retry, so Haiku roles need `max_turns` ≥ 4; extracted dates may carry a time
  suffix; a failed extraction or Stage B call is noted on the turn instead of failing the job; Stage A
  compares amounts by value, checks a day count only if the number appears in the claim text, fills missing
  computation inputs from the record's typed facts; authority matching handles bracketed abbreviations and
  acronyms; Stage B sees all stored propositions of a cited case.
- Model choice per role is in `config.py` (`haiku` for smoke/extraction, `sonnet` for advocates/baseline/
  reflection, `opus` for judges). Opus drains windows fastest; switch judges to `sonnet` if the weekly
  Opus cap binds.

---

## 8. Target architecture (revised)

### 8.0 Agents vs. code — what is an agent and what is not
The original design was a chain of single LLM calls. The build uses **tool-using agents** where an LLM
must decide *what to look up* (advocates, judges, case builder, reflection), and keeps **deterministic
code** wherever the answer must be reproducible or must not be decided by a model (orchestration,
verification, rules, aggregation, metrics).

An *agent* here = an LLM in a bounded tool-calling loop: role prompt + a role-scoped tool set + a
budget (max tool calls, max tokens) + a typed final output submitted through a `submit_*` tool.

| Component | Kind | Why |
|---|---|---|
| Orchestrator (turn order, record closure, retries, budgets, sealing) | **Code** (state machine) | Must be deterministic and testable; not an LLM (replaces "Clerk State Machine – gpt-4o-mini") |
| Clerk (assemble case file from `unspoiled.jsonl`) | **Code** | Pure data assembly |
| Case Builder (PDF → public case draft, §6.6.6) | **Agent** (offline) | Must search the PDFs and loop until the validator passes |
| Appellant / Respondent advocates | **Agents** | Decide what to retrieve, which provision/version, what to compute |
| THEMIS-LOCAL | **Sequential pipeline**: Haiku extraction → Stage A code + Z3 (≤ 3 attempts) → Stage B LLM checks once on the final version | A verifier must be reproducible; Stage B runs once, on text that will not change again |
| Rule engine + Z3 | **Code** | Arithmetic and statute logic (§5, §8.3.4) |
| Judges (3 personas) | **Agents** (read-only tools) | Check record, bare text, authority status themselves |
| Aggregator | **Code** | Majority label, issue merge, dissent |
| Order writer | Single LLM call | Renders the aggregated findings as a reasoned order; adds no new findings |
| THEMIS-GLOBAL | Pipeline (LLM calls + code), **runs before the bench** | Whole-transcript findings feed the judges; never a verdict (§8.3a) |
| Evaluator, baselines | **Code** (+ single-LLM baseline call) | Metrics |
| Reflection (train split only) | **Agent** + code validator | Must read transcript + ground truth + law to ground a lesson; validator decides admission |

Agent rules (all enforced in code, not in prompts):
- **Tool scoping is the security boundary.** An agent can only reach data through the tools registered for
  its role. No runtime agent has a tool that touches `ground_truth.jsonl` or `manifest.jsonl`; only the
  reflection agent (train split) and evaluator do.
- **Leakage filters live inside the tools.** `search_authorities` applies overlap exclusion, temporal cutoff
  and status-as-of on the server side (§4, §8.2); `get_provision` always answers `as_of = law_as_of`. The
  agent cannot pass a later date or disable a filter.
- **Budgets**: max tool calls and tokens per turn/judgment, from `config/thresholds.yaml`; exceeding them
  forces `submit_*`.
- **Full traces**: every tool call and result is logged in `runs/<run_id>/traces/`. The trace is what makes
  an agent run auditable and replayable (cache hits on the same `(model, messages, tools)` hash).
- **No agent-to-agent free chat.** Advocates see only published turns; judges deliberate independently and
  do not see each other's drafts.

### 8.1 Case lifecycle
```
OFFLINE
  PDFs → Case Builder agent → validator → human review → public_db/ (unspoiled | ground_truth sealed | manifest)
  India Code / Gazette → laws.jsonl (versions, as_of) · SC + NCLAT → authorities.jsonl (status_as_of)
  reference precedents → proposition index (BM25 + dense, Qdrant embedded)

PER CASE (orchestrator = code)
  Clerk (code): case file from unspoiled.jsonl; law_as_of fixed
  for each turn in §8.4:
      advocate agent (tools: §8.1a) → structured turn {prose, claims[]}
      THEMIS-LOCAL (§8.3): extract (Haiku) → Stage A code+Z3 (≤ 3 attempts) → Stage B LLM once (flags only)
      append turn + THEMIS report to the hearing transcript (hash-chained, shared page)
  bench question turn: judge agents propose questions → orchestrator merges → advocates answer
  seal transcript (final hash)
  THEMIS-GLOBAL (§8.3a) on the whole transcript → findings report (no verdicts)
  3 judge agents in parallel (tools: §8.1a; inputs: sealed transcript + GLOBAL report) → findings + label each
  aggregator (code) → order writer (1 call) → reasoned order
  evaluator (code): unseal ground truth → metrics (reuses the GLOBAL report)
  if split == train: reflection agent per side → validator (code) → memory store
```

#### 8.1a Tool sets by role
| Tool | Advocates | Judges | Reflection (train) | Case Builder |
|---|---|---|---|---|
| `read_record(section)` — unspoiled case file | ✓ | ✓ | ✓ | |
| `read_transcript(turns)` — published turns + THEMIS flags | ✓ | ✓ | ✓ | |
| `search_authorities(query, provisions)` — filtered retrieval | ✓ | ✓ | ✓ | |
| `get_authority(uid)` / `authority_status(uid)` — at cutoff | ✓ | ✓ | ✓ | |
| `get_provision(id)` — bare text + checklist at `law_as_of` | ✓ | ✓ | ✓ | |
| `rules.*` — `limitation`, `threshold`, `sec10a`, `sec9_notice`, `appeal_timeline` | ✓ | ✓ | ✓ | |
| `recall_lessons(query)` — own side's frozen memory | ✓ (own side) | | | |
| `notes_write/read` — private per-case scratchpad | ✓ (own side) | | | |
| `read_ground_truth()` | | | ✓ | |
| `propose_lesson(...)` | | | ✓ | |
| `pdf_search / pdf_read_page` | | | | ✓ |
| `validate_draft()` — §6.6.6 checks | | | | ✓ |
| `submit_turn` / `submit_judgment` / `submit_draft` | ✓ | ✓ | | ✓ |

Advocates *may* call `rules.*` to get their arithmetic right; THEMIS still recomputes independently.

#### 8.1b Models (config, not code)
- Claude only, via the subscription (§7.4). Advocates: Sonnet. Judges: Opus (a different Claude model,
  §7.3). THEMIS extraction/NLI, order writer, classification: Haiku. Case Builder: Sonnet or Opus (it
  writes ground truth that humans then verify — never the cheapest model).
- Every model used on the test split must have a training cutoff before the test cases (§4.2). With
  Claude-only models this is the binding constraint: look up each model's training cutoff in Anthropic's
  model documentation, record it in the run snapshot, and expect the eligible test pool to be only the
  appeals decided after the newest model's cutoff — possibly far fewer than 150. Re-check §6.6.5 sizes once
  the cutoffs are known.
- The agent loop is the Claude Agent SDK's (it is Claude Code's loop). Tool calls and results are captured
  from the message stream into `AgentResult.trace`; every call is cached and logged (§7.3).

### 8.2 Retrieval
- Index units: authority **propositions** (ratio split per issue) + issues + facts, not facts alone.
- Hybrid: BM25 (legal terms, section numbers matter) + dense (bge-m3 or bge-base; pick one, record it)
  + statute-ID filter + cross-encoder reranker.
- Hard filters: `uid ∉ dedup_cluster(case)`, `date < cutoff(case)`, `status_as_of(cutoff) == GOOD_LAW`
  (or include with an explicit "reversed on …" tag, never silently).
- Threshold: calibrated on a labelled set of (case, relevant authority) pairs drawn from the train split
  — e.g. authorities a ratio actually relies on. Choose τ to hit a target precision; report recall.
- Always include the controlling SC authority for the provision if one exists (rule-based, not similarity).

### 8.3 THEMIS-LOCAL (per turn) — two-stage gate
Stage A (deterministic) loops up to 3 attempts; then Stage B (semantic LLM checks) runs **once, on the
final version, whether or not Stage A passed**. Stage B never sends the turn back to Stage A; its findings
are published as flags. Control flow is implemented and tested in `lexarena/themis/local.py`.

```
draft turn
  └─ attempt 1..3:  Haiku extracts claims → ClaimSet JSON  →  STAGE A: code + rules + Z3
                     pass → go to Stage B
                     fail, attempt < 3 → error codes + evidence → same advocate revises → Haiku re-extracts
                     fail on attempt 3 → keep the hard flags, go to Stage B
  └─ STAGE B: LLM semantic checks, once, on the final version → flags (no revision, no return to A)
  └─ publish: PASSED | FLAGGED_HARD | FLAGGED_SOFT | FLAGGED_BOTH
```

**Why sequential, not parallel.** The two stages check different things, but they check the same text, and
a Stage A failure changes that text (the advocate revises). Run in parallel, Stage B would either check a
version that is about to be replaced (stale flags) or have to re-run on every revision (up to 3× the LLM
calls). On a subscription the scarce resource is usage, not wall-clock time; the latency saved by
parallelism is one Haiku call per turn. Running B once on the final version is the cheapest correct option.

1. **Claim extraction (Haiku, structured):** produces a `ClaimSet` JSON: dates, amounts, day-counts,
   provision references, authority citations with the proposition attributed to each, factual assertions
   about the record. The advocate's declared `claims[]` are merged in; anything the extractor finds that
   the advocate did not declare is checked the same way. Re-run on every revision. Haiku does not fix
   errors; the advocate revises its own turn. The revision prompt shows the extracted claim and the
   evidence, so if Haiku mis-extracted, the advocate can restate the point clearly and the re-extraction
   picks it up.
2. **Stage A, deterministic (code + rule engine + Z3), pass/fail with error codes. Up to 3 attempts.**
   - Asserted date/amount ≠ record typed fact → `ERR_FACT_MISMATCH` (lookup).
   - Arithmetic wrong (day counts, limitation expiry, s.61(2) 30+15, s.9 ten days) → `ERR_ARITHMETIC` (`rules/`).
   - The claims contradict each other or the record's dates (e.g. acknowledgment after expiry presented as
     saving limitation) → `ERR_INCONSISTENT_CLAIMS` (Z3 over the ClaimSet + typed facts).
   - Provision doesn't exist / not in force on the date → `ERR_PROVISION_NOT_IN_FORCE` (law DB lookup).
   - Authority not in table → `ERR_UNVERIFIED_AUTHORITY`; decided after cutoff → `ERR_ANACHRONISTIC_AUTHORITY`;
     reversed as of cutoff and presented as good law → `ERR_BAD_LAW` (authority-table lookup).
   - Z3 is the right tool for the consistency and uncertain-fact checks: when a typed fact is null or ranged
     ("acknowledgment sometime in FY 2018-19"), encode it as a bounded variable and report
     `ALWAYS / POSSIBLY / NEVER` within limitation. `POSSIBLY` is **not** a failure; it is recorded as an
     annotation for the bench. Plain lookups and known-date arithmetic stay plain Python.
3. **Stage B, semantic LLM checks (Haiku), once, after the Stage A loop ends. Flags only, no revision.**
   What code cannot decide:
   - Attributed proposition contradicts the stored proposition for that authority (NLI) → `ERR_MISATTRIBUTED_RATIO`.
   - Factual assertion not supported by the cited record section (entailment against the record text) →
     `ERR_UNSUPPORTED_BY_RECORD`.
   - New facts introduced after the record closed (turn > 3, not asked for by the bench) → `ERR_NEW_FACT`.
4. **What it never does:** reject a turn because its *legal position* would lose. An agent may argue
   limitation is saved; the gate checks only that the dates and acknowledgments it relies on are real and
   the arithmetic is right.
5. **Revisions** go to **the same advocate agent** with error codes + evidence (no separate "lawyer agent";
   authorship stays with the side). Flags are published on the transcript, visible to the opponent,
   THEMIS-GLOBAL and the bench. The penalty is a count of failures by stage, reported separately from the
   bench outcome.
6. **Cost per turn on the subscription:** best case 2 Haiku calls (extract + Stage B); worst case 3 extractions
   + 2 advocate revisions + 1 Stage B call. Log attempts per turn; if the average is high, fix prompts
   before scaling.

### 8.3a THEMIS-GLOBAL — after the debate, **before** the bench
Runs once on the full hearing transcript (the shared page where all published turns and their flags live)
before the judges see it. Its report goes to the bench as an input.
- **Checks (whole-transcript, which per-turn checks cannot see):** cross-turn self-contradiction by the same
  side; claims that drifted between turns (a date or amount stated differently later); rebuttal
  responsiveness (which points of the other side went unanswered, by issue); citations repeated after being
  flagged; a re-run of Stage A on every claim in the final transcript.
- **Implementation:** code for the deterministic parts (re-running Stage A, claim drift, flag repetition) plus
  Haiku/Sonnet calls for contradiction and responsiveness. A pipeline, not an agent.
- **Output to the bench: findings, never verdicts.** Per issue: claims verified / flagged with error codes,
  unanswered points, contradictions, each with the turn and quoted span. It must **not** say which side is
  stronger, score the sides, or recommend an outcome; otherwise the auditor decides the case and the bench
  just ratifies it (same reason the gate never judges merit, §8.3.4). A side-symmetric format (same headings
  for both sides) limits anchoring.
- **Also used after the trial** for the hallucination, fact-fidelity and adversarial-quality metrics (§9.2);
  the same report, computed once.
- **Ablation:** bench with vs without the GLOBAL report (§9.2) — measures how much the judges lean on it.

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
- Each judge is an agent with read-only tools (§8.1a). Inputs: the sealed transcript with its per-turn flags
  **and the THEMIS-GLOBAL report (§8.3a)**. Output, per framed issue: finding, reasons, authorities relied
  (must pass THEMIS checks), and a final label. A judge may disagree with a GLOBAL finding but must say why.
  Judges run independently. Aggregator (code): majority on label; issue-wise reasoning merged; dissent recorded.
- No weighted "scoring matrix" (accuracy 0.35 / consistency 0.25 …): the bench decides issues and a label;
  advocacy-quality measures come from THEMIS-GLOBAL and are reported separately.
- Bias controls: side-swap test (swap appellant/respondent labels in the transcript and the GLOBAL report),
  length-normalised scoring check, different Claude model from advocates, with/without-GLOBAL ablation.

### 8.6 Reflection memory
- Built **only on the train split**; frozen before dev/test runs.
- One reflection agent per side after each train case: reads transcript, ground truth, law and authorities;
  proposes lessons via `propose_lesson`. A code validator (scope present, `grounded_in` resolves, law check,
  NLI merge check) decides what enters memory — the agent never writes to the store directly.
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
Splits apply to the **public case DB only** (§6.6.5); the reference DBs have no split.
- `train` (~250): decided ≤ 2023-12-31 · `dev` (~100): 2024 · `test` (~150): 2025–2026 (confirm all test
  cases are after the newest model cutoff; drop or flag any that aren't).
- Power: with ~150 test cases a bootstrap CI on balanced accuracy is roughly ±8 points. Prefer few, paired
  comparisons on the same cases (McNemar) over many ablations on test.
- Stratify reporting by `proceeding_type` and `appellant_role`.
- Dedup clusters never span splits.

### 9.2 Metrics
- **Outcome**: accuracy, **balanced accuracy, macro-F1**, always beside three baselines: **majority
  class** (≈65 % DISMISSED in the reference DB — re-measure on the public test split), **metadata-only**
  (majority per `proceeding_type` × `appellant_role`, or a small classifier on proceeding type, role, bench,
  year), and **single-LLM** (one model reads the unspoiled case, predicts). Run the single-LLM baseline
  right after the public DB exists — before building THEMIS — since the research claim depends on beating it.
- **Issue-level alignment**: per framed issue, does the simulated finding match the real ratio? LLM-graded
  with a rubric, with ≥100 issues double-checked by a lawyer; report agreement (Cohen's κ).
- **Hallucination**: unverified/anachronistic/bad-law citations per 1,000 tokens, before and after THEMIS.
- **Fact fidelity**: `ERR_FACT_MISMATCH` + `ERR_ARITHMETIC` rate per turn.
- **Adversarial quality**: rebuttal responsiveness (does turn t+1 address the claims of turn t), cross-turn
  self-contradiction rate.
- **Memory effect**: dev metrics with memory frozen at 0, 100, 300, all train cases (learning curve).
- **Ablations**: no THEMIS · bench without the THEMIS-GLOBAL report · no retrieval · no memory · single judge vs bench · same vs different model
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

Phase 0a (A–E, J, L) builds the **reference DBs**; Phase 0b (PB1–PB6) builds the **public case DB**.
F–I and K apply to the public DB first (that is what is simulated); run them on the reference DB only
where retrieval needs the field.

#### Phase 0a — Reference DBs
- [x] **A. Raw loader** (`ingest/load_raw.py`, §7.1). 3,000 parsed; the second pass (jump to the next
      `{"precedent_id"`) recovers none of the 5 lost records, which sit inside broken segments; the 14 parse
      errors are logged in `data/reports/reference_build.md` for manual re-sourcing.
- [x] **B. Clean & normalise** (`ingest/normalise.py`): `[cite]` stripped everywhere; label from
      `final_order`, refined from `operative_order` (ALLOWED_REMANDED 232, PARTLY_ALLOWED 117); bench city;
      issues split into a list; ratio split into numbered propositions. Bench members not yet parsed.
- [x] **C. Dedup + `case_uid`** (`ingest/build_reference.py`): union-find over (title key, date) and
      (appeal number qualified by bench + appeal type, date). **2,696 unique cases** (audit key alone: 2,736;
      40 more connected-appeal duplicates merged), zero `case_uid` collisions, 1 label conflict.
      Output: `data/canonical/reference_cases.jsonl` (`python -m lexarena.ingest.build_reference`).
- [x] **D. Statute alias map** (`ingest/statute_alias.py`): canonical `ACT_YEAR_UNIT_N[_SUB]` (e.g.
      `IBC_2016_SEC_61_2`, `COMPANIES_ACT_2013_SEC_241`, `LIMITATION_ACT_1963_ART_137`); both raw schemes
      mapped; `from_text()` parses plain language ("Section 61(2) of the IBC"). Resolution against law DB
      unchanged until step E.
- [ ] **E. Law DB v2**: add missing provisions (§3.3), verbatim bare text, version history for amended
      sections (at minimum s.4, 5(8), 7, 10A, 12, 12A, 29A, 30, 32A, 61, 238A, 240A), fix s.4 threshold
      logic, dedupe PMLA s.8, strip `[cite]`. Source: India Code / Gazette; record `source_url`.
- (J and L are listed under shared steps below.)

#### Phase 0b — Public case DB (§6.6)
- [x] **PB1. Pydantic schemas** `lexarena/schemas/public_case.py` + `scripts/validate_public_db.py`
      (schema, `src` page resolution, leakage 8-gram scan, anonymisation scan, issue coverage, split/date
      rules, duplicate appeals) + JSON Schema export + synthetic example + 19 tests.
- [ ] **PB2. Candidate pool + sampling plan**: list eligible IBC appeals per year/stratum (§6.6.5); confirm
      PDFs (judgment + impugned order) are obtainable. *Accept*: ≥ 1.5× candidates per stratum.
- [ ] **PB3. Pilot 20 cases** end to end (draft → human review → validator); fix schema before scaling.
- [ ] **PB4. Build remaining ~480** in batches; lawyer check on ≥ 50 stratified. *Accept*: ≥ 95 % precision
      on verified typed facts; zero validator failures.
- [ ] **PB5. Overlap linking** to the reference DB; retrieval exclusion test passes for every public case.
- [ ] **PB6. Freeze splits** + contamination probe + single-LLM and metadata baselines on dev.

#### Shared steps
- [ ] **F. Proceeding-type + appellant-role classification** (LLM + rules from statutes_cited; human
      check 100). *Accept*: ≥ 90 % agreement on the checked sample.
- [ ] **G. Typed-fact extraction** (§6.2) with evidence spans. Human-verify 50 cases stratified by
      proceeding type. *Accept*: ≥ 95 % precision on non-null dates; null when absent.
- [ ] **H. Issue neutrality pass** (§6.2).
- [ ] **I. Anonymisation** of unspoiled text (keep original in a non-runtime field).
- [~] **J. Authority table v1** (§6.4). Stand-in built: `law/authorities.py` over the reference DB (exact
      dates) + `data/seed/sc_landmarks.json` (27 SC landmarks from §5, **year only, unverified**), court-aware
      matching (same parties at NCLAT and SC). Remaining: exact SC dates, treatment table (REVERSED/OVERRULED
      with dates, e.g. Essar NCLAT 2019 → SC 15.11.2019), human verification of every SC entry.
- [ ] **K. Splits** (§9.1, public DB only) + **contamination probe** baseline per candidate model (= PB6).
- [ ] **L. Data audit report** regenerated by `ingest/build_all.py` (one command, reproducible).

### Phase 1 — Rule engine (deterministic, test-first)
- [x] **M. `rules/`**: s.4 threshold by filing date (+ s.7 class-creditor proviso); Art.137 limitation with
      s.12/s.25 calendar arithmetic, s.18 chained acknowledgments (before-expiry check), s.19, COVID exclusion
      + 90-day floor, s.14 exclusion periods, s.4 closed days; s.10A bar; s.8/s.9 notice timing; s.61(2) 30+15
      from pronouncement with s.12(2) certified-copy exclusion; s.62 45+15.
- [~] **N. Tests**: edge cases done (37 tests: leap day, acknowledgment on/one day after expiry, chained
      acknowledgments, unwritten part-payment, s.14 both-days count, COVID floor vs longer balance, s.10A
      boundaries, day 10 vs 11, 46-day appeal, certified copy applied late). Remaining: ≥ 5 real-case
      fixtures per rule, once public cases exist.
- [x] **O. `rules/smt.py`**: ALWAYS/POSSIBLY/NEVER over uncertain dates, with a witness for each side;
      period-end table shared with `limitation()` so both always agree (tested).

Rule engine contract (`lexarena/rules/`): every rule returns a `RuleResult` with `status`, `value`,
`details`, `steps` (the computation in words), `for_bench` (questions it does not decide: bona fides,
sufficient cause, Mobilox plausibility, whether an entry is an acknowledgment in law), `verify` (assumptions
still to check) and `provisions`. Legal dates/amounts live only in `rules/constants.py`. **Open `VERIFY`
items in the engine:** S.O. number and boundary day of the 24.03.2020 threshold notification; s.10A
window-extension notifications; COVID floor last day (29.05 vs 30.05.2022); 29 February + years convention;
acknowledgment signed on the last day; s.12(2) day counting and whether it extends the 45-day outer limit;
10 % rounding for class creditors; pending applications on 28.12.2019 (Manish Kumar).

### Phase 2 — Retrieval
- [~] **P. Index** (`retrieval/`): 17,935 units (propositions, issues, facts); BM25 with section-aware
      tokens built in memory (~2 s); RRF fusion with dense when built; provision boost; one hit per case.
      Dense (bge-m3) code ready but **the local bge-m3 cache has no weights** (43 MB, config/tokenizer only);
      download, then `python -m lexarena.retrieval.build_index --dense`. Brute-force numpy instead of Qdrant
      (enough at this size; same interface). No cross-encoder reranker yet.
- [x] **Q. Filters**: exclusion set + temporal cutoff applied before ranking; overruled flag surfaced as a
      treatment note (status-as-of needs step J). Leakage tests pass.
- [ ] **R. Calibrate** τ on train pairs; report precision/recall (needs labelled pairs).

### Phase 3 — Agents and THEMIS-LOCAL
- [x] **S. Agent backend + session runtime** (§7.4) + research tools (`tools/research.py`):
      search_authorities, get_provision, authority_status, rules_limitation / appeal_timeline / sec9_notice /
      sec10a / threshold, each built per case with cutoff, law date and exclusions fixed inside. Tests prove
      excluded and post-cutoff authorities never come back and post-cutoff SC authorities are marked unusable.
- [~] **S2. Measure usage**: first measurement on the synthetic case recorded in §7.4; repeat on 3 real dev cases.
- [~] **T. Advocate agents**: structured turns (prose + claims), record + research tools, MVP 5-turn
      schedule. Remaining: prompts conditioned on `appellant_role` / `proceeding_type`; s.61(3) scope.
- [x] **U. THEMIS-LOCAL** (§8.3): `themis/claims.py` (ClaimSet), `themis/stage_a.py` (fact/event
      mismatch, day counts, computations redone by the rule engine, provision not in force, unverified /
      anachronistic authority; notes for record conflicts and coverage gaps), Haiku extractor and Stage B
      (`themis/checkers.py`), revision by the same advocate; wired into the debate handler per turn.
- [ ] **U2. THEMIS-GLOBAL** (§8.3a) before the bench; report format side-symmetric, findings only.
- [x] **V. Orchestrator**: plain Python job handlers + checkpointed steps (`orchestrator/handlers.py`).
- [~] **W. Smoke run**: two live end-to-end debates on the synthetic case (tools used correctly; THEMIS caught
      and fixed real errors; false positives found and fixed). Remaining: 10 real dev cases, lawyer reads every transcript.

### Phase 4 — Bench, global audit, metrics
- [ ] **X. Bench** personas (§8.5), aggregator, issue-wise order.
- [ ] **Y.** `eval/metrics.py` (reusing the THEMIS-GLOBAL report) + baselines + ablation runner.
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
| "Data quality?" | Evaluation cases are built from the original PDFs with page/para pointers on every fact, human-verified, lawyer-sampled. The reference DB audit: 264 duplicates removed, 157 ID collisions fixed, cite artefacts stripped. |
| "Isn't the precedent DB LLM-generated?" | Yes — it is only the retrieval store. Nothing is scored against it; ground truth comes from the judgments themselves. |

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
| 2026-10-04 | Existing precedent/law folders = reference DBs only; separate ~500-case public case DB for train/dev/test | Project owner's decision; also keeps scoring off LLM-written summaries |
| 2026-10-04 | Public cases built from judgment + impugned-order PDFs, three files (unspoiled / ground_truth / manifest) | Provenance, physical sealing of ground truth |
| 2026-10-04 | Public DB split 250 / 100 / 150 by decision year; natural outcome ratio in dev/test | Memorisation control; honest baselines |
| 2026-10-04 | Ground-truth label = NCLAT order; SC history recorded separately | The simulated forum is NCLAT |
| 2026-10-04 | Advocates, judges, case builder, reflection = tool-using agents; orchestrator, THEMIS checks, rules, aggregator, metrics = code | Agents where lookup decisions matter; code where reproducibility matters (§8.0) |
| 2026-10-04 | Leakage filters enforced inside tools, not prompts | Agents can't bypass filters; full traces for replay |
| 2026-10-04 | All model calls on the owner's Claude subscription via the Agent SDK (no API key, no gateway); work paced to 5-hour windows with a checkpointed job queue | Project owner's decision (budget) |
| 2026-10-04 | Judges = different Claude model, not a different family | Only Claude is available; limitation reported, side-swap test measures bias |
| 2026-10-04 | THEMIS-LOCAL: Haiku extraction → Stage A code+Z3 (≤ 3 attempts, re-extract each time) → Stage B LLM once on the final version, even if A never passed; B flags only, never loops back | Project owner's decision. Sequential over parallel: a Stage A revision changes the text, so parallel B would be stale or repeated |
| 2026-10-04 | Public case segmentation per paragraph (§6.6.7): grounds as one-line headings in unspoiled, full submissions and party-cited authorities sealed; record date conflicts stored, not resolved | Prevents replaying the real arguments and leaking the authority list; keeps record defects visible |
| 2026-10-04 | THEMIS-GLOBAL runs before the bench and its report is a judge input; findings only, no verdict or side scores; with/without ablation | Project owner's decision; guardrail so the auditor does not decide the case |

## 13. Open questions (ask the project owner before deciding)
- Pro or Max? Pro's windows are small; a full simulation of ~500 cases with a 3-judge bench may need
  weeks of windows. Measure per-case usage first (§7.4) before committing to the 11-turn / 3-judge design.
- Which Claude models' training cutoffs fall before enough 2025–26 appeals to form a test split (§8.1b)?
- Will more than one person run jobs? If yes, each needs their own account, or the backend moves to an API key (§7.4 terms).
- Are 3–5 practising lawyers available for the human study and for verifying the authority table?
- Is there access to the original judgment **and impugned NCLT order** PDFs? **Required** for the public
  case DB (§6.6); also needed to recover the 5 lost reference records.
- Who reviews the ~500 public cases (annotators) and which lawyer does the ≥ 50-case check?
- Is 500 fixed, or can test grow if enough post-cutoff 2025–26 appeals qualify?
- How are remands mapped to `appellant_won` (win, loss, or excluded from the binary metric)?
- Deadline / which phases must be done for the next evaluation milestone?

## 14. Glossary
CIRP — corporate insolvency resolution process · CD — corporate debtor · FC/OC — financial/operational
creditor · RP/IRP — (interim) resolution professional · CoC — committee of creditors · AA — Adjudicating
Authority (NCLT) · NCLAT — appellate tribunal · PG — personal guarantor · L4L — logic-for-law predicates ·
Reference DB — existing precedent + law folders, used for retrieval/lookup only · Public case DB — the
~500 PDF-built cases that are simulated and scored (§6.6) · Unspoiled — pre-decision case material visible to agents · Ground truth — the real order, sealed until
evaluation · Cutoff — date after which no authority may be used for a given simulated case.
