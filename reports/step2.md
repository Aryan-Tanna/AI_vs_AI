# LexArena: Step 2 report (Law DB loading)

**Date:** 2026-10-07
**Commits:**
- `5e9f3d5`: source data repair (D-036)
- `21908c8`, `798d80f`: Step 2
- `aaa19f5`: decision-date fix

**Status:** built, tested and committed. Step 2 is **not ticked** until you've looked at this. Step 1 is ticked.

## Decisions waiting on you

1. **Q-022: dangling cross-references in the Law DB.** 184 `intersecting_statute_ids` (264 references) point to no record.
   - **28 have an obvious match:** another spelling or a sub-section of an existing ID (`IBC_SEC_21` → `IBC_2016_SEC_21`, `IBC_SEC_14_SUB_2` → `IBC_2016_SEC_14`). Most are in the IBBI regulation records.
   - **156 name sections or whole Acts that aren't in the Law DB** (`ARBITRATION_ACT_1996_SEC_17`, `COMPANIES_ACT_2013`, ...).
   - **What I propose:** rewrite the 28 in the source files, the same way as the data repair, and leave the 156 reported until you add those sections.
   - **The full list** is in `reports/law_db_validation.json`.
2. **Which step comes next: 3 or 4?**
   - **Step 4 (precedents into Qdrant)** gets you searchable precedents sooner.
   - **Step 3 (drafting date rows for your approval)** closes R-019, below. Its output waits on your approval of each row, so starting it earlier gives you more lead time.
   - My recommendation: **Step 3 first**, because of R-019.

## What's in the databases now

- **MongoDB:** the real Law DB is loaded, 139 records, snapshot `5a92419f…`. It's the first real data in the system.
- **Qdrant:** still empty. Precedent vectors come in Step 4.
- **Every section is `UNVERIFIED` (R-019).** No date rows have been approved yet, so nothing is hidden by date. An agent arguing a 2018 case could see a section inserted in 2020. Step 3 drafts those rows for you to approve.

## What I built

### Validation

`lexarena law validate` writes a report covering every file and record.

**Blocks loading (nothing loads):**
- unparseable JSON;
- a record that doesn't match the frozen format;
- two records with the same `_id`.

**Reported only:**
- dangling cross-references, each with suggested matches from one general rule. Nothing is matched automatically.
- error-code problems: none, repeated, or not an uppercase tag;
- a record that lists itself;
- fields the format doesn't document.

### Loading

`lexarena law load` makes MongoDB match the source files exactly: new records are added, edited ones updated, deleted ones removed, and unchanged ones left untouched. Each stored record sits unchanged inside a wrapper that adds its content hash and source file. A **snapshot ID** for the whole Law DB goes into every session's version stamp.

### `get_statute(id, as_of)`

- **Only approved rows count:** only APPROVED `temporal_overlay` rows for that section are used.
- **Each row on its own date:** a row is checked against the case date it names (FILING, DEFAULT, DECISION, ...). A date the case doesn't have is reported, never guessed.
- **Not in force looks unknown:** a section that isn't in force on that date comes back **exactly like an unknown ID** (`None`), so its existence doesn't leak.
- **No date rows:** the section is shown as `UNVERIFIED`.
- **Conflicts raise:** two rows covering the same thing on the same date is a data error.

### Storing date rows

A date row is stored only if:
- it is APPROVED;
- its section exists in the Law DB;
- its window doesn't overlap another row for the same section, parameter and date label.

Only the offline ingestion process can write. Lawyers, THEMIS and judges get a read-only Law DB handle.

### Source data repair (D-036, done earlier today)

- **What changed:**
  - 14 broken-JSON spots fixed;
  - 28,147 `[cite: N]` markers removed;
  - the misspelled key `surge_summary` renamed to `summary`;
  - the duplicate `PMLA_2002_SEC_8` removed.
- **Result:** Law DB 139/139 valid; precedents 2,995/2,995 valid. Five precedents are readable again, and none of them is a dev case.

## Test results (actual output)

```
offline:      318 passed, 112 skipped
integration:  107 passed           (real MongoDB, Qdrant, Redis)
ruff, mypy:   clean
```

**Tests first, honestly:** this time I wrote the tests before the code. They all passed on their first run, so I planted bugs to check they can fail. Each turned the suite red:

| Planted bug | Result |
| --- | --- |
| draft date rows treated as approved | 1 failed |
| a section not in force still shown | 6 failed |
| unapproved rows stored | 1 failed |
| overlap check removed | 1 failed |
| deleted records kept on reload | 1 failed |
| duplicate IDs don't block loading | 1 failed |
| a missing case date guessed | 1 failed |
| the decision date returned to a lawyer | 1 failed |

**A bug the review caught (fixed in `aaa19f5`):** `get_statute` returned the date each row was checked on. For a row keyed on the decision date, that would have handed the simulation date to lawyers, THEMIS and judges, against the Step 1 guarantee. It was latent, because no row is approved yet. That date is no longer returned, and a sentinel test now guards it.

## Sample output: real Law DB, real MongoDB, lawyer's handle

```json
{
 "statute_id": "IBC_2016_SEC_7",
 "in_force": "UNVERIFIED",
 "applied": [],
 "unresolved": [],
 "record.section_title": "Initiation of corporate insolvency resolution process by financial creditor",
 "record.mandatory_prerequisites[0]": "Filing of application in prescribed form, manner, and accompanied by the prescribed fee."
}
unknown id -> None
```

Validation summary for your Law DB:

| Check | Result |
| --- | --- |
| Records read / valid | 139 / 139 |
| Parse errors, malformed records, duplicates | 0, 0, 0 |
| Error-code problems, self-references | 0 |
| Dangling cross-references | 184 distinct (264 uses); 28 with a suggested match |
| Field not in the format | `diagnostic_checklist.expense_provision` (IBBI_CIRP_REG_6) |

## Definition of done

- [x] Acceptance criteria:
  - the validation report lists every malformed and dangling record;
  - `get_statute` hides a section that isn't in force, tested with an approved sample row on a placeholder section, not real law.
- [x] Tests written first, all passing.
- [x] No law or tuning literals: the scanner passes.
- [x] No path to sealed data:
  - `get_statute` can't reveal the decision date (sentinel test);
  - writes are limited to ingestion, tested for 5 other roles.
- [x] DECISIONS D-036 to D-039; OPEN_QUESTIONS Q-021 (closed), Q-022, R-019, S-008.
- [x] Retrospective below.

## Retrospective

- **Harder than expected:** keeping each new feature from reopening an old guarantee. The date leak came from a reasonable-looking debug field. From now on, every repository that returns data to a session role gets the sentinel check by default.
- **What I'd do differently:** write the leak sentinel together with any new read path, not after a review finds the gap.
- **Changes to later steps:**
  - **Step 3** should first draft date rows for the sections the 14 dev cases rely on (closes R-019 where it matters).
  - **Step 4** depends on Q-022's ID convention to resolve precedent citations.
