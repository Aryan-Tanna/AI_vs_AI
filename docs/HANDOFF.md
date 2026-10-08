# Handoff: state of LexArena (end of the 2026-10-08 session; top note added 2026-10-09)

## Start here (2026-10-09)

- **Main is up to date.** Parth's Steps 8-13 and the review viewer were pulled as a fast-forward with no conflicts.
  965 offline tests pass and 164 integration tests pass. Mypy needs `uv sync --group ui` (Streamlit). Read
  `docs/HANDOFF_ARYAN.md` (Parth's notes) next.
- **No model is degraded, by the owner's decision (D-084, D-085).**
  - The lawyer runs at full (default) reasoning with a 4,096-token output cap.
  - The verifier runs at full reasoning with a 4,096-token cap, on its own key `Groq_API6`.
  - All Groq keys (`Groq_API1`-`Groq_API7`) are free tier: 8,000 tokens a minute and 1,000 requests a day.
    `Groq_API5` is shared with another user.
  - Free-key sessions are plumbing tests only. Real sessions use paid keys.
- **Fixed on 2026-10-09:** `.env.local` held another machine's service passwords. They were restored from
  `.env.docker`. Never re-run `make_env.py` here: it would force wiping MongoDB, which holds the only copies of the
  clerked dev cases.
- **Nothing real has run yet.** `data/cases/` is empty. Dev-run lessons are cleared in Step 14 before v1.0.
- **Next (the owner said tomorrow):**
  1. Finish the first live end-to-end DEV_0001 session (HANDOFF_ARYAN §5.1). Expect free-tier rate-limit pauses at
     full reasoning; the runner resumes from the cache.
  2. The owner decides: persona approval (Q-031), the D-071 and D-078 choices, the Step 4, 6 and 7 ticks, and the
     three limitation drafts.
  3. Clerk more dev cases. The new keys `gemini_api4` and `gemini_api5` are untested.

> **Update 2026-10-09:** Parth built Steps 8 to 13, reflection and the review viewer; read `docs/HANDOFF_ARYAN.md` first.

Read this first in a new session, then CLAUDE.md, the tail of `docs/DECISIONS.md` (D-048 to D-069) and
`docs/OPEN_QUESTIONS.md`. Parth reads `docs/HANDOFF_PARTH.md` first.

## 1. The owner's current direction

- **Plan:** build every Phase 1 step (to Step 14). The owner then supplies the 500 cases (NCLAT and Supreme Court
  formats, D-061) and paid API keys for full sessions.
- **Saturday 2026-10-10:** a presentation with a demo and a hypothesis. Proposed:
  - H1: a verified adversarial debate produces fewer hallucinated facts and citations than one frontier model on the
    same case file, while reaching the real outcome at least as often;
  - H2 (long-term): memory improves later unseen cases against an empty-memory run.

  The live debate is not built yet (Steps 8-9). Steps 0-7 can be shown: clerk, retrieval, THEMIS layer 1.
- **Speed:** keep moving. The PDF cleaning is plumbing, not architecture (D-061). Don't fit the code to the provided
  cases; they are references only (guard test).
- **Work split with Parth:**
  - Aryan with Claude Code: Steps 8-10;
  - Parth: Steps 11-13 and a review viewer (D-049, `docs/HANDOFF_PARTH.md`).

  `main` takes changes through branches and PRs; Claude Code reviews and merges.

## 2. Where the build plan stands

| Step | State |
| --- | --- |
| 0-3 Repo, schemas and access control, Law DB, drafting tools | ticked |
| 4 Precedents in Qdrant (2,770 points; statute resolution 63.4%, D-050) | built; **not ticked, waiting for the owner** |
| 5 Retrieval tools (compact cards; reranker measured and off, D-055) | ticked (D-054) |
| 6 Clerk (judgment PDF to agent view + sealed ground truth) | built (D-056 to D-061). DEV_0001 SBI v. Krishidhan, DEV_0002 Rajat Metaal and DEV_0003 Citi Securities are stored, with review files in `reports/review/`. **Not ticked: the owner's review of the 3 cases**; then a held-out run on unseen NCLAT and SC judgments |
| 7 THEMIS layer 1 | built (D-062 to D-069); see §3. **Not ticked: the owner decides** with the gaps stated |
| 8 THEMIS layer 2 + outcome policy | **next** |
| 9-14 | not started (11-13 are Parth's) |

## 3. Step 7 in one screen

**Code** (`lexarena/themis_local/`):
- `predicates.py`: a generic engine that compiles expressions to Z3. Only APPROVED predicates whose Law DB item is
  unchanged run. Wrong-kind values are skipped, never rejected.
- `audit.py`: the SPEC D1 audit. Threshold errors arise only against an approved dated value, and only when the
  filing-date and default-date readings agree (D-069).
- `extract.py`: the claim extractor, on the verifier model with prompt v2. Every number that could reject needs
  counsel's own quoted words, checked in code (D-066).
- `limitation.py`: the Art. 137 date chain, with the COVID exclusion and the 90-day floor. Its result is a warning
  only (D-063).
- `layer1.py`: the per-argument wrapper. The limitation rule comes from whichever offered statute carries it (D-068).

**Acceptance** (`scripts/step7_acceptance.py`, `reports/step7_acceptance.md`, 42 arguments): 0 of 34 honest arguments
rejected; 7 of 8 mutations caught. The miss was a sentence naming no section, attached to a statute with no period:
a missed check, not a rejection.

**Not met as written:**
- no open-interpretation case (no predicate drafted yet);
- the honest arguments are the clerk model's paraphrases, not counsel's words: real submission paragraphs hold real
  names, and the pseudonym map is not stored;
- no precedent-based arguments.

**Re-running the acceptance script** must pass the alternative date readings (already wired in). It costs about 20
minutes of Groq time per uncached run, and one key's daily limit is 200,000 tokens.

## 4. Legal data

**Approved and loaded** (the owner's approvals, run by Claude Code at his explicit instruction, D-064):
- s.4 Rs 1 crore from 24.03.2020, keyed FILING;
- in-force dates: s.10A 05.06.2020, s.29A 23.11.2017, s.32A 28.12.2019, s.240A 06.06.2018.

**Drafted, waiting for the owner** (`lexarena review show <id>`, then `review approve <id> --by Aryan`, then
`review load`):

| Draft | Row | Claude Code's research (D-069) |
| --- | --- | --- |
| `OV_LIMITATION_ACT_1963_ART_137_f589ec605f` | period 3 years, from 01.01.1964, keyed FILING | Keep 1964. *B.K. Educational Services v. Parag Gupta* (SC, 2018): Art. 137 governs s.7 applications from the Code's inception (s.238A clarificatory); time runs from the date of default |
| `OV_LIMITATION_ACT_1963_ART_137_adac47aa3a` | excluded window 15.03.2020 to 28.02.2022 | The order covers "all judicial or quasi judicial proceedings" under general or special laws, so NCLT applications included; FILING key correct |
| `OV_LIMITATION_ACT_1963_ART_137_73badec580` | 90-day minimum from 01.03.2022 | Direction III; the checker's max(balance, 90) matches it |
| `OV_IBC_2016_SEC_4_8fdc027705` | Rs 1 lakh before 24.03.2020 | **Blocked by the tool**, correctly: its end date comes from the 2020 notification, not from the s.4 text it quotes. Reject it, or extend the drafting tool to accept a date quoted from a second registered source (S-011) |

**Sources registered** (`data/legal_sources/`, hashes pinned):
- the IBC Acts and notifications (from ibbi.gov.in);
- LIMITATION_ACT_1963 (High Court of Tripura copy; India Code's server returned 504);
- SC_SUO_MOTU_LIMITATION_2022_01_10 (IBBI's copy of the SC order).

**Contested point, handled in code, not in data (D-069):** tribunals have differed on whether the Rs 1 crore threshold
turns on the filing date (the majority NCLT view, *Jumbo Paper*) or the default date (as read from *Madhusudan Tantia*,
NCLAT 2020). Layer 1 checks a threshold only when both readings give the same figure (config
`themis_local.threshold_date_readings`); otherwise THRESHOLD_NOT_VERIFIABLE goes to layer 2. This follows SPEC D2:
contested readings are never fixed rules.

## 5. Waiting on the owner

- Tick or hold Steps 4, 6 and 7.
- Approve or reject the three limitation drafts. Reject or keep the blocked s.4 one-lakh draft.
- Open questions:
  - Q-025: the 2026 Amendment Act, versioned records;
  - Q-026: an `sc_authorities` side collection, which matters now that SC appeals are in scope; planned with Step 8;
  - Q-010, Q-011, Q-012, Q-015, Q-017, Q-018.
- Risks to watch:
  - R-027: the extractor misreads legal phrases as values;
  - R-028: layer 1 checks little, so don't oversell it;
  - R-029: `law:` predicate inputs read stored, not dated, values.
- Push `main`; it is well ahead of origin. Claude Code commits but never pushes.

## 6. Next: Step 8 (THEMIS layer 2 and the outcome policy)

Per BUILD_PLAN and SPEC D4, D5, D7, D8, on the verifier model family (different from the lawyers'):
- citation tier (VERIFIED, REFERENCED, UNVERIFIABLE) plus entailment against the precedent's ratio
  (ERR_PRECEDENT_MISATTRIBUTED only on CONTRADICTS);
- every factual claim traced to a record ID (ERR_FACT_NOT_IN_RECORD, ERR_EXHIBIT_CONTENT_FABRICATED);
- responsiveness;
- repetition (a hard error only above `themis_local.repetition_hard_threshold`).

Then the outcome: PASS, PASS_WITH_NOTES, REVISE with exact codes and record IDs up to `retry_cap`, FLAGGED. Merge the
extractor's UNMAPPED warnings (`ExtractionReport.warnings`) into the outcome, and build alternative views with
`alternative_readings`. Consider the `sc_authorities` collection (Q-026) here.

## 7. Standing instructions

- **Frozen formats:** the Law DB and precedent formats don't change; add side collections instead.
- **Claude Code never approves law** unless the owner explicitly says so, and then logs it.
- **Drafts:** Claude Code may hand-write drafts (`lexarena draft import`) from registered official text.
- **Commits:** commit with short informal messages after the full suite passes (check the exit code); never push.
- **Out of quota:** ask for keys. The owner has more Gemini and Groq keys and is moving to paid ones.
- **Outputs:** concrete, with real JSON from dev cases. Tests first; plant bugs to prove the tests fail; log every
  decision.

## 8. Environment facts

- **Docker:** the CLI is at `C:\Users\aryan\AppData\Local\Programs\DockerDesktop\resources\bin` (not on PATH). Start
  it with `docker compose --env-file .env.docker up -d`.
- **Secrets:** `.env.local`, `.env.sealed` and `.env.docker`, from `scripts/make_env.py`. Read key names only, never
  values.
- **Models** (config v1):
  - lawyer: Groq gpt-oss-120b (`Groq_API1`);
  - verifier: Groq qwen3.8-27b (`Groq_API3`);
  - judge and auditor: gemini-2.5-flash (`gemini_api`);
  - drafter and reflection: gemini-3.5-flash (`gemini_api2`);
  - clerk: gemini-3.5-flash (`gemini_api3`) plus gpt-oss (`Groq_API4`).
- **Free-tier limits:**
  - Gemini: 20 requests a day per model per key;
  - Groq: about 7,000 input tokens per request and 200,000 tokens a day per key.
- **LLM traffic:** the cache is `.cache/llm_cache.sqlite` (its key ignores which API key was used); the call log is
  `.cache/logs/llm_calls.jsonl`.
- **Windows console:** the CLI forces UTF-8 output (legal sources contain Hindi text).
- **Official sources:**
  - ibbi.gov.in and thc.nic.in are reachable;
  - indiacode PDF downloads time out;
  - sci.gov.in was unreachable earlier.
- **Rebuilding on a new machine:** CLAUDE.md §12.
