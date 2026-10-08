# LexArena: Step 1 report (schemas and access control)

**Date:** 2026-10-07
**Commits:** `e058eeb` (credential split), `49285ec` (schemas and repositories), `3441641` (review fixes)
**Status:** built, tested and committed. Step 1 is **not ticked** in BUILD_PLAN until you've looked at this. Step 0 is ticked (your approval).

## Decisions only you can make

1. **Q-020, blocks Step 4.** The precedent files have breakage that only a data edit can fix cleanly (details under "Real data" below). Will you fix the source files, or should ingestion clean derived fields only and report the rest? I recommend you fix the source.
2. **Q-019, blocks Step 6.** You review each clerked case before it runs, which means reading the sealed part before any session exists. Today nobody can read it until after a verdict. I propose a REVIEW role that can read it only while the case has no session yet.

Neither one blocks Step 2.

## What changed for you

- **New start command:** `docker compose --env-file .env.docker up -d`.
- **Three env files now.** Your API keys are still in `.env.local`, unchanged; I checked they're identical to before.
- **New credentials:** I generated fresh Mongo passwords, two Qdrant keys and a Redis password.
- **Fresh volumes:** I recreated the database volumes. They were empty, so nothing was lost.
- **Fresh machine only:** `.venv/Scripts/python scripts/make_env.py` regenerates all of this. You don't need it otherwise.

## What I built

### 1. Credentials split by process (D-034)

| File | Loaded by | Holds |
| --- | --- | --- |
| `.env.local` | every process, including the session (lawyers, THEMIS, judges) | API keys, app Mongo user, Qdrant **read-only** key, Redis |
| `.env.sealed` | clerk, ingestion, evaluator, reflection only | sealed Mongo user, Qdrant **write** key |
| `.env.docker` | docker compose only | root and server-side secrets |

- **Session process guard:** it refuses to start if any of 12 restricted names is visible to it, even from the environment.
- **What "absent" means precisely:** `.env.sealed` sits in the repo folder, readable by your Windows user, like any file. The guarantee is that a session process never loads it, refuses to run if it can see it, and has no code path to the sealed database. MongoDB also refuses the app user on sealed data by itself.

### 2. Schemas for every format (`lexarena/schemas/`)

**Frozen formats (Law DB, precedents):**
- Documented fields are validated strictly; a number written as text is rejected.
- Any other field is **kept and reported**, never dropped and never special-cased (D-033, your "don't overfit" instruction).

**Side collections and lessons:**
- `temporal_overlay` and `predicate_registry`, including the expression grammar.
- Structural checks: every variable is declared, a `choose` covers all of its options, operators have the right number of arguments.
- A predicate must use at least one `claim:` input (D-021), and its error code must be a D8 hard-error code.
- Lessons: judge memory takes LEGAL_RULE lessons only, lawyer lessons need a party status, and EVIDENCE-driven lessons are impossible by type.

**SPEC H collections:**
- `cases`: every fact, exhibit, party and issue ID that is referred to must exist. LEX-P must represent the PETITIONER side and LEX-D the RESPONDENT side.
- Ground truth, turns and sessions.

### 3. Access control (`lexarena/storage/`)

One policy table, copied from SPEC I1, is checked on every call. Ground truth has three independent layers:
- **Credentials:** only a sealed process can open it, and MongoDB refuses the app user.
- **Role:** only the evaluator and reflection may read it.
- **State:** the session must be about that case and in VERDICT_RECORDED or later. The state is read from the database, never taken from the caller.

**Changes from the SPEC, all MINOR as agreed (D-035):**
- **Transcript split:** published turns and private THEMIS data are separate collections.
- **Stripped from the agent view:** lawyers, THEMIS and judges get no decision date, `build` or `split`.
- **Exhibits:** each carries `source_paras` (SPEC I3-8 requires it).
- **Split values:** `split` gains `DEV`.

## Test results (actual output)

```
offline:      299 passed, 98 skipped
integration:   93 passed            (real MongoDB, Qdrant, Redis)
ruff:         All checks passed!
mypy:         Success: no issues found in 59 source files
live smoke:   {"role": "lawyer", "model": "openai/gpt-oss-120b", "value": {"answer": 365, "unit": "days"}, "attempts": 1}
```

**What the integration tests prove:**
- **Barred from ground truth in every session state, including after the verdict:** lawyer P and D, THEMIS-LOCAL P and D, THEMIS-GLOBAL, the judges, the orchestrator and the clerk.
- **Before the verdict:** the evaluator and reflection are refused in CREATED, IN_PROGRESS and ABORTED, and can read only after the verdict.
- **Wrong case:** a verdict in another case doesn't unseal this one.
- **Private turn data:** P's data is refused to everyone except P's reflection, and to P's reflection too until the verdict. D's THEMIS can neither write nor overwrite P's data.
- **Session memory:** each side's is separate. THEMIS can read its own agent's memory but not write it.
- **Sentinel check:** unique marker strings are planted in ground truth, `build`, private data and the decision date. None appear in anything a session role reads, and a positive control confirms those reads did return data.
- **MongoDB itself:**
  - the app user can't read or write the sealed DB, grant itself roles, create users or list users;
  - the sealed user can't read the app DB;
  - anonymous access fails.
