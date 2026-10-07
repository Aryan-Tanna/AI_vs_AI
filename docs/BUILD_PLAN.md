# Build plan

One step per session. Tick a step only when every "done when" item holds and I have seen the sample output.

## Phase 1: the base (no case from the 500 is touched)

- [x] **Step 0: Repository and config**
  - Build: repo layout from CLAUDE.md, `pyproject.toml`, ruff and mypy config, config loader (pydantic-settings) with `config/config.v1.yaml`, LLM client wrapper with logging and caching, docker-compose for MongoDB, Qdrant and Redis.
  - Done when: `pytest` runs; a test proves config values are read, not defaulted in code; the LLM client returns schema-validated JSON from a dummy prompt.

- [x] **Step 1: Schemas and access control**
  - Build: Pydantic models for every format in DATA_FORMATS.md and SPEC H; role-scoped repositories in `lexarena/storage/`.
  - Done when: tests show lawyers, THEMIS-LOCAL, THEMIS-GLOBAL and judges cannot read `case_ground_truth` or the other agent's private data, and the evaluator can read ground truth only after `VERDICT_RECORDED`. Ground truth lives in a separate database whose credentials are absent from agent, THEMIS and judge processes, and a test proves the shared credentials are refused by MongoDB itself (D-024).

- [x] **Step 2: Law DB loading**
  - Build: loader that validates every Law DB record, plus integrity checks (dangling `intersecting_statute_ids`, missing error codes); `get_statute(id, as_of)` honouring approved `temporal_overlay` rows.
  - Done when: a validation report lists every malformed or dangling record; `get_statute` hides sections not in force on a given date (tested with an approved sample row).

- [ ] **Step 3: Drafting tools for side collections**
  - Build: tooling that drafts `temporal_overlay` rows and `predicate_registry` entries into `review/` with source text, using two models and recording disagreements; a loader that accepts only APPROVED items; hash-based STALE detection.
  - Done when: I can approve or reject drafts in `review/`; a changed Law DB item marks its predicate STALE.

- [ ] **Step 4: Precedent DB to Qdrant**
  - Build: incremental ingestion from my JSON/JSONL as specified in DATA_FORMATS §2.
  - Done when:
    - the point count equals the valid record count, with point IDs from the derived `precedent_uid` and every ambiguous `precedent_id` reported (D-024);
    - 5 random payloads match the source exactly;
    - unresolved statute IDs are reported;
    - a date-filtered query never returns later decisions;
    - re-running ingestion changes nothing.

- [ ] **Step 5: Retrieval tools**
  - Build: `find_similar_cases`, `find_authority`, `get_precedent`, `get_record_item`, all enforcing the date cut-off and exclusion list server-side.
  - Done when: 5 hand-written queries return sensible results, which I review; exclusion and cut-off are covered by tests.

- [ ] **Step 6: Clerk**
  - Build: PDF cleaning, part routing, record building, neutral issue rewrite, pseudonymization, source-paragraph entailment check, two-model agreement, leakage scan, overlap check, extraction flags.
  - Done when: on 3 dev judgments, I compare the output with the judgment and find no invented fact, every fact has source paragraphs, and the agent view passes the leakage scan.

- [ ] **Step 7: Predicate engine and THEMIS-LOCAL layer 1**
  - Build: the expression-to-Z3 compiler, claim extraction into checklist-mirroring JSON, the audit (SPEC D1, D2), the limitation date-chain helper driven by overlay data.
  - Done when: a test suite of at least 30 arguments built from dev cases and precedents (honest, misstated, open-interpretation) gives the expected hard errors and warnings, and no honest argument is rejected. The honest arguments come from real counsel submissions in dev judgments, the misstated ones are mechanical mutations of them, and the false-rejection rate is reported (D-024).

- [ ] **Step 8: THEMIS-LOCAL layer 2 and outcome policy**
  - Build: citation tiers plus entailment, record fidelity, responsiveness, repetition (Redis), and the D8 outcome policy with retries.
  - Done when: a fabricated exhibit claim and an inverted holding are both caught; UNVERIFIABLE citations warn rather than reject; the first-attempt pass rate on honest test arguments is reported.

- [ ] **Step 9: Agents and session orchestration**
  - Build: LEX-P and LEX-D on one prompt template; the LangGraph session (8 alternating turns plus parallel closings); lesson retrieval for pinning; version stamping.
  - Done when: one dev case runs end to end; a diff of both agents' assembled inputs shows the same template and identical shared inputs, and every side-specific input (role line, party-status lessons, own opening positions and reliefs) is listed and within equal budgets (D-024).

- [ ] **Step 10: THEMIS-GLOBAL**
  - Build: contradiction detection from tracked claims; answered, conceded or ignored marking per opposing point; the audit report.
  - Done when: a planted contradiction in a test transcript is found; the report contains no ground-truth fields.

- [ ] **Step 11: Judges**
  - Build: persona prompts (drafted into `review/` for my approval), order-swapped scoring, aggregation, tie rule, validator with ID checks.
  - Done when: on dev sessions, swapping presentation order changes scores by less than the gap fixed in config before measuring (SPEC E1: 0.15), the full distribution of gaps is reported, and every reason cites valid IDs (D-024).

- [ ] **Step 12: Evaluator and reflection**
  - Build: post-verdict unseal, per-issue alignment, lesson extraction with provenance, rejection of base-rate lessons and lessons containing names, three-step dedup, weighting with decay.
  - Done when: lessons from 3 dev cases are general, typed and sourced, and contain no names; evidence-driven mismatches produce none.

- [ ] **Step 13: Run manager and reports**
  - Build: sequential runner in date order, dispute grouping for splits, memory snapshots, frozen-memory test mode, empty-memory baseline mode, ablation switches, metrics report.
  - Done when: a dry run over the dev set produces the full report, and test mode provably writes nothing to memory.

- [ ] **Step 14: Calibrate and freeze**
  - Build: calibration of thresholds and weights on the dev set only; `config.v1` frozen; tag `v1.0`; clear memory.
  - Done when: `docs/DECISIONS.md` records every calibrated value and how it was chosen.

## Phase 2: the 500 (only when I start it)

- [ ] **Step 15:** Clerk the cases in date order; I review each case before it runs.
- [ ] **Step 16:** Training and validation run, in sequence, frozen version, no tuning; bug fixes only, each with a version bump logged.
- [ ] **Step 17:** Test run on the last 100 with frozen memory, plus the empty-memory baseline and ablations.
- [ ] **Step 18:** Final report: per-issue and verdict alignment, learning curve, ablations, bias diagnostics, limitations.