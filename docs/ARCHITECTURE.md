# LexArena architecture

This is the condensed architecture. Detailed rules, schemas and code sketches are in `docs/SPEC.md` (section letters are given in brackets).

## 1. Components

| Component | Job |
| --- | --- |
| Clerk | Turns a real judgment PDF into an agent-visible case and a sealed ground-truth record [A, H] |
| Retrieval tools | Date-filtered, exclusion-filtered access to statutes, precedents and the case record [B] |
| LEX-P / LEX-D | Advocate agents. LEX-P represents the party seeking relief; LEX-D opposes [I2] |
| THEMIS-LOCAL | One instance per agent, identical config. Verifies each draft before publication [D] |
| THEMIS-GLOBAL | Audits the full transcript before judging; never sees ground truth [E, I3] |
| Judges | Textualist, Purposivist, Proceduralist. Score advocacy per issue; the higher aggregate wins [E] |
| Evaluator | After the verdict, compares the session with the real judgment [G, I3] |
| Reflection engine | Writes typed, general lessons into the experience memories [F] |
| Orchestrator | LangGraph session graph; run manager that executes cases in date order and stamps versions |

## 2. Data stores and the knowledge base

The knowledge base has three parts:

- **Regulation memory:** the Law DB plus its side collections (`temporal_overlay`, `predicate_registry`).
- **Case library:** the precedent DB.
- **Experience DB:** the lawyer and judge lesson memories.

Agents never retrieve past session transcripts. Only distilled lessons carry across cases.

| Store | Written by | When | Read by | Never read by |
| --- | --- | --- | --- | --- |
| Law DB, `temporal_overlay`, `predicate_registry` (MongoDB) | Ingestion scripts, approved items only | Offline, between runs | Lawyers, THEMIS, judges, reflection (as of the case date) | — |
| Precedent DB (Qdrant: `facts` multivector + `ratio` vector, full record as payload) | Ingestion scripts | Offline, between runs | Lawyers, THEMIS, judges (date cut-off and exclusion list always applied) | — |
| `cases.agent_view` (MongoDB) | Clerk | Before the case runs | Lawyers, THEMIS, judges | — |
| `case_ground_truth` (MongoDB, separate credentials) | Clerk | Offline | Evaluator and reflection, after the verdict only | Lawyers, THEMIS-LOCAL, THEMIS-GLOBAL, judges |
| Published turns | Orchestrator | During the session | Both lawyers, THEMIS, judges | — |
| Private turn data (attempts, warnings, scores) | THEMIS-LOCAL | During the session | That agent's reflection only | Opponent, judges |
| Redis session memory | Each agent | During the session; cleared at the end | That agent and its own THEMIS-LOCAL | Opponent, later sessions |
| Lawyer experience memory (Qdrant) | Reflection | After the verdict | Lawyers whose party status matches, at session start | Judges, THEMIS |
| Judge experience memory (Qdrant) | Reflection | After the verdict | Judges | Lawyers, THEMIS |
| `sessions` (MongoDB) | Orchestrator, evaluator | During and after | Reflection, analysis | Any agent |
| Config (versioned YAML) | Me | Between runs only | Everything | — |

In test runs, both experience memories are read-only.

## 3. Case preparation (clerk)

1. Clean the PDF: strip page headers and footers, fix encoding.
2. Split it by judgment part and route each part [H0]:
   - **To the agent view:** header (pseudonymized), lower order, facts, issues, headline grounds, reliefs sought.
   - **To the sealed record:** full submissions with authorities, statutory analysis, precedent analysis, findings, conclusion.
3. Build the record:
   - stipulated facts (F);
   - contested facts with each side's version (C);
   - exhibit cards holding only what the judgment says each document contains (EX);
   - every amount (AM) and key date;
   - each item with its `source_paras`.
4. Rewrite issues as neutral questions. Generate fresh pseudonyms for every case.
5. Checks:
   - each fact must be entailed by its source paragraphs;
   - two models must agree on the extraction;
   - a leakage scan of the agent view;
   - an overlap check against the precedent DB, producing `excluded_precedent_ids`.
6. Log extraction flags (conflicting figures, missing tables). Never guess a value.
7. I review the output against the judgment before the case is used.

## 4. A session

1. The orchestrator loads the case and gives both agents identical inputs:
   - the record;
   - Law DB entries for the invoked statutes, as of the case date;
   - the same retrieval tools;
   - lessons for their party status, filtered by the case's statutes, then ranked by weight, within the same token budget.
