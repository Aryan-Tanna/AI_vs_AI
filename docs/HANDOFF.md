# Handoff: state of LexArena (updated 2026-10-08)

Parth: read `docs/HANDOFF_PARTH.md` first.

## Update 2026-10-08: Parth's repo merged, verdict rule changed

- **Repositories:**
  - `origin` is github.com/Aryan-Tanna/AI_vs_AI;
  - `parth` (github.com/ParthShahgg/lex-arena) is fetch-only, with its push URL disabled;
  - branch `lexarena-v2-aryan` is the snapshot taken before the merge;
  - commit e0e979c records Parth's history with the `ours` strategy (credit only; no files taken).
- **Porting plan:** D-049 lists what is taken from Parth's code, at which step, and what is not. Read it before porting anything.
- **Git trap (R-023):** Parth must not pull this `main` into his branch; git would fast-forward and drop his files from his working tree. One canonical repository still needs agreeing with him.
- **Verdict (D-048, D-051):** the bench's reasoned, order-swapped majority decides. The advocacy score is secondary and breaks an even split only. Fewer than `min_deciding_judges` deciding judges gives an UNSTABLE verdict. INTENT, ARCHITECTURE §5, BUILD_PLAN Step 11 and the config are updated; SPEC E1 is superseded but unedited.
- **Step 4 changed while under review (D-050):**
  - the alias table `data/statute_aliases.json` lifts statute resolution to 63.4% (12,292 of 19,381; was 55%);
  - payloads gain `derived_hash`, and the snapshot is now `03f5dd40...` (was `b5a13215...`);
  - the real load refreshed 2,773 payloads with 0 re-embedded, and a re-run changed nothing.
- **Do not port Parth's limitation engine as code.** Its counting conventions (trigger day, s.14 end days, acknowledgment on the last day, the COVID floor) are legal rules. They go to `review/` in Step 7; Q-027 blocks COVID.
- **Tests at the end of the session:** see the latest commit message.


Read this first in a new session, then CLAUDE.md, docs/DECISIONS.md (D-001 to D-047) and docs/OPEN_QUESTIONS.md.

## Where the build plan stands

| Step | State |
| --- | --- |
| 0 Repository and config | ticked |
| 1 Schemas and access control | ticked |
| 2 Law DB loading | ticked |
| 3 Drafting tools for side collections | ticked |
| 4 Precedent DB to Qdrant | built, all acceptance checks passed on real data; **not ticked, waiting for the user's review** |
| 5 Retrieval tools | built 2026-10-08 (D-052); 5 hand-written queries in `reports/step5_queries.md` (`scripts/retrieval_queries.py`); ticked 2026-10-08 (D-054) |
| 6 Clerk | built 2026-10-08 (D-056 to D-061). `lexarena clerk run --file <pdf> --case-id DEV_000N`; review files in `reports/review/`; sealed record via `lexarena clerk show`; approve via `lexarena clerk approve`. Stored dev cases: DEV_0001 SBI v. Krishidhan (`data/dev/State_Bank_Of_India_vs_Krishidhan_Seeds_Pvt_Ltd_on_17_November_2020.PDF`), DEV_0002 Rajat Metaal (`data/dev/Rajat_Metaal_Polychem_Pvt_Ltd_vs_Neeraj_Bhatia_And_Anr_on_4_September_2024.PDF`), DEV_0003 Citi Securities (`data/dev/Citi_Securities_Financial_Services_vs_Sudip_Bhattacharya_Resolution_on_16_September_2022.PDF`). **Not ticked: waiting for the owner's review** of the three cases; then a held-out run on unseen NCLAT and SC judgments on frozen clerk code (the owner asked whether the clerk generalises) |

Reports per step: `reports/step1.md`, `step2.md`, `step3.md` (untracked; Step 4 summary is in this file).

## Step 4 results (real data, 2026-10-07)

- **Points:** 2,773 points = 2,773 distinct cases. 203 exact duplicate copies merged; 19 differing copies of one case each keep the first and are reported; 167 `precedent_id`s are shared by different cases.
- **Payloads:** 5 random payloads equal the source records.
- **Date cut-off:** a search with a 2019-01-01 cut-off returned only decisions up to 2018-08-16.
- **Exclusions:** an excluded precedent never appears.
- **Re-run:** changes nothing (snapshot `b5a13215…`).
- **Statute links:** 55% of statute citations resolve to Law DB IDs; the rest are mostly naming mismatches (Q-028).

## Waiting on the user

**Approve:** five side-collection drafts, using `lexarena review approve <id> --by <name>` and then `lexarena review load`:
- `OV_IBC_2016_SEC_29A_544401e4ad` (both models agreed);
- `OV_IBC_2016_SEC_32A_f251867f0d`, `OV_IBC_2016_SEC_240A_eaad7189aa`, `OV_IBC_2016_SEC_10A_4d193cfcd2`, `OV_IBC_2016_SEC_4_6be1c476ec` (written by Claude Code, labelled MANUAL).

Claude Code never approves. It may reject blocked drafts as triage, labelled as its own decision.

**Open questions:**
- **Q-025:** the 2026 Amendment Act is in force from 26.05.2026 for about 60 sections. Recommended: versioned Law DB records, switched by `section_in_force` rows on the DECISION date.
- **Q-026:** Supreme Court rulings. Recommended: a side collection `sc_authorities` in Step 8, because the precedent format allows NCLT/NCLAT only.
- **Q-027:** the COVID limitation exclusion needs the SC suo motu order PDF (sci.gov.in is unreachable from this machine). Also: may s.10A window end dates be computed?
- **Q-028:** a statute alias table, e.g. `COMPANIES_ACT_2013_SEC_` → `CA2013_SEC`.
- Older open items: Q-010, Q-011, Q-012, Q-015, Q-017, Q-018.

## Standing instructions from the user

- **Keep the formats unchanged:** the Law DB and precedent formats are frozen.
- **Don't fit code to the provided data:** the Law DB, precedents and dev cases are references only. A guard test, `tests/test_no_data_coupling.py`, enforces this.
- **Law DB records:** Claude Code may add or edit them (D-045, an override), only from registered official text, with an evidence file in `data/law_db_provenance/` that `tests/test_law_provenance.py` verifies. No hallucination.
- **Do what the free APIs can't:** for example, write drafts by hand through `lexarena draft import`, which runs the same checks as model drafts.
- **Outputs:** concrete, never vague. Claude reviews pipeline outputs itself; passing checks is not proof that something is correct.
- **Rhythm:** tests first, plant bugs to prove the tests can fail, show real output, log every decision.

## Environment facts

- **Docker:**
  - the CLI is at `C:\Users\aryan\AppData\Local\Programs\DockerDesktop\resources\bin`, which is not on PATH in the shells;
  - start it with `docker compose --env-file .env.docker up -d`.
- **Secrets:** `.env.local` (every process), `.env.sealed` (offline and post-verdict only) and `.env.docker` (compose only), all generated by `scripts/make_env.py`.
- **Models:**
  - judge and auditor run on gemini-2.5-flash (key `gemini_api`);
  - drafter_primary and reflection run on gemini-3.5-flash (key `gemini_api2`, a new account where 2.5-flash isn't available);
  - Groq's gpt-oss/qwen allow 7k input tokens per request;
  - Gemini's free tier allows 20 requests a day per model.
- **Official sources:** ibbi.gov.in is reachable and holds the Acts, notifications and the consolidated IBC; sci.gov.in and indiacode are not reachable.
- **Rebuilding on a new machine:** see "On a new machine" in CLAUDE.md §12.
