# LexArena architecture, version 2

Image version: [architecture.png](architecture.png). Source of truth for decisions: [CLAUDE.md](../CLAUDE.md) §7.4 and §8.
Research simulation, not legal advice.

## Principles

1. **Agents where the model must decide what to look up** (advocates, judges, case builder, reflection).
   **Code where results must be reproducible or must never decide the merits** (orchestration, verification,
   rules, aggregation, metrics).
2. **The tool registry is the security boundary.** An agent reaches data only through tools registered for its
   role. Leakage filters (own-case exclusion, temporal cutoff, good-law-as-of) run inside the tools.
3. **Every model call runs on one Claude subscription** through the Claude Agent SDK. A checkpointed job queue
   paces work to fit the 5-hour and weekly usage windows.

## Diagram

```
 EXECUTION LAYER (under every phase)                                                   [built]
 ┌──────────────┐   ┌──────────────────┐   ┌──────────────────┐   ┌─────────────────────────────┐
 │ Job queue    │──▶│ Session runner   │──▶│ Cache + usage    │──▶│ Agent backend               │
 │ SQLite,      │   │ stop at 85 % /   │   │ ledger (5-hour,  │   │ Agent SDK → Claude Code,    │
 │ checkpoints  │   │ reject; --wait   │   │ weekly windows)  │   │ subscription login, no API  │
 └──────────────┘   │ resumes at reset │   └──────────────────┘   │ key, no built-in tools,     │
                    └──────────────────┘                          │ empty sandbox folder        │
                                                                  └─────────────────────────────┘

 PHASE 0 · OFFLINE DATA
   India Code/Gazette ──▶ Law DB builder (code+human) ──▶ laws.jsonl          get_provision(id, as_of)
   Judgment + NCLT PDFs ─▶ CASE BUILDER (agent) ─▶ validator ─▶ human ─▶ public_db/   (schema: docs/schema/)
                                                     unspoiled | ground_truth (SEALED) | manifest | splits
   Reference precedents ─▶ ingest + authority table ──▶ authorities.jsonl  status_as_of(date)
                                                   └─▶ proposition index (BM25 + dense, Qdrant)

 PHASE 1 · DEBATE RUNTIME (one case per job, one checkpointed step per turn)
   Debate handler (code) ─▶ unspoiled reader (code; fixes law_as_of)
   for each turn:
     APPELLANT / RESPONDENT (agents, sonnet) ──tools──▶ read_record, read_transcript            [built]
                                                        search_authorities, get_provision,
                                                        authority_status, rules.*, recall_lessons
        │ structured turn {prose, claims[]}
        ▼
     THEMIS-LOCAL (sequential gate, not an agent)                                  [control flow built]
        1. claim extraction (haiku) → ClaimSet JSON
        2. STAGE A: code + rules + Z3   ── fail → same advocate revises → back to 1   (≤ 3 attempts)
              3rd failure → keep hard flags, continue
        3. STAGE B: LLM semantic checks (haiku), once, on the final version — misattributed
              ratio, unsupported by record, new facts → flags only, never back to Stage A
        publish: PASSED | FLAGGED_HARD | FLAGGED_SOFT | FLAGGED_BOTH
        ▼
     hearing transcript (hash-chained, shared page) → runs/<run_id>/<case>/transcript.json     [built]
   seal

 PHASE 2 · THEMIS-GLOBAL (whole transcript, BEFORE the bench)
   sealed transcript ─▶ re-run Stage A on all claims · claim drift · self-contradiction ·
                        unanswered points by issue · flagged citations reused
                        (code + haiku/sonnet calls)
                    ─▶ global findings report (per issue, same headings for both sides;
                        findings only — no verdict, no side scores)

 PHASE 3 · BENCH (independent, different Claude model)
   inputs: sealed transcript + global findings report
   TEXTUALIST · PURPOSIVE/COMMERCIAL · PROCEDURALIST (agents, opus; read-only tools)
        ─▶ aggregator (code: majority label, issue merge, dissent) ─▶ order writer (haiku call)

 PHASE 4 · EVALUATION (after the order)
   evaluator (code: unseal ground truth, metrics, bootstrap CIs; reuses the global report)
   baselines: majority class · metadata-only · single LLM (sonnet)                            [built]

 PHASE 5 · REFLECTION MEMORY (train split only; frozen before dev/test)
   REFLECTION (agent per side) ─▶ lesson validator (code) ─▶ memory per side ─▶ recall_lessons
```

## Components