2. Turns 1 to 8 alternate, LEX-P first. Turns 9 and 10 are closing statements written in parallel; they may answer turn 8.
3. Each draft passes the agent's THEMIS-LOCAL:
   - **Layer 1, claim extraction.** Claims are extracted from the draft. For each statute relied on, a JSON mirroring its `diagnostic_checklist` and `procedural_timelines` is built and checked against the Law DB entry plus the record's amounts and dates. Approved predicates are compiled to Z3 at runtime. Contested interpretations are parameters chosen by the argument, never fixed rules.
   - **Layer 2, LLM checks** (on a different model family from the lawyers):
     - citation tier (VERIFIED, REFERENCED or UNVERIFIABLE) plus an entailment check against the precedent's ratio;
     - every factual claim traced to a record ID;
     - responsiveness to the opponent;
     - repetition of the agent's own earlier turns.
   - **Outcome:**
     - PASS or PASS_WITH_NOTES: the draft is published;
     - REVISE: only for hard errors (SPEC D8), with the exact code and record ID fed back, up to the configured retry cap;
     - FLAGGED: published with the flag visible to the opponent and the judges.
4. THEMIS-GLOBAL audits the transcript: contradictions between tracked claims, which opposing points were answered or ignored, grounding and consistency.

## 5. Judging

- Each persona decides each framed issue twice, with the two sides presented in swapped order: finding, governing rule (statute or precedent ID), application to record IDs, conclusion, and the side whose position it upholds; then the overall result (D-048).
- A judge whose two decisions disagree abstains for that case; the abstention rate is reported.
- Judges see anonymous counsel labels and only FLAGGED hard errors. They use read-only tools, and every reason must cite record, statute or precedent IDs. THEMIS layer 1 rules check those references, with one revision; the validator confirms each judge's overall result follows from its issue findings.
- The verdict is the majority of the non-abstaining judges, with dissent recorded. Advocacy scores (accuracy, consistency, rebuttal, grounding; weights in config) are produced alongside, reported as a secondary measure, break a tie (rule in config), and feed reflection.

## 6. Learning

1. After the verdict, `case_ground_truth` unseals for the evaluator and reflection.
2. The evaluator records per-issue alignment, plus verdict alignment unless the real outcome is MIXED.
3. Reflection writes general lessons with provenance (issue IDs and source paragraphs) and no names or pseudonyms:
   - ADVOCACY lessons go to lawyer memory, keyed by party status and statutes;
   - LEGAL_RULE lessons go to judge memory;
   - PROCEDURAL_ERROR lessons are tied to error codes.
4. Mismatches caused by evidence the agents never had produce no lesson. Base-rate lessons are rejected.
5. Lessons are deduplicated by structured key, then embedding, then LLM confirmation. Their weight reflects confidence and decays with disuse. Lessons from case N are readable from case N+1.

## 7. Runs, splits, versions

- **Phase 1:** build and tune on the dev set only. Freeze as v1.0.
- **Phase 2:** feed the 500 strictly in sequence, in date order. Cases about the same dispute or corporate debtor stay in the same split. The last 100 are the test set: memory frozen, plus an empty-memory baseline and ablations.
- Every session stores git SHA, config version, Law DB snapshot, precedent DB snapshot and memory snapshot.
- Thresholds are recalibrated only between runs, under a new config version.

## 8. Built to grow

- **Law changes are data.** New amendments are `temporal_overlay` rows with effective dates and the date they key on. New sections become Law DB entries; sections not yet in force on a case date are hidden by `get_statute(id, as_of)`.
- **Predicates are data.** Each is an expression in `predicate_registry` with its source text. A new or changed Law DB item has no approved predicate (hash mismatch), so it is flagged for drafting, and until approved its checks go to the LLM layer.
- **Precedent ingestion is incremental.** Upsert by `precedent_id`, re-embed only when the content hash changes, and re-run the statute-ID integrity check.
- **Config holds every tunable value.** Splits and cut-offs are computed from dates.

## 9. Known limitations

- No legal expert review yet. Mitigations: only text-traceable rules are encoded; THEMIS is tested against real precedents; drafts are cross-checked by two models; cases whose law cannot be verified are set aside.
- The record comes only from what judgments say; documents the judgment doesn't describe are unknown.
- The models may remember famous judgments. Cases the model can identify are reported separately.