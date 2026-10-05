# Data formats

The Law DB and precedent formats are **frozen**: never change them. Everything else here (side collections, lessons, config) can evolve, with a version bump recorded in `docs/DECISIONS.md`. The public DB schemas (`cases`, `case_ground_truth`, `transcript_turns`, `sessions`) are in `docs/SPEC.md` section H.

Notation: `"STRING (description)"` gives the type and meaning of a field.

## 1. Law DB record (frozen)

```json
{
  "_id": "STRING (Primary Key, e.g., ACT_ABBREVIATION_SEC_NUMBER)",
  "statute_id": "STRING (Identical to _id)",
  "act_name": "STRING (Official name of the legislation)",
  "section_number": "STRING (e.g., \"7\", \"14\", \"18\")",
  "section_title": "STRING (Official legal heading of the section)",
  "jurisdiction_type": "STRING (Classification tag, e.g., INITIATING_CLAIM, PROHIBITORY_SHIELD, SAVING_PROVISION)",
  "forum_level": "STRING (Adjudicating authority, e.g., NCLT_ORIGINAL, NCLAT_APPELLATE)",
  "statutory_summary": "STRING (Concise explanation of legal effect)",
  "core_judicial_inquiry": "STRING (The core legal test the judge must evaluate)",
  "intersecting_statute_ids": ["STRING (Foreign keys to related sections in the Law DB)"],
  "diagnostic_checklist": {
    "applicant_eligibility": ["STRING (Qualifying criteria for standing, including class/quorum rules as plain text)"],
    "financial_threshold": {
      "minimum_amount": "NUMBER or NULL",
      "currency": "STRING or NULL"
    },
    "mandatory_prerequisites": ["STRING (Required notices, forms, affidavits or documentary evidence)"],
    "statutory_bars": ["STRING (Conditions or defenses that prohibit or invalidate the claim)"],
    "saving_exceptions": ["STRING (Provisos or mechanisms that cure a bar or extend a right)"]
  },
  "procedural_timelines": {
    "adjudication_window_days": "NUMBER or NULL",
    "rectification_window_days": "NUMBER or NULL"
  },
  "audit_error_codes": ["STRING (Standardized uppercase error tags used by THEMIS and memory logging)"]
}
```

How the system uses each field:

- `jurisdiction_type` selects the audit stance: asserting a claim, invoking a bar, or invoking an exception.
- `core_judicial_inquiry` is the question judges answer per issue, and the question THEMIS layer 2 checks the argument addresses.
- `audit_error_codes` names hard errors and Z3 tracked assertions.
- `intersecting_statute_ids` auto-loads related provisions together.
- `financial_threshold` and `procedural_timelines` apply only when no approved `temporal_overlay` row covers the case date.

## 2. Precedent record (frozen; stored as JSON/JSONL)

```json
{
  "precedent_id": "STRING (Unique ID, e.g., YEAR_FORUM_BENCH_NUMBER)",
  "case_title": "STRING",
  "appeal_number": "STRING (Case or appeal number as reported)",
  "forum": "STRING (NCLT | NCLAT)",
  "bench": "STRING",
  "decision_date": "DATE (YYYY-MM-DD)",
  "final_order": "STRING (e.g., ALLOWED, DISMISSED)",
  "is_overruled": "BOOLEAN (Not good law today; overruling dates live in temporal_overlay)",
  "statutes_cited": ["STRING (Statute IDs, may be sub-clause level, e.g., IBC_2016_SEC_29A_C)"],
  "material_facts": "STRING (Numbered labelled sections: 1. PARTY IDENTITIES: ... 2. COMMERCIAL TRANSACTION: ...)",
  "legal_issues": "STRING (Numbered issues)",
  "ratio_decidendi": "STRING (Numbered parts: 1. ABSTRACT LEGAL RULE 2. STATUTORY INTERPRETATION 3. EVIDENTIARY TEST APPLIED 4. DEFINITIVE CONCLUSION)",
  "operative_order": "STRING",
  "summary": "STRING"
}
```

How it goes into Qdrant (the stored record is never modified):

| Item | Rule |
| --- | --- |
| Point ID | uuid5 of `precedent_id`, so re-ingestion overwrites instead of duplicating |
| `facts` vector | Multivector with MAX_SIM: one vector per labelled section of `material_facts` except PARTY IDENTITIES; sections over the embedding model's token limit are split into windows |
| `ratio` vector | Ratio parts 1 to 3 only; part 4 is case-specific |
| Payload | The full record, plus derived fields: `statutes_normalized` (section-level Law DB IDs), `decision_date` in RFC 3339, `content_hash` |
| Indexes | `precedent_id` keyword, `statutes_normalized` keyword, `decision_date` datetime, full-text index on `material_facts` |
| Integrity | Every `statutes_cited` value must resolve to a Law DB `_id` after normalization; unresolved IDs are reported, not dropped |

## 3. temporal_overlay (side collection)

Law that changes with dates. One row per parameter per period.