- **Qdrant:** no key gets 401; the read-only key can read but gets 403 on write; the write key can write.
- **Redis:** the password is required.

**Did the tests prove anything? I planted bugs, and each turned the suite red:**

| Planted bug | Result |
| --- | --- |
| judges allowed to read ground truth | 3 failed |
| state check removed | 9 failed |
| case check removed | 1 failed |
| side check removed | 3 failed |
| decision date not stripped | 1 failed |
| evaluator may record the verdict | 29 failed, 12 errors |
| **real MongoDB grant** of sealed access to the app user | 2 failed, then green after the revoke |

**A real bug found:** Python's date parser accepted `20200101` and week dates like `2020-W01` as decision dates. Only exact `YYYY-MM-DD` is accepted now.

## Sample output

No dev case exists in the SPEC H shape yet; that comes from the clerk in Step 6. So this uses placeholder documents, run against the real MongoDB:

```
stored top-level keys: ['_id', 'agent_view', 'build', 'split']
stored metadata keys:  ['forum', 'key_dates', 'proceeding_type', 'simulation_date', 'statutes_invoked']
lawyer receives keys:  ['case_id', 'factual_background', 'framed_issues', 'lower_forum_order', 'metadata', 'opening_positions', 'parties', 'presumptions', 'procedural_history', 'record', 'reliefs_sought']
lawyer metadata keys:  ['forum', 'key_dates', 'proceeding_type', 'statutes_invoked']
evaluator, verdict not recorded: SealedError: case DEMO_0001 is sealed: session DEMO_S1 is IN_PROGRESS
session process with .env.sealed: a session process must not see these credentials: ['LEXARENA_MONGO_SEALED_DB', 'LEXARENA_MONGO_SEALED_URI', 'LEXARENA_QDRANT_WRITE_API_KEY']
```

## Real data: your files against the frozen formats

Source: `scripts/check_formats.py`.

| | Law DB | Precedents |
| --- | --- | --- |
| Records read | 140 | 2,990 |
| Valid | **140** | **2,989** (1 has no `summary`) |
| Fields not in the format | `diagnostic_checklist.expense_provision` (1 record) | `material_dates` (14), `material_dates_judgment` (1) |
| Values outside the documented shape | none | `forum` like `NCLAT[cite: 1]` (76); `decision_date` like `2017-09-22[cite: 1]` (56) |
| Broken JSON | none | **14 places in 6 files**; the records there are lost |
| Duplicate IDs | `PMLA_2002_SEC_8` | (157 shared `precedent_id`s, known: D-024) |

The broken JSON comes in three shapes:
- objects glued together inside an array (`}{`);
- stray brackets;
- `[cite: N]` markers placed outside the string quotes, like `"...set aside."[cite: 19]}`.

This is Q-020.

## Definition of done

- [x] Acceptance criteria met, shown with real output: barred roles, the evaluator only after VERDICT_RECORDED, a separate database whose credentials sessions never load, and MongoDB itself refusing the shared user.
- [ ] **Tests written first: no.** I wrote the code first and the tests straight after. The planted-bug runs above are what show the tests aren't passing by accident.
- [x] No law or tuning literals: the scanner passes. The only marked literals are grammar arities.
- [x] No access path to sealed data: tested at three layers.
- [x] DECISIONS D-032 to D-035; OPEN_QUESTIONS Q-019, Q-020, R-016 to R-018, S-007.
- [x] Retrospective below.

## What I haven't verified, and limits

- **No per-role database logins inside a session:** Qdrant and Redis can't separate LEX-P from LEX-D, or lawyers from judges, inside one session process. That separation is enforced in Python only (R-016).
- **The import-boundary test has nothing to check yet:** the agent, THEMIS, judge and orchestrator packages don't exist. The checker itself is tested on planted imports (R-017).
- **Decision date and prompts:** session-role repositories never return the decision date, but the orchestrator holds the full case. Step 9 must check assembled prompts for it (R-018).
- **Commit `e058eeb`** doesn't pass on its own: one test imports code from the next commit. I left history as it is.

## Retrospective

- **Harder than expected:** the precedent files. Six of 12 are not valid JSON throughout, so my first check silently dropped whole files. It now reads around each break and reports the location.
- **What I'd do differently:** write the access tests before the repositories, as CLAUDE.md asks. I'll do that from Step 2.
- **Changes to later steps:**
  - **Step 2** extends `check_formats.py` instead of writing a second validator.
  - **Step 4** waits on Q-020.
  - **Step 9** adds the prompt check (R-018).
  - **Step 13** must start the evaluator and reflection as a separate process; the boundary test enforces this once the orchestrator package exists.
