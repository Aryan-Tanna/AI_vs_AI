# Critical review of the code and architecture after DEV_0002 (2026-10-11)

Scope: bias between sides, order bias, and logic that can produce a wrong or unfair result.
Evidence: DEV_0001, DEV_0002 and DEV_0004 runs, the code at 72e8830, and the DEV_0002 judgment PDF.
Every fix proposed here is justified by mechanism, not by which side the real court favoured. I have not tuned anything towards outcomes.

## Track record so far (be honest about it)

| Case | Bench | Real | Single LLM |
| --- | --- | --- | --- |
| DEV_0001 | PETITIONER (unanimous) | RESPONDENT | PETITIONER |
| DEV_0004 | RESPONDENT 2-0 (one judge abstained) | PETITIONER | RESPONDENT |
| DEV_0002 | PETITIONER (1-1 tie, broken by advocacy score) | RESPONDENT | PETITIONER |

0 of 3 verdicts are right, for both systems. Three cases prove nothing statistically, but the causes below are structural and would hurt any number of cases.

## A. The bench (highest impact)

### A1. Each judge decides once, so order bias is neither cancelled nor measured
- **What happens:** since D-093 each persona sees one presentation order. With 3 personas and 2 orders, two judges always read the same side first.
- **Why it matters:** a primacy or recency effect therefore tilts every case towards whichever order got two judges. The order-swap check (`abstain_on_order_swap_disagreement`, `order_swap_gap`) can never fire; in `fold_judge` the single-order branch skips it.
- **Conflict with INTENT:** INTENT.md says the judges decide "twice with the sides swapped". D-093 overrode that.
- **Fix:** `orders_per_persona: 2`. Cost: about 3 more judge calls, roughly $0.05 per case at Flash.

### A2. A tie is decided by advocacy score, which measures style, not law
- **What happened:** in DEV_0002 the Purposivist ruled RESPONDENT on both issues, yet scored the Petitioner higher on every dimension. Both judges preferred the Petitioner's advocacy, so the tie-break gave the verdict to the Petitioner, against one of the two judges' own legal findings.
- **A second problem:** the verdict was DECIDED while the decisive issue (I2) was UNSTABLE, which is incoherent.
- **Fix:** an even split becomes UNSTABLE, reported apart. Advocacy stays a secondary measure. D-048 named advocacy as the tie-break, so this is your call.

### A3. Ties only exist because a judge fails
- **What happens:** with 3 valid opinions a split is impossible.
- **The Proceduralist produced no valid opinion in 3 of 3 runs:**
  - I-prefixed IDs;
  - IDs split into characters;
  - issue IDs given as statute IDs.
- **Across all runs:** 4 of 9 judge opinions were invalid or abstained.
- **Fix:** review the Proceduralist persona text, plus one of:
  - a stronger judge model (Qwen 3.8 Max, which you moved off for cost in D-088);
  - a structured-output repair for the issue-ID mistake.

### A4. Judge reasoning quality
- **What happened:** in DEV_0002 the Textualist held the nil liquidation value "unproven".
- **What the court did:** it computed nil itself from the same figures the agents had (judgment para 11: the sole financial creditor cannot recover its own claim, so operational creditors get nil in liquidation).
- **Why this is the model, not the record:** the record had the numbers, and the Respondent argued exactly this.
- **Why it matters:** a weak judge model is the ceiling on accuracy. Flash judges are cheap but have not yet produced a correct verdict.

## B. THEMIS-LOCAL

### B1. Repetition hard check is noise
- **Measured:** same-side turns in one case score 0.91-0.96 similarity whole-text, on bge-small. The threshold is 0.95, so turn 8 passed at 0.950 while turn 5 was rejected at 0.954.
- **Cost:** 3 rejections in DEV_0002 and 5 in DEV_0004, each costing a lawyer call.
- **Fix:** warning on all turns, or a claim-level overlap measure.