```json
{
  "overlay_id": "STRING",
  "statute_id": "STRING (Law DB _id)",
  "parameter": "STRING (e.g., minimum_default_inr, section_in_force, bar_window, excluded_period, precedent_overruled)",
  "value": "NUMBER | BOOLEAN | {\"from\": DATE, \"to\": DATE} | STRING",
  "keyed_on": "STRING (Which case key_dates label decides applicability, e.g., FILING, DEFAULT, CIRP_COMMENCEMENT)",
  "effective_from": "DATE or NULL",
  "effective_to": "DATE or NULL",
  "source_ref": "STRING (Amendment Act, notification number and date, or judgment)",
  "source_text": "STRING (Exact text relied on)",
  "status": "STRING (DRAFT | APPROVED | RETIRED)",
  "approved_by": "STRING or NULL",
  "version": "NUMBER"
}
```

## 4. predicate_registry (side collection)

Machine-checkable versions of checklist items. Only items whose numbers or dates are fixed by statute or notification text get a predicate. Everything else stays with the LLM layer.

```json
{
  "predicate_id": "STRING",
  "statute_id": "STRING (Law DB _id)",
  "field": "STRING (diagnostic_checklist field or procedural_timelines key)",
  "item_index": "NUMBER or NULL (Index within the checklist list)",
  "item_hash": "STRING (sha256 of the Law DB item text; a mismatch marks the predicate STALE)",
  "kind": "STRING (THRESHOLD | DAY_COUNT | DATE_ORDER | DATE_WINDOW)",
  "inputs": [
    {
      "name": "STRING",
      "source": "STRING (record.amounts:<label> | record.key_dates:<label> | law:<json path> | overlay:<parameter> | claim:<field>)"
    }
  ],
  "open_parameters": [
    {
      "name": "STRING",
      "options": ["STRING (Readings the argument may choose)"],
      "note": "STRING"
    }
  ],
  "expression": "OBJECT (Expression tree; grammar below)",
  "error_code": "STRING (From the statute's audit_error_codes)",
  "source_text": "STRING (Exact statute or notification text this encodes)",
  "status": "STRING (DRAFT | APPROVED | STALE | RETIRED)",
  "approved_by": "STRING or NULL",
  "version": "NUMBER"
}
```

### Expression grammar

One generic engine compiles any expression to Z3. No per-section Python.

- A leaf is `{"var": "<input name>"}` or `{"const": <value>}`. A constant must be quoted in `source_text`.
- A node is `{"op": "<operator>", "args": [ ... ]}`.
- Operators:
  - logic: `and`, `or`, `not`, `implies`;
  - comparison: `==`, `!=`, `<`, `<=`, `>`, `>=`;
  - arithmetic: `+`, `-`;
  - dates: `days_between(a, b)`, `add_years(date, n)`, `add_days(date, n)`;
  - choice: `if(cond, a, b)`;
  - interpretation: `choose(<open_parameter name>, {option: expr, ...})`.
- The engine resolves `law:` and `overlay:` inputs as of the case date, `record.` inputs from the case record, and `claim:` inputs from the argument's extracted checklist.
- A predicate's result is checked as a tracked assertion named by its `error_code`, so unsat cores return error codes directly.

## 5. Lesson (experience memory)

```json
{
  "lesson_id": "STRING",
  "lesson_type": "STRING (ADVOCACY | LEGAL_RULE | PROCEDURAL_ERROR)",
  "memory": "STRING (LAWYER | JUDGE)",
  "party_status": "STRING or NULL (For lawyer memory, e.g., FINANCIAL_CREDITOR)",
  "statute_ids": ["STRING"],
  "error_code": "STRING or NULL",
  "trigger": "STRING (Situation in general terms)",
  "lesson": "STRING (Rule, tactic or error to avoid; no names or pseudonyms)",
  "provenance": {"case_id": "STRING", "issue_ids": ["STRING"], "source_paras": ["STRING"]},
  "driver": "STRING (LAW; EVIDENCE-driven mismatches never produce lessons)",
  "severity": "NUMBER (1 to 5)",
  "frequency": "NUMBER",
  "confidence": "NUMBER (0 to 1)",
  "last_retrieved_case_seq": "NUMBER",
  "status": "STRING (ACTIVE | RETIRED)",
  "created_in_run": "STRING"
}
```

## 6. Config shape (`config/config.vN.yaml`)

All tunable values live here. The values below are placeholders to be calibrated on the dev set; the code must read them, never assume them.

```yaml
version: v1
models:
  lawyer: {provider: ..., name: ..., temperature: ...}
  verifier: {provider: ..., name: ..., temperature: 0}   # different family from lawyer
  judge: {provider: ..., name: ..., temperature: ...}
  clerk_primary: {provider: ..., name: ..., temperature: 0}
  clerk_secondary: {provider: ..., name: ..., temperature: 0}
  reflection: {provider: ..., name: ..., temperature: 0}
embedding: {model: BAAI/bge-small-en-v1.5, max_tokens: ..., window_tokens: ...}
retrieval: {facts_threshold: ..., ratio_threshold: ..., top_k: ...}
session: {alternating_turns: 8, parallel_closings: true, max_turn_tokens: ...}
themis_local:
  retry_cap: ...
  extraction_min_confidence: ...
  repetition_hard_threshold: ...
  score_weights: {rule: ..., llm: ...}
  penalty_cap: ...
judging:
  weights: {accuracy: ..., consistency: ..., rebuttal: ..., grounding: ...}
  order_swap_max_gap: ...
  tie_margin: ...
memory:
  pinned_token_budget: ...
  pinned_k: ...
  decay_lambda: ...
  retire_below_confidence: ...
  dedup_embedding_threshold: ...
splits: {test_count: ..., validation_count: ...}
seed: ...
```