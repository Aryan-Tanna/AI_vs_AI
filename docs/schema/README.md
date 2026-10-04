# Public case DB: record structure

Each case is **three JSON records** sharing one `case_uid`, stored one record per line in three files:

| File | Who can read it | Contents |
|---|---|---|
| `public_db/unspoiled.jsonl` | Advocates, judges (runtime) | Everything that existed before the NCLAT decided, anonymised |
| `public_db/ground_truth.jsonl` | Evaluator; reflection agent on **train** cases only | The real decision, sealed |
| `public_db/manifest.jsonl` | Build pipeline and humans; never an LLM at runtime | Real names, sources, split, QA |

- **Source of truth:** `lexarena/schemas/public_case.py` (Pydantic).
- **JSON Schemas:** `unspoiled.schema.json`, `ground_truth.schema.json`, `manifest.schema.json`, regenerated with `python scripts/export_schemas.py`.
- **Complete example:** [example/](example/), a synthetic s.7 appeal that must never be loaded into `public_db/`.
- **What goes where when splitting a judgment:** CLAUDE.md §6.6.7, worked through in [../examples/public_case_example.md](../examples/public_case_example.md).

Validate before committing any case:
```
python scripts/validate_public_db.py                 # checks public_db/
```

## Conventions
- **Dates:** `YYYY-MM-DD`. A date known only to a financial year or a range uses `date_precision: "FY"` or `"RANGE"` plus `date_to`.
- **Every fact carries `src`:** `[{"doc": "JUDGMENT" | "IMPUGNED", "page": 3, "para": "3.4"}]`. Page numbers are checked against the PDF page count in the manifest.
- **Anonymised names are tokens** like `[FINANCIAL_CREDITOR_1]`. Every token used anywhere must be declared in `parties` (people and entities) or `placeholders` (applications, proceedings, documents whose numbers were removed).
- **IDs:** events `E1…`, documents `D1…`, issues `I1…`, appellant grounds `G1…`, respondent contentions `R1…`.
- **Absent vs null:** a typed fact left out means not extracted; `{"value": null}` means looked for and not on the record. Never infer a value.
- **Conflicting record values** are stored as `{"values": [a, b], "conflict": true, "src": [...]}` and listed in `record_conflicts`. The pipeline never picks one.

## `unspoiled` fields

| Field | Required | Notes |
|---|---|---|
| `schema_version`, `case_uid` | yes | `"1.0"`; `PC-` followed by digits/letters. Opaque: never encode the bench or appeal number |
| `title_anon` | yes | Tokens only |
| `forum`, `bench_city` | yes | `"NCLAT"`; city only, no member names |
| `law_as_of` | yes | Decision date minus 1 day. All law lookups use this date |
| `proceeding_type`, `appellant_role`, `respondent_roles` | yes | Enums (CLAUDE.md §6.3) |
| `parties` | yes, ≥ 2 | token, kind, side (APPELLANT / RESPONDENT / NON_PARTY), role, neutral description |
| `placeholders` | no | Tokens for applications and proceedings |
| `impugned_order` | yes | forum, bench_city, date, application_type, outcome_below, neutral reasoning_summary, operative_part, src |
| `chronology` | yes, ≥ 1 | One event per entry: id, date (or null), precision, event, actor token, src, optional conflict_ref |
| `typed_facts` | no | Named facts from CLAUDE.md §6.2, `acknowledgments[]`, and `other{}` for case-specific facts |
| `record_documents` | no | id, kind, date, neutral gist (≤ 400 chars), src |
| `issues` | yes, ≥ 1 | id, neutral text (validator rejects "erred", "rightly", "dismissed", etc.), provisions |
| `appellant_grounds` / `respondent_contentions` | grounds ≥ 1 | One-line headings (≤ 240 chars) tied to an issue. The full submissions go in ground truth |
| `statutes_in_play` | no | Canonical IDs taken from the parties' submissions only |
| `appeal_scope` | no | e.g. `restricted_grounds: "SEC61_3"`; `record_closed_after_turn` (default 3) |
| `record_conflicts` | no | `{field, note}` for every conflicting typed fact |

## `ground_truth` fields

| Field | Required | Notes |
|---|---|---|
| `decision_date`, `label`, `appellant_won` | yes | Label enum; `appellant_won` is null when the case is excluded from the binary metric |
| `issue_findings` | yes | Exactly one per unspoiled issue: finding code, holding, provisions, authorities relied on, src |
| `ratio_decidendi`, `operative_order_verbatim` | yes | |
| `directions`, `dissent`, `outcome_detail` | no | |
| `submissions_full` | yes | The bench's summaries of each side's arguments, used for the argument-coverage metric |
| `authorities_cited_by_parties` | no | title, citation only as printed, `by`. Used for the retrieval-recall metric |
| `bench_framing` | no | The bench's issue grouping and interpretive aids |
| `subsequent_history` | no | e.g. a Supreme Court appeal. Never changes the label |

## `manifest` fields

| Field | Required | Notes |
|---|---|---|
| `real` | yes | Real title, all connected appeal numbers, token → real name map, bench members, removed identifiers |
| `sources` | yes | doc, url, sha256, page count, retrieved_at |
| `overlap_with_reference_db` | no | Links to the same case in `nclat_precedents*`, so retrieval can exclude it |
| `in_scope` | yes | Phase 1: IBC appeals only |
| `split`, `strata` | yes | train ≤ 2023 · dev 2024 · test ≥ 2025 (enforced) |
| `build`, `qa`, `contamination_probe` | build yes | Who drafted and reviewed, QA flags, and per-model probe results |

## What the validator enforces across the three files
- The same `case_uid` appears in all three files.
- Every issue has exactly one finding.
- `law_as_of` is the decision date minus 1 day.
- The split matches the decision year, and `strata` matches the unspoiled record.
- Non-IBC proceeding types are not marked in scope.
- No chronology event is dated on or after the decision.
- Every `src` page exists in its PDF.
- No real name, bench member, appeal or application number from the manifest appears in unspoiled, and no case-number pattern does either.
- No 8-word phrase is shared between unspoiled and the ratio, holdings or operative order.
- Issues contain no outcome words.
- No appeal number belongs to two cases (connected appeals are one case).
- Split lists agree with the manifest.
- A synthetic template record is never allowed into the real DB.
