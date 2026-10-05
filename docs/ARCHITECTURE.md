# LexArena architecture, version 2

Image version: [architecture.png](architecture.png). Source of truth for decisions: [CLAUDE.md](../CLAUDE.md) §4, §7.4 and §8.
Status and next steps: [ROADMAP.md](ROADMAP.md). Research simulation, not legal advice.

## Principles

1. **Agents where the model must decide what to look up** (advocates, judges, case builder, reflection).
   **Code where results must be reproducible or must never decide the merits** (orchestration, verification,
   rules, aggregation, metrics).
2. **The tool registry is the security boundary.** An agent reaches data only through tools registered for its
   role. Leakage filters (own-case exclusion, temporal cutoff) run inside the tools.
3. **Sources are configuration, not code.** Every precedent DB, law DB, seed list, web rule and MCP server is
   declared in `config/sources.yaml`. Tools and THEMIS ask one `SourceRegistry`, which fans out to whatever
   is enabled.
4. **Two run modes.**
   - `eval`: historical cases with an answer key. Closed and reproducible. Only cutoff-respecting sources, and
     web fetches limited to official statute sites.
   - `live`: new matters. Open web search and external MCP servers are allowed.
5. **Closed record.** There is no evidence beyond what the judgments record. Facts must cite the record (E#/D#),
   and invented exhibits fail deterministically.
6. **Every model call runs on one Claude subscription** through the Claude Agent SDK. A checkpointed job queue
   paces the work to fit the 5-hour and weekly usage windows.

## Diagram

```
 EXECUTION LAYER (under every phase)                                                   [built]
 ┌──────────────┐   ┌──────────────────┐   ┌──────────────────┐   ┌─────────────────────────────┐
 │ Job queue    │──▶│ Session runner   │──▶│ Cache + usage    │──▶│ Agent backend               │
 │ SQLite,      │   │ stop at 85 % /   │   │ ledger (5-hour,  │   │ Agent SDK → Claude Code,    │
 │ checkpoints  │   │ reject; --wait   │   │ weekly windows)  │   │ subscription login, no API  │
 └──────────────┘   │ resumes at reset │   └──────────────────┘   │ key, empty sandbox, built-in│
                    └──────────────────┘                          │ tools only as mode allows   │
                                                                  └─────────────────────────────┘
 SOURCES LAYER (config/sources.yaml → SourceRegistry)                                  [built]
   authority sources: sc_seed (SC, year only, unverified) · nclat_reference (2,696 NCLAT, BM25 + bge-small 384d)
                      · any generic_jsonl DB via field mapping · custom types via register_source_type
   law sources:       law_db_summaries (LLM summaries; Law DB v2 with bare text + versions pending)
   web:               eval → WebFetch on official statute hosts only · live → open WebSearch/WebFetch
   mcp_servers:       live only (or eval if the server enforces the cutoff)

 PHASE 0 · OFFLINE DATA
   raw precedent dumps ─▶ ingest (field mapping, dedup, statute IDs) ─▶ reference_cases.jsonl     [built]
   reference cases ─▶ SILVER public DB (auto; 1,087 train/dev cases, data/silver/)               [built]
   judgment (+ NCLT order) ─▶ CASE BUILDER (agent) ─▶ validator ─▶ human ─▶ GOLD public DB        [planned]
                                     unspoiled | ground_truth (SEALED) | manifest | splits  (schema: docs/schema/)
   India Code/Gazette ─▶ Law DB v2 (verbatim, versioned) ─▶ get_provision(id, as_of)             [planned]

 PHASE 1 · DEBATE RUNTIME (one case per job, one checkpointed step per turn)
   Debate handler (code) ─▶ unspoiled reader (code; fixes law_as_of)
   for each turn:
     APPELLANT / RESPONDENT (agents, sonnet)                                                    [built]
        prompt: side description + proceeding framework (identical for both sides) + s.61(3)/(4) scope
        tools: read_record, read_transcript, search_authorities, get_provision, authority_status,
               rules_* (limitation, appeal timeline, s.9 notice, s.10A, threshold), web per mode
        │ structured turn {prose, claims[] with record refs}
        ▼
     THEMIS-LOCAL (sequential gate, not an agent)                                               [built]
        1. claim extraction (haiku, thinking off) → ClaimSet JSON
        2. STAGE A: code + rule engine + Z3 ── fail → same advocate revises → back to 1  (≤ 3 attempts)
              unknown record ref · fact/event mismatch · day count · computation redone ·
              provision not in force · unverified / post-cutoff authority
        3. STAGE B (haiku), once, on the final version: misattributed ratio · unsupported by record ·
              new facts → flags only
        publish: PASSED | FLAGGED_HARD | FLAGGED_SOFT | FLAGGED_BOTH
        ▼
     hearing transcript (hash-chained, shared page) → runs/<run_id>/<case>/transcript.json     [built]
   seal

 PHASE 2 · THEMIS-GLOBAL (whole transcript, BEFORE the bench)                                   [built]
   re-run Stage A on all claims · claim drift · self-contradiction · unanswered points by issue ·
   flagged citations reused ─▶ global findings report (same headings for both sides; no verdict)

 PHASE 3 · BENCH (independent, different Claude model)                                          [built]
   inputs: sealed transcript + global findings report
   TEXTUALIST · PURPOSIVE/COMMERCIAL · PROCEDURALIST (agents, opus; read-only tools)
        ─▶ aggregator (code: majority label, issue merge, dissent) ─▶ order writer (haiku call)

 PHASE 4 · EVALUATION (after the order)
   evaluator (code: unseal ground truth, metrics, bootstrap CIs; reuses the global report)      [built]
   baselines: single LLM (sonnet) · majority class · metadata-only (from train)                 [built]

 PHASE 5 · REFLECTION MEMORY (train split only; frozen before dev/test)                        [planned]
   REFLECTION (agent per side) ─▶ lesson validator (code) ─▶ memory per side ─▶ recall_lessons
```

## Components

| Component | Kind | Model | Status |
|---|---|---|---|
| Job queue, session runner, cache, usage ledger | Code | — | Built |
| Agent backend (Claude subscription via Agent SDK) | Code | — | Built; live runs pass |
| Source registry + config (`lexarena/sources/`, `config/sources.yaml`) | Code | — | Built: eval/live modes, generic JSONL DBs, custom types, web scoping (checked live) |
| Unspoiled reader (`public_db.py`) | Code | — | Built (validates against the schema) |
| Public case DB schema, validator, JSON Schemas, example | Code | — | Built (`schemas/public_case.py`, `scripts/validate_public_db.py`, [schema/](schema/)) |
| Reference DB ingest (field mapping, normalise, dedup, statute IDs) | Code | — | Built: 2,696 cases (`python -m lexarena.ingest.build_reference`) |
| Search index | Code | bge-small-en-v1.5 (384 dims) | Built: BM25 + dense (`python -m lexarena.retrieval.build_index --dense`) |
| Law DB lookup / authority registry | Code | — | Stand-ins: law DB summaries (no bare text yet); SC seed (unverified, year only) |
| Research tools (`tools/research.py`) | Code | — | Built |
| Debate handler: 5-turn MVP, hash-chained transcript | Code | — | Built, THEMIS-LOCAL wired |
| Appellant / Respondent advocates | Agents | Sonnet | Built: record + research tools, proceeding framework (`agents/framework.py`) |
| THEMIS-LOCAL: extractor, Stage A, Stage B, revision | LLM call + code + LLM call | Haiku | Built |
| Rule engine + Z3 | Code | — | Built (`lexarena/rules/`; real-case fixtures pending) |
| Single-LLM baseline | LLM call | Sonnet | Built |
| Silver DB builder (reference → public case format) | Code | — | Built: 1,087 cases (`python -m lexarena.ingest.build_silver`) |
| Case Builder (judgment → gold public case) | Agent | Sonnet / Opus | Planned |
| THEMIS-GLOBAL (before bench) | Code + 1 LLM call | Sonnet | Built (`themis/global_.py`); tests not yet run |
| 3 judges | Agents | Opus (Sonnet if the weekly Opus cap binds) | Built (`bench/judge.py`); tests not yet run |
| Aggregator + order writer | Code + LLM call | Haiku | Built (`bench/aggregator.py`); tests not yet run |
| Evaluator, metadata baseline | Code | — | Built (`eval/`, `cli evaluate`); issue-level alignment planned |
| Reflection + lesson validator | Agent + code | Sonnet | Planned |

## Tool access by role

| Tool | Advocates | Judges | Reflection | Case Builder |
|---|---|---|---|---|
| `read_record`, `read_transcript` (built) | ✓ | ✓ | ✓ | – |
| `search_authorities`, `authority_status`, `get_provision` (built) | ✓ | ✓ | ✓ | – |
| `rules_*` (limitation, threshold, s.10A, s.9 notice, appeal timeline) (built) | ✓ | ✓ | ✓ | – |
| Web: official statute hosts (eval) / open search (live) (built) | ✓ | ✓ | – | ✓ |
| `recall_lessons`, private notes | own side | – | – | – |
| `read_ground_truth`, `propose_lesson` | – | – | train only | – |
| `pdf_search`, `pdf_read_page`, `validate_draft` | – | – | – | ✓ |

## Running

```
python -m lexarena.ingest.build_reference             # raw precedent dumps -> data/canonical/reference_cases.jsonl
python -m lexarena.retrieval.build_index --dense      # bge-small vectors -> data/index/ (one-off, ~40 min on CPU)
python -m lexarena.ingest.build_silver               # silver train/dev cases -> data/silver/ (no model calls)
python scripts/validate_public_db.py                  # check public_db/ before using it
python -m lexarena.cli smoke                          # 1 tiny Haiku call: login, tools, isolation, window state
python -m lexarena.cli enqueue debate --split train --run-id train1
python -m lexarena.cli run                            # work until the window is ~85 % full, then exit
python -m lexarena.cli run --wait                     # sleep through resets until the queue is empty
python -m lexarena.cli status                         # job counts, window state, failures
python -m lexarena.cli evaluate --run-id dev1 --split dev   # metrics vs sealed ground truth (no model calls)
LEX_MODE=live python -m lexarena.cli run              # live mode: open web search, MCP servers (no answer key)
```

- **Pacing.** Before each job the runner reads the usage ledger. If the window is rejected, nearly full
  (≥ 85 %), or the CLI has sent a limit warning, it stops between jobs.
- **Checkpoints.** A limit hit in the middle of a job puts the job back in the queue with its checkpoint
  intact. Completed steps are not re-run, and the cache makes any repeated call free.
- **API key.** `ANTHROPIC_API_KEY` must be unset. If it is set, Claude Code bills the API, so the backend
  refuses to start.
- **Own account only.** These runs are for the owner, on the owner's account. Do not share the login across a
  team (CLAUDE.md §7.4).
- **Measured cost.** About $1.5 API-equivalent per 5-turn debate with THEMIS-LOCAL (synthetic case, 2026-10-05).

## Changes from the original diagram

| Original | Version 2 | Reason |
|---|---|---|
| AgentRouter gateway; Opus, GPT-5, GPT-4o-mini | Claude subscription via Agent SDK; Haiku / Sonnet / Opus by role | Budget decision; paced to usage windows |
| Fixed databases | Config-driven sources; eval vs live mode | Works with any DB; web case-law search would leak outcomes in evaluation |
| LEX-P "Plaintiff" / LEX-D | Appellant / Respondent | The data is NCLAT appeals |
| Clerk State Machine on gpt-4o-mini | Orchestrator and reader in code | Deterministic, testable |
| Advocates as single LLM calls | Tool-using agents with role-scoped tools | They choose lookups; every step is traced |
| Z3 gate checks ₹1 Cr, s.10A, limitation | Rule engine checks claims; Z3 only for uncertain facts | The gate must not decide the merits |
| Retry ×3 via a "Lawyer Agent" | Same advocate revises; Stage A ≤ 3 attempts, then Stage B once on the final version | Authorship stays with the side; Stage B never checks text that will change |
| THEMIS-GLOBAL after the trial | THEMIS-GLOBAL before the bench; findings are a judge input | Judges see cross-turn problems; findings only, never a verdict |
| Evidence assumed available | Closed record from the judgments; invented exhibits fail | Exhibits are not public; prevents fabricated evidence |
| Precedent DB of "verified" ratios | Reference DB + verified authority table | Status is computed as of the cutoff |
| Pragmatist judge | Purposive / Commercial, legally constrained | Viability-based refusal is wrong in law |
| Judges on another vendor's model | Judges on a different Claude model | Only Claude is available; side-swap test measures bias |
| Scoring matrix | Issue-wise findings + majority label | A weighted opaque score can't be validated |
| Continuous learning feeds runtime | Train-only, validator-gated, frozen | Prevents test leakage |
