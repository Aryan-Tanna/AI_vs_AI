# LexArena roadmap

Where the project stands and what to do next, in order. Detailed specs: [CLAUDE.md](../CLAUDE.md) (source of
truth), [ARCHITECTURE.md](ARCHITECTURE.md), [schema/README.md](schema/README.md). Status as of 2026-10-05.

## What is done

| Area | What exists | Evidence |
|---|---|---|
| Design | Reframed as NCLAT appeals; leakage rules; legal rules with `VERIFY` tags; agents vs code split; sequential THEMIS gate; THEMIS-GLOBAL before the bench (findings only); closed record (no evidence beyond the judgments) | CLAUDE.md §1–§9, decisions log §12 |
| Running on the subscription | Claude Agent SDK backend (no API key), isolation (empty sandbox, no built-in tools unless the mode allows), job queue with per-step checkpoints, runner that stops near the 5-hour limit and resumes after reset, cache, usage ledger | Three live debates; tests |
| Dynamic sources | Any precedent/law DB plugged in via `config/sources.yaml` (generic JSONL field mapping, custom types, raw-dump ingest mapping); `eval` mode (closed, cutoff-safe, statute sites only) vs `live` mode (open web search, MCP servers) | `tests/test_sources.py`; web scoping checked live |
| Public case DB format | Three records per case (unspoiled / sealed ground truth / manifest), segmentation rules, Pydantic schema, JSON Schemas, validator (leakage, anonymisation, splits, page refs), synthetic example | `docs/schema/`, `scripts/validate_public_db.py` |
| Rule engine (Phase 1) | Art.137 limitation with s.18/19/14, COVID order, s.4 threshold, class creditors, s.10A, s.8/9 timing, s.61/62 appeals; Z3 for uncertain dates (ALWAYS / POSSIBLY / NEVER) | 37 rule tests |
| Reference DB (Phase 0a) | 2,696 unique NCLAT cases from the raw files, cleaned, deduplicated, one statute ID scheme | `python -m lexarena.ingest.build_reference` |
| Retrieval (Phase 2) | BM25 with section-aware tokens + bge-small-en-v1.5 dense (384 dims), fused; cutoff and exclusions applied before ranking; overruled flags surfaced | Leakage tests |
| Viewer | Local read-only Streamlit app: live transcript with THEMIS gate per turn, bench and audit, evaluation, usage dashboard, case browser (`python -m lexarena.ui`) | AppTest on all pages; screenshots |
| Silver public DB | 1,073 auto-built train/dev cases from the reference DB, anonymised, outcome-stripped, validated | `data/reports/silver_build.md`; `tests/test_silver.py` |
| Agents + THEMIS-LOCAL (Phase 3) | Advocates with record and research tools and a proceeding-specific framework (identical for both sides); Haiku claim extraction; Stage A (invented record refs, facts, arithmetic, provisions in force, authorities); Stage B (misattribution, unsupported facts, new facts); revision by the same advocate | Three live debates on the synthetic case; 107 tests |

**Measured cost:** a 5-turn debate with THEMIS-LOCAL costs about 27 calls and ~$1.5 API-equivalent (not billed
on the subscription). That figure is after the extractor's thinking was turned off, which cut extraction
output from ~170k to ~52k tokens. Three debates plus our chat in the same window reached about 90% of one
5-hour window.

## What is stand-in or unverified (do not report results on these yet)
- **Supreme Court authorities:** 27 landmarks with year only, unverified (`data/seed/sc_landmarks.json`).
- **Law DB:** LLM-written summaries, no bare text, no version history; only a few insertion dates are encoded.
  indiacode.nic.in refuses automated fetches (HTTP 403), so a local Law DB v2 is required.
- **Treatment of precedents:** only the source DB's undated "overruled" flag.
- **Rule engine `VERIFY` items:** listed in CLAUDE.md §10 Phase 1 (notification dates, COVID floor day, counting conventions).
- **Every live run so far used the synthetic template case**, not a real one. The latest Stage A fixes are covered by tests but have not been re-run live.

## Data plan: silver and gold

| Tier | Built from | Used for |
|---|---|---|
| **Silver** | The 2,696 reference cases converted automatically into the public case format | Train (reflection memory) and dev (prompt tuning, debugging). **Never** for reported results: the summaries were written knowing the outcome |
| **Gold** | The NCLAT judgment text (Indian Kanoon or the NCLAT site) plus the NCLT order where available, built by the Case Builder and human-checked | Test only (100–150 cases), plus the lawyer study |

- **No NCLT order?** Use the judgment's own summary of it, and record the source in the manifest.
- **Exclusions.** Leave out cases that turn on documents whose content the judgment does not describe.
- **Terms of use.** Check Indian Kanoon's terms, or use its API, before bulk download.

## What to do next, in order

### 1. Silver DB: done
`python -m lexarena.ingest.build_silver` builds **1,073 cases (893 train, 180 dev)** into `data/silver/`, all passing
the validator, with no model calls. It's heuristic: roles, proceeding type and grounds are approximate, and only the
impugned-order date is a typed fact. **Live runs are paused** until the owner says so; then use
`LEX_PUBLIC_DB_DIR=data/silver python -m lexarena.cli enqueue debate --split dev --run-id silver-dev1`.

### 2. Phase 4: code built 2026-10-05; tests written, not yet run
Built: THEMIS-GLOBAL (`themis/global_.py`), bench (`bench/`), evaluator (`eval/`, `cli evaluate`). Next: run the
unit tests (no model calls), then, when the owner allows live runs, one silver dev case end to end.
Original plan for reference:
1. THEMIS-GLOBAL on the whole transcript, before the bench (findings only, same format for both sides).
2. Bench-question turn, then 3 judge agents (Opus, read-only tools), then the aggregator, then the order writer.
3. Evaluator: unseal ground truth and compute metrics against the baselines (single LLM, majority class, metadata-only), with confidence intervals. Side-swap test and the with/without-GLOBAL ablation.

### 3. Gold test set (needs the judgments)
1. Collect judgment texts (and NCLT orders) for candidate 2025–26 appeals.
2. Build the Case Builder agent (judgment → three records), then human review, then the validator. Pilot 20 cases first.
3. Check the training cutoff of each Claude model in use. Only appeals decided after it can be test cases.

### 4. Verify the legal sources (in parallel; needs a lawyer)
1. Verify the 27 Supreme Court entries against the judgments and add exact dates (authority table, step J).
2. Clear the rule engine's `VERIFY` items.
3. Start Law DB v2 (step E) with verbatim text and version history for the amended IBC sections: s.4, 5(8), 7, 10A, 12, 12A, 29A, 30, 32A, 61, 238A, 240A.

### 5. Measure and review
1. Run baselines on dev, then 3 real debates to size usage (S2). Decide 5-turn vs 11-turn, and 1 vs 3 judges.
2. A lawyer reads 10 transcripts (W). Fix prompts and the remaining Stage A extraction noise.

### 6. Phase 5: memory, frozen test, human study
1. Reflection memory on the train split only, validated, then frozen. Learning curve on dev.
2. One frozen test run on gold.
3. Lawyer study (Track B) and the review UI.

## Decisions waiting on the project owner
- Who collects the judgment texts, and who reviews gold cases?
- Pro or Max subscription? (Throughput.)
- Which lawyer verifies the authority table and the `VERIFY` items? (On hold: no lawyer yet.)
- How do remands count for `appellant_won`? Silver currently counts a remand as an appellant win; confirm or change.
- Will anyone else run jobs? If so, each person needs their own account, or the backend moves to an API key.
