# Handoff for Aryan: what Parth built (2026-10-08 to 2026-10-09)

Read this before the next session; then the new decisions D-070 to D-083 in `docs/DECISIONS.md`. Everything below is
on `main` as a fast-forward of 16 commits on top of `7d7443a` (nothing of yours was changed or lost). The step branches
(`parth/step-11-judges` ... `parth/step-09-session`) are pushed too, for reference.

## 1. What is on main now

All of Phase 1 Steps 8 to 13 exist, so a session can now run end to end. Each step follows the repo rules: tests
first, planted-bug tests, no literals, import boundaries, decisions logged.

| Step | What | Decisions | Shown by |
| --- | --- | --- | --- |
| schema | Bench verdict, issue-wise judge decisions, UNSTABLE, per-issue evaluation (additive; old documents validate) | D-070 | `tests/test_bench_schema.py` |
| 8 | THEMIS-LOCAL layer 2 + outcome policy: record fidelity, citation entailment, repetition, retries, FLAGGED | D-075 | DEV_0001: 6/6 honest pass first time, 3/3 mutations caught (`reports/step8_acceptance.md`) |
| 9 | Lawyers with a three-part knowledge base, private strategy phase, session orchestrator, `lexarena session run` | D-079 | `tests/test_session_orchestrator.py` (real stores, scripted models) |
| 10 | THEMIS-GLOBAL transcript audit (points answered, self-contradictions, held to the transcript) | D-076, D-078 | `tests/test_themis_global.py` |
| 11 | Judges: issue-wise bench, order-swap abstention, validator, layer-1 check of judges' stated law | D-071 | live pleadings-only trial on DEV_0001 (`reports/bench/`) |
| 12 | Evaluator, single-LLM and majority baselines, statistics; experience memory and reflection | D-072, D-077 | `tests/test_evaluator*.py`, `tests/test_reflection*.py` |
| 13 | Run manager: date order, resume, quota pacing, frozen-memory proof, reports | D-073, D-080 | `reports/step13_*.md` |
| viewer | Streamlit clerk-review page (`uv sync --group ui`; `streamlit run lexarena/ui/app.py`) | D-074 | `tests/test_review_viewer*.py` |

Tests at the last commit: 964 offline pass (171 skipped), 164 integration pass; ruff and mypy clean.

## 2. Needs your decision or approval

1. **Persona prompts (Q-031).** Three method-only prompts in `prompts/judges/persona_*.v1.txt`, DRAFT in
   `review/judge_personas/`. Read them, then `lexarena judges approve PERSONA --by Aryan`. Until then sessions need
   `--allow-draft-personas` and every judge decision is stamped unapproved.
2. **The schema change (D-070)** landed without the separate PR HANDOFF_PARTH §4 asked for, at Parth's request. It is
   additive; review it and say if you want anything changed.
3. **Choices open to change** (each is in its decision entry):
   - D-071 (4): "result follows findings" only when every one-sided issue finding upholds the same side.
   - D-071 (6): issues have no tie-break.
   - D-078: judges see THEMIS-GLOBAL's map of points and contradictions (never its scores), behind
     `judging.show_audit_notes`. This was Parth's direction; ablate it on dev sessions.
   - D-079: the orchestrator is plain Python, not LangGraph (a minor deviation from CLAUDE.md §8).
4. **Reflection (Q-032)** had no owner; Parth built it (D-077). Confirm or reassign.
5. Still yours from before: tick Steps 4, 6 and 7; the three limitation overlay drafts; the blocked s.4 one-lakh draft.

## 3. What changed in shared code (check before your next pull, if you have local work)

- `lexarena/schemas/`:
  - new `bench.py`, `evaluation.py`, `agent.py`, `reflection.py`, `run.py`;
  - `session.py` gains `judge_decisions`, `bench`, `case_seq` and `pinned_lessons` (defaults keep old documents valid);
  - `lesson.py` gains `last_reward`;
  - `config.py` gains the sections and keys below.
- `lexarena/storage/`:
  - `sessions.record_bench_verdict` (use this, not `record_verdict`);
  - `lessons.py` (Qdrant `lawyer_memory` and `judge_memory`);
  - `cases.index()`;
  - the factory bundles carry the lesson repositories;
  - policy: REFLECTION may read both memories (to deduplicate).
- `lexarena/llm/`:
  - `ModelConfig.reasoning_effort` (required; null except the lawyer's `low`, D-081), sent only when set;
  - the cache key leaves out unset optional fields, so your existing cache entries stay valid;
  - `GenerationRejectedError` retries Groq's `json_validate_failed` (D-083).
- `config/config.v1.yaml`:
  - new sections `evaluation` and `runner`;
  - new prompt references;
  - `judging`, `memory`, `session` and `themis_local` keys;
  - `session.max_turn_tokens` is now 600 (D-082).
- **If you have unpushed Step 8 to 10 work** in `lexarena/themis_local/`, `agents/`, `orchestrator/` or
  `themis_global/`: this main now contains Parth's versions of those packages. Compare before merging. Keep whichever is
  better and tell Parth; `layer1.py`, `audit.py`, `extract.py`, `predicates.py` and `limitation.py` are untouched.

## 4. State of the first live end-to-end run (DEV_0001)

Not finished yet. Four attempts each got further, and every stop was a free-tier limit or an output cap, not a logic
error:

| Attempt | Got to | Stopped by | Fix |
| --- | --- | --- | --- |
| 1, 2 | turn 1 | lawyer output cap (gpt-oss reasoning filled 2,048 tokens) | D-081, D-082 |
| 3 | turn 3 | Groq strict-schema 400 treated as permanent | D-083 |
| 4 | turn 7 | verifier output cap (`qwen3.8-27b` reasoning, layer-2 review) | **next, see §5** |

On the way, the pause and resume worked as designed: rate limits paused the run, and resuming replayed every finished
call from the cache. Groq accounts shared with other users ran out of their daily budget mid-session. One spare
account caps output tokens per minute at 1,000 (R-033).

## 5. Next steps

1. **Verifier output cap.** Give the verifier role a reasoning setting too, or size `max_output_tokens` per call type.
   Then finish the live DEV_0001 LEARN run:
   `lexarena run plan DEV_E2E_5 --mode LEARN --allow-draft-personas`, then `run go DEV_E2E_5 --skip-quota-check`.
   That gives the first real session, bench, evaluation against the judgment, and reflected lessons.
2. **Clerk more dev cases** (3 of about 30). Then run the Step 11 and 12 acceptance on real sessions: order-swap rates,
   reference validity, alignment against baselines.
3. **Measure session cost** (the SPEC G4 pilot). Replace the placeholders, including `runner.stage_requests` and
   `memory.confidence_step`.
4. **Ablation** of D-078's auditor's notes, plus SPEC G1's NO_THEMIS, NO_MEMORY and NO_EXHIBIT_CARDS.
5. **Paid keys before long runs** (R-014, R-033). Step 14 calibration on the Phase 2 models, then freeze v1.0.

## 6. Commands added

| Task | Command |
| --- | --- |
| One session end to end | `lexarena session run --case-id ID --run-id R --mode LEARN\|FROZEN\|EMPTY --case-seq N [--allow-draft-personas true]` |
| Runs | `lexarena run plan R --mode M [--allow-draft-personas] [--dry-run]`, `run go R [--skip-quota-check]`, `run status R`, `run report R` |
| Persona approval | `lexarena judges personas\|draft-personas\|approve P --by NAME\|reject P --by NAME --reason T` |
| Bench trial, baseline, evaluation, reflection | `lexarena judges trial`, `baseline single`, `evaluate session\|report`, `reflect session` |