| Component | Kind | Model | Status |
|---|---|---|---|
| Job queue, session runner, cache, usage ledger | Code | — | Built |
| Agent backend (Claude subscription via Agent SDK) | Code | — | Built, live smoke test passed |
| Unspoiled reader (`public_db.py`) | Code | — | Built (validates against the schema) |
| Public case DB schema, validator, JSON Schemas, example | Code | — | Built (`schemas/public_case.py`, `scripts/validate_public_db.py`, [schema/](schema/)) |
| Debate handler: 5-turn MVP, hash-chained transcript | Code | — | Built (THEMIS/bench not wired) |
| Appellant / Respondent advocates | Agents | Sonnet | Built: record + research tools, 5-turn MVP |
| Single-LLM baseline | LLM call | Sonnet | Built |
| Case Builder (PDF → public case) | Agent | Sonnet / Opus | Planned |
| Reference DB ingest (load, normalise, dedup, statute IDs) | Code | — | Built: 2,696 cases (`python -m lexarena.ingest.build_reference`) |
| Law DB lookup / authority registry / proposition index | Code | — | Built as stand-ins: law DB summaries (no bare text yet), SC seed (unverified, year only), BM25 index; dense pending bge-m3 weights |
| Retrieval / law / rules tools | Code | — | Built (`tools/research.py`); memory tools planned |
| THEMIS-LOCAL gate order (extract → A ≤ 3 → B once) | Code | — | Built (`themis/local.py`, 5 tests) |
| THEMIS-LOCAL checks: extractor, Stage A, Stage B | LLM call + code + LLM call | Haiku | Built, wired into the debate handler |
| Rule engine + Z3 | Code | — | Built (`lexarena/rules/`; real-case fixtures pending the public DB) |
| THEMIS-GLOBAL (before bench) | Code + LLM calls | Haiku / Sonnet | Planned |
| 3 judges | Agents | Opus (Sonnet if the weekly Opus cap binds) | Planned |
| Aggregator + order writer | Code + LLM call | Haiku | Planned |
| Evaluator | Code | — | Planned |
| Reflection + lesson validator | Agent + code | Sonnet | Planned |

## Tool access by role

| Tool | Advocates | Judges | Reflection | Case Builder |
|---|---|---|---|---|
| `read_record`, `read_transcript` (built) | ✓ | ✓ | ✓ | – |
| `search_authorities`, `authority_status`, `get_provision` | ✓ | ✓ | ✓ | – |
| `rules.*` (limitation, threshold, s.10A, s.9 notice, appeal timeline) | ✓ | ✓ | ✓ | – |
| `recall_lessons`, private notes | own side | – | – | – |
| `read_ground_truth`, `propose_lesson` | – | – | train only | – |
| `pdf_search`, `pdf_read_page`, `validate_draft` | – | – | – | ✓ |

## Running in 5-hour windows

```
python -m lexarena.cli smoke                          # 1 tiny Haiku call: login, tools, isolation, window state
python -m lexarena.cli enqueue debate --split train --run-id train1
python -m lexarena.cli run                            # work until the window is ~85 % full, then exit
python -m lexarena.cli run --wait                     # sleep through resets until the queue is empty
python -m lexarena.cli status                         # job counts, window state, failures
```

- Before each job the runner reads the usage ledger. If the window is rejected, nearly full (≥ 85 %), or the
  CLI has sent a limit warning, it stops between jobs.
- A limit hit in the middle of a job puts the job back in the queue with its checkpoint intact. Completed
  steps (debate turns) are not re-run in the next window, and the cache makes any repeated call free.
- `ANTHROPIC_API_KEY` must be unset. If it is set, Claude Code bills the API, so the backend refuses to start.
- This is for the owner's own runs on their own account. Do not share the login across a team (see
  CLAUDE.md §7.4).

## Changes from the original diagram

| Original | Version 2 | Reason |
|---|---|---|
| AgentRouter gateway; Opus, GPT-5, GPT-4o-mini | Claude subscription via Agent SDK; Haiku / Sonnet / Opus by role | Budget decision; paced to usage windows |
| LEX-P "Plaintiff" / LEX-D | Appellant / Respondent | The data is NCLAT appeals |
| Clerk State Machine on gpt-4o-mini | Orchestrator and reader in code | Deterministic, testable |
| Advocates as single LLM calls | Tool-using agents with role-scoped tools | They choose lookups; every step is traced |
| Z3 gate checks ₹1 Cr, s.10A, limitation | Rule engine checks claims; Z3 only for uncertain facts | The gate must not decide the merits |
| Retry ×3 via a "Lawyer Agent" | Same advocate revises; Stage A ≤ 3 attempts, then Stage B once on the final version | Authorship stays with the side; Stage B never checks text that will change |
| THEMIS-GLOBAL after the trial | THEMIS-GLOBAL before the bench; findings are a judge input | Judges see cross-turn problems; findings only, never a verdict |
| Precedent DB of "verified" ratios | Reference DB + verified authority table | Status is computed as of the cutoff |
| Pragmatist judge | Purposive / Commercial, legally constrained | Viability-based refusal is wrong in law |
| Judges on another vendor's model | Judges on a different Claude model | Only Claude is available; side-swap test measures bias |
| Scoring matrix | Issue-wise findings + majority label | A weighted opaque score can't be validated |
| Continuous learning feeds runtime | Train-only, validator-gated, frozen | Prevents test leakage |
