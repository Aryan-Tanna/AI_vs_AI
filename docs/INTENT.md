# Why I'm building LexArena, and what I care about

Written by me, for Claude Code. Read this as my voice: it explains what I want and why, so you can make the same calls I would when the spec doesn't cover something.

## The idea

Legal AI today answers questions in one shot and makes things up: fake citations, wrong thresholds, misread holdings. Real law doesn't work in one shot. It is adversarial: two sides argue, each attacks the other's weak points, and a bench decides.

I want a system where two AI advocates argue real Indian insolvency cases (IBC, NCLT and NCLAT) against each other, where every argument is checked against real statutes, real precedents and the real case record before anyone sees it, where judges score the advocacy fairly, and where the agents learn from every case so they argue better next time. No fine-tuning: learning happens through structured memory.

I chose IBC cases only, to stay narrow and deep.

## What success looks like

1. Agents argue real cases using only real law, real precedents and the real record.
2. Every argument is verified before it enters the transcript, and honest arguments pass.
3. Judging is fair to both sides, with no structural advantage for either agent.
4. Over hundreds of cases, the agents get measurably better on cases they have never seen, compared with the same system running with empty memory.
5. The system keeps working, without code changes, as I add law and precedents over the coming years.

## What I'm afraid of (design against these)

1. **Hallucination.** An agent inventing a fact, an exhibit's contents, a citation, or what a precedent held. Every claim must trace to something real.
2. **Bias.** One agent getting a better prompt, more memory, the last word, or a friendlier verifier. Judges favouring length, order or labels. Memory learning base rates like "creditors usually win".
3. **Leakage.** The real outcome reaching an agent, a verifier or a judge before the verdict, through the case text, the precedent DB, the memory, a connected case, or the model remembering a famous judgment.
4. **Over-rejection.** A verifier so strict that every argument gets rejected and retried. THEMIS should catch provable errors, not punish imperfect but honest arguments.
5. **Hardcoding.** Legal numbers or tuning values buried in code. Law changes; my DBs will grow; the code must not need editing when they do.
6. **Silent data errors.** A wrong fact extracted from a judgment quietly poisoning everything downstream.
7. **Fooling myself.** Tuning the system while looking at the cases I evaluate on.

## Choices I have made (don't reopen these without asking me)

- **Real cases, not moot problems.** The record each case uses is built from the real judgment. "Closed record" only means agents cannot add facts the real case doesn't contain.
- **Winner by advocacy score.** The side with the higher aggregate advocacy score from the three judges wins, with the debiasing guards in SPEC E1. The real outcome is used only after the verdict, for evaluation and learning.
- **LEX-P represents the party seeking relief** in the proceeding being simulated (the appellant in appeals). LEX-D opposes.
- **Frozen formats.** My Law DB and precedent DB formats stay as they are. The precedent DB has two vectors: `material_facts` (one sub-vector per section) and `ratio_decidendi`.
- **Z3 design.** For each statute an argument relies on, an extractor builds a JSON mirroring that statute's `diagnostic_checklist` and `procedural_timelines`. Z3 checks it against the real Law DB entry and the case's real amounts and dates. It checks whether the lawyer stated the law and facts accurately, never whether the case is winnable.
- **Judges:** Textualist, Purposivist, Proceduralist.
- **Turn schedule:** 8 alternating turns, LEX-P first, then two closing statements written in parallel. Five turns each.
- **Base first.** Build and tune on a dev set of judgments outside the 500, freeze, then feed the 500 one at a time in date order. The last 100 are the test set, run with frozen memory and compared with an empty-memory run.

## My constraints

- **No lawyer on the team right now.** Only encode legal rules traceable to statute or notification text, and I approve each one. Where something needs legal judgment, send it to the LLM layer with real sources, or set it aside and flag it. State the lack of expert review as a limitation.
- **The DBs will grow.** I will keep adding to the Law DB and the precedent DB for years.
- **I'm using you (Claude Code) to write most of the code.** I will review samples, approve legal drafts, and check clerk output against judgments.

## How I'd like you to work with me

- Be direct. If something I ask for would create bias, leakage, hallucination or hardcoding, tell me before doing it.
- Prefer simple, inspectable mechanisms over clever ones. I need to be able to explain every part to a review panel.
- Show me real outputs (actual JSON from dev cases), not just code.
- Ask when the spec is unclear, especially on anything legal.
- Keep `docs/DECISIONS.md` honest and up to date, so that a year from now I can see why each choice was made.