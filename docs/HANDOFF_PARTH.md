# Handoff for Parth: joining the LexArena build

Written 2026-10-08 for your first clone of this repository. Read this first, then `CLAUDE.md`, `docs/INTENT.md` and
`docs/ARCHITECTURE.md`. If you use Claude Code, it loads `CLAUDE.md` automatically.

## 1. What this repository is, and how your work fits

**What it is.** LexArena simulates Indian insolvency litigation:
- two advocate agents argue a real NCLAT or Supreme Court case;
- THEMIS checks every argument before anyone sees it;
- three judges decide each issue;
- after the verdict, the real outcome is unsealed for evaluation and for lessons that help the agents improve across
  cases.

The rules that never bend are in `CLAUDE.md` §4. In short:
- real cases only, no hallucination path, no bias between the sides;
- nothing legal hardcoded, the data formats frozen;
- the real outcome sealed until the verdict.

**Your earlier work.**
- Your `lex-arena` history is merged into this repository's history (commit `e0e979c`), so you are credited.
- Your files were not copied wholesale: the two `lexarena/` packages collided module by module.
- Your ideas are being ported step by step. D-049 in `docs/DECISIONS.md` lists what was taken, at which step, and what
  was not (with reasons).
- Already ported:
  - the statute alias idea (`data/statute_aliases.json`);
  - "tools are the security boundary" (retrieval tools bound to the case's scope);
  - the per-paragraph routing of a judgment;
  - the leakage and anonymisation scans in the clerk;
  - the judge design: issue-wise reasoned decisions, majority of judges, advocacy score secondary (D-048).

**Important: do not sync your old repository with this one.** Your `integrate-ai-vs-ai` tip is an ancestor of this
`main`. If you pull or merge this `main` into your old `lex-arena` branches, git fast-forwards and your Phase 1-4
files vanish from your working tree (R-023). Instead:
- clone this repository fresh, into a new folder;
- leave the old one as an archive.

## 2. Set up (Windows, about 30 minutes)

```
git clone https://github.com/Aryan-Tanna/AI_vs_AI.git lexarena
cd lexarena
uv sync --python 3.12
.venv/Scripts/python scripts/make_env.py        # writes .env.local, .env.sealed, .env.docker with fresh service passwords
```

1. **Your own API keys.** Open `.env.local` and paste your keys into the variables listed in `.env.example`:
   - `Groq_API1` to `Groq_API4`;
   - `gemini_api`, `gemini_api2`, `gemini_api3`.

   Use keys from your own free accounts. Never commit any `.env.*` file except `.env.example`.
2. **Start the services.** With Docker Desktop running: `docker compose --env-file .env.docker up -d`. MongoDB,
   Qdrant and Redis start.
3. **Build the databases** from the files in git:
   ```
   .venv/Scripts/lexarena law load
   .venv/Scripts/lexarena review load
   .venv/Scripts/lexarena precedents load       # first run downloads the embedding model (~65 MB) and embeds ~2,770 precedents
   ```
4. **Check everything.** All three should pass:
   ```
   .venv/Scripts/python -m pytest -q                                  # offline: ~630 pass
   .venv/Scripts/python -m pytest --run-integration -m integration    # needs Docker: ~150 pass
   .venv/Scripts/lexarena llm smoke                                   # one real call per model role
   ```

**What is not in git:**
- the LLM cache (`.cache/`);
- the clerked dev cases (they live in your local MongoDB).

To get the three clerked dev cases on your machine, run:

```
.venv/Scripts/lexarena clerk run --file "data/dev/State_Bank_Of_India_vs_Krishidhan_Seeds_Pvt_Ltd_on_17_November_2020.PDF" --case-id DEV_0001
```

Repeat for the files listed in `docs/HANDOFF.md`, about 6 Gemini calls each. Gemini's free tier allows 20 calls a
day per model per key.

## 3. Where the build stands (BUILD_PLAN.md)

| Step | State |
| --- | --- |
| 0-3 Repo, schemas and access control, Law DB, drafting of side collections | done, ticked |
| 4 Precedents in Qdrant | built; awaiting Aryan's tick |
| 5 Retrieval tools (compact cards; reranker tested and off) | done, ticked |
| 6 Clerk (judgment PDF to case + sealed ground truth) | built; 3 dev cases clerked; awaiting Aryan's review |
| 7-14 | not started; split below |

Tests are written first, and every non-trivial check has a planted-bug test proving it can fail. Guards run on every
`pytest`:
- `tests/test_no_literals.py`: no legal or tuning number in code;
- `tests/test_no_data_coupling.py`: no real case name or ID in code;
- `tests/test_import_boundaries.py`: session code cannot reach sealed data.

## 4. Work split, so we build in parallel

Each person owns separate packages. The shared contract is `lexarena/schemas/`:
- the transcript, session, case and ground-truth models;
- frozen for this sprint;
- a change there goes in its own small PR that both of you agree to first.
- **Changed since this file was first written (Step 7, 2026-10-08):**
  - `ClaimedThreshold.minimum_amount` is now `float`;
  - `ExtractedChecklist` gained optional fields: `threshold_amount_id`, `chosen_readings`,
    `asserts_within_limitation`, `acknowledgment_dates`;
  - `lexarena/schemas/themis.py` is new (what the extractor model returns);
  - config gained `themis_local` keys.

  Old data still validates (D-062, D-066).

| Who | Steps | Packages | Builds against |
| --- | --- | --- | --- |
| **Aryan (with Claude Code)** | 7 Z3 predicate engine + THEMIS layer 1; 8 THEMIS layer 2; 9 agents + LangGraph session; 10 THEMIS-GLOBAL | `lexarena/themis_local/`, `lexarena/agents/`, `lexarena/orchestrator/`, `lexarena/themis_global/` | retrieval tools, clerked cases, Law DB |
| **Parth** | 11 judges; 12 evaluator; 13 run manager; a review viewer | `lexarena/judges/`, `lexarena/evaluator/`, `lexarena/runner/`, `lexarena/ui/` | `lexarena/schemas/transcript.py`, `session.py`, `ground_truth.py`; test transcripts from `tests/builders.py` |

### Parth's tasks in detail

You have built all of these once before; port the ideas into this codebase's rules.

**Step 11, judges** (`lexarena/judges/`), following D-048 and D-051:
- Persona prompts go to `prompts/judges/`, drafted into `review/` for Aryan's approval (CLAUDE.md §4.8).
- Each persona decides each framed issue twice, with the two sides presented in swapped order and anonymous labels.
- A judge whose two decisions disagree abstains.
- The verdict is the majority of the deciding judges, with dissent recorded.
- The advocacy score breaks an even split only. Fewer than `judging.min_deciding_judges` deciding judges makes the
  verdict UNSTABLE.
- Every reason cites record, statute or precedent IDs, and a validator checks they exist.
- Judges read precedents only through `get_precedent` and `get_record_item` (`lexarena/retrieval/tools.py`,
  `tools_for(Role.JUDGE, ...)`). They never search.

**Step 12, evaluator** (`lexarena/evaluator/`):
- After `VERDICT_RECORDED`, read ground truth through `SealedProcess.evaluator()`. Its `get` refuses earlier states;
  the tests in `tests/test_access_control.py` prove it.
- Compute per-issue alignment, and verdict alignment unless the real outcome is MIXED.
- Baselines: majority class, and a single-LLM call on the same agent view.
- Statistics: balanced accuracy, macro-F1, McNemar against the single-LLM baseline, bootstrap confidence intervals.
- The seed comes from config.

**Step 13, run manager** (`lexarena/runner/`):
- Your checkpoint-and-resume job runner, paced to the free-tier quotas (Gemini 20 a day per model per key; Groq about
  7,000 input tokens per request).
- Runs cases in date order, one at a time.
- Takes memory snapshots; a frozen-memory test mode provably writes nothing; an empty-memory baseline mode.

**Review viewer** (`lexarena/ui/`):
- Your Streamlit app, adapted to show a clerked case's review file and sealed record through
  `SealedProcess.review()`. That works only before the case's first session (D-056).
- Aryan uses it to tick each record item against its source paragraph.

### How we work

- Branch per task: `parth/step-11-judges`, `aryan/step-7-predicates`, and so on.
- Commit small, with tests and a line in `docs/DECISIONS.md` for any design choice.
- Push your branch and open a pull request to `main`. Aryan merges, after Claude Code reviews the diff against
  CLAUDE.md.
- Never commit to `main` directly. Never edit another person's package without asking.
- Before pushing, run `.venv/Scripts/ruff check lexarena tests`, `.venv/Scripts/mypy` and
  `.venv/Scripts/python -m pytest -q`.
- **Things that need Aryan's explicit approval, logged in DECISIONS:**
  - any access to `case_ground_truth`;
  - a change to the Law DB or precedent formats;
  - loading a legal rule that isn't APPROVED;
  - running anything over the 500 before Phase 2.

## 5. Things that will save you time

- **Docker on Windows:** the CLI is under the Docker Desktop install's `resources\bin`, which may not be on PATH. Always
  pass `--env-file .env.docker` to compose.
- **Models in config** (`config/config.v1.yaml`):
  - lawyer: Groq gpt-oss-120b;
  - verifier: Groq qwen, a different family from the lawyer (SPEC I3-7);
  - judge and auditor: gemini-2.5-flash;
  - clerk: gemini-3.5-flash on `gemini_api3`, with gpt-oss as the second family.
- **The LLM cache** (`.cache/llm_cache.sqlite`) makes a repeated call free. The key does not include which API key
  made the call.
- **Every legal number lives in data:** the Law DB, `temporal_overlay` rows and predicates. Every tuning number lives
  in config. The no-literals guard fails on a bare number in `lexarena/`; a reviewed exception carries
  `# literal-ok: <reason>`.
- **Open questions** waiting on Aryan are in `docs/OPEN_QUESTIONS.md`: Q-025 to Q-027 and the older ones listed in
  `docs/HANDOFF.md`.