### B2. The fidelity reviewer over-rejects, and inconsistently
- **Measured:** 3 rejections in DEV_0002 for "100% / unanimous CoC approval".
  - The record has a sole financial creditor, and the judgment itself says it is "the sole Member of the CoC".
  - The reviewer's prompt already says not to report inferences from recorded facts, so the model ignored its instruction.
  - The same claim ("unanimous CoC approval") passed in turn 3.
- **Mechanism:** a hard error rests on one Flash call's self-reported confidence (≥ 0.7), and self-reported confidence is poorly calibrated.
- **Fix: confirm before rejecting.** When the review would raise a hard error, a second, narrow call asks only "is this exact statement stated in, or a direct inference from, these record items?". Reject only if both agree.
  - Cost falls only on would-be rejections.
  - Honest drafts gain the most.

### B3. Fixed today
- **D-104:** the reviewer was not shown the parties.
- **D-100 to D-103:** tokens and closings.

## C. Lawyers

### C1. The lawyers argue against condensed summaries of the debate
- **What happens:** `session.lawyer_input_tokens: 6000` is a free-tier Groq relic (R-011: Groq rejected over 7,000). Measured input per DEV_0002 draft plateaus at 5,700-7,300 tokens from turn 2. From early in the debate, older turns, including the lawyer's own, reach it only as claim ledgers.
- **Likely effects:** repetition (it cannot see what it already said in full), shallower rebuttal, and noisier retries.
- **Why this is safe to change:** DeepSeek V4.1 Flash has no such limit.
- **Fix:** raise to about 20,000. Cost: about +$0.05 per case of input. It is symmetric for both sides.

### C2. Symmetry is fine
Both sides use the same class, model, templates, budgets and retry cap. Only the role line, the side's own lessons and its private plan differ (`agents/lawyer.py`). The turn order is P first, D gets turn 8, and the closings are parallel, which is balanced as designed.

## D. THEMIS-GLOBAL

### D1. The contradictions it shows the judges are unreliable
- **What happened:** all 3 contradictions in DEV_0002 were against the Respondent, and all 3 were the same argument in short form, which the auditor's own prompt excludes.
- **Why it matters:** they reach the judges as notes, and the judges' consistency scores for the Respondent were lower. That fed A2.
- **Fix:** show the judges only the points map, until contradictions are confirmed by a second pass or by code.

## E. Clerk and evaluation
- **DEV_0002's record was fair.** I checked the PDF: C1 (nil liquidation value) is the court's own computation from figures that are in the record. The clerk also left out the all-operational-creditor totals in the impugned order's table (₹6.53 crore claimed, ₹3.61 crore admitted), which is minor.
- **The memorization probe looks weak.** It said NOT_IDENTIFIED for DEV_0004, a well-known 2021 Supreme Court case (TCS v. Vishal Ghisulal Jain).

## Recommended order (each needs your go-ahead; all are mechanism fixes)

| # | Change | Cost per case | Decision |
| --- | --- | --- | --- |
| 1 | Restore two orders per judge (A1) | +$0.05 | Reverses D-093 |
| 2 | Tie becomes UNSTABLE, not an advocacy win (A2) | 0 | Changes D-048 tie-break |
| 3 | Fix the Proceduralist; consider a stronger judge model (A3, A4) | +$0 to +$0.50 | Judge model choice |
| 4 | Repetition becomes a warning (B1) | saves | SPEC D8 |
| 5 | Confirm before a fidelity rejection (B2) | small, only on rejections | New mechanism |
| 6 | Lawyer input budget 6,000 → 20,000 (C1) | +$0.05 | Config |
| 7 | Judges see the points map, not unconfirmed contradictions (D1) | 0 | Changes D-078 |

After these, re-run DEV_0001, DEV_0002 and DEV_0004. The debate drafts change (C1), so this is not a cache replay; expect about $0.30-0.40 each. Then freeze v1.0 before the 500.
