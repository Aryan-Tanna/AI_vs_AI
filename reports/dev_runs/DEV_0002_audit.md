# DEV_0002 run audit (DEV2_E2E_1, 2026-10-11)

Case: an operational creditor appeals the NCLT's approval of a resolution plan that pays operational creditors nil.
Issues: I1, must a plan pay operational creditors something under s.30(2)(b)? I2, was the Adjudicating Authority justified in approving the plan?
Real outcome: **RESPONDENT** (appeal dismissed). Code 445cd33, config v1.

## 1. Result

| | Verdict | I1 | I2 |
| --- | --- | --- | --- |
| Real judgment | RESPONDENT | RESPONDENT | RESPONDENT |
| Bench | **PETITIONER (wrong)** | RESPONDENT (right) | split 1-1 |
| Single-LLM baseline | PETITIONER (wrong) | wrong | wrong |

- **Textualist:** PETITIONER. I1 for R; I2 for P: "the nil-liquidation premise is unproven on this record".
- **Purposivist:** RESPONDENT. I1 and I2 for R: "no positive s.30(2)(b) entitlement shown; commercial wisdom".
- **Proceduralist:** abstained. It put issue IDs (I1, I2) where statute IDs go, and did so again in its one revision.
- **How the verdict was reached:** the tie was broken by advocacy scores (P 0.89, R 0.81), as the config rule says. The verdict therefore rests on the secondary measure, not on the bench's legal reasoning.
- **Bench against baseline:** the bench beat the single-LLM baseline on issues (1 of 1 decided issues right, against 0 of 2), but not on the verdict.

## 2. Every THEMIS-LOCAL rejection, checked against the record

17 drafts for 10 turns: 7 drafts were rejected and 1 turn was published FLAGGED.

| Turn / attempt | Reason THEMIS gave | Check against the record | Verdict |
| --- | --- | --- | --- |
| T1 a1 (P) | "Company-T is an operational creditor" not in record | The parties list says Company-T: OPERATIONAL_CREDITOR, but the reviewer was never shown that list | **WRONG: a bug, now fixed** |
| T1 a1 (P) | "The AA held compliance because liquidation value was nil" | The record has no lower-order reasons (lower_order is empty), and the pleaded grounds don't say it either | Correct: invented |
| T1 a1 (P) | "The approval order simply accepts the nil-liquidation assertion" | Same as above | Correct: invented |
| T1 a1 (P) | "100% CoC approval" | F6 says only "approved by the CoC". F5 says there was a sole financial creditor, which implies 100% only by legal inference | **Doubtful** |
| T5 a1 (P) | ERR_REPEATED_ARGUMENT (similarity 0.954) | See section 3 | **Noise** |
| T5 a2 (P) | "The impugned order records only the nil-liquidation conclusion", "the F3 direction remains unaddressed", "order records no such consideration" | None of the order's contents are in the record | Correct: invented |
| T6 a1 (R) | ERR_REPEATED_ARGUMENT (0.953) | See section 3 | **Noise** |
| T6 a2 (R) | "On this record, both are nil" | C1 (liquidation value nil) is a contested fact, but was stated as established | Correct |
| T6 a2 (R) | "the CoC unanimously approved" | As with "100% CoC" above | **Doubtful** |
| T6 a3 (R) | ERR_REPEATED_ARGUMENT (0.962) | See section 3 | **Noise** |
| T6 a4 (R), **published FLAGGED** | "the remaining plan amount is only about INR 25.4 crore" | AM7 − AM5 = 28,45,47,000 − 30,50,206 = **INR 28.15 crore** | **Correct: arithmetic error** |
| T9 a1 (P) | "A 100% CoC vote cannot substitute the statutory floor" | Rejected only on the "100%" point | **Doubtful: probably over-rejection** |

Totals:
- **Correct:** 6 grounds, all invented descriptions of what the impugned order said, or a misstated figure.
- **Wrong:** 1 (the parties-list bug, fixed).
- **Noise:** 3 repetition rejections.
- **Doubtful:** 3 (the 100%/unanimous CoC point).

**The reviewer is also inconsistent with itself.** Turn 3 used "unanimous CoC approval" and was published without comment, while turn 9 was rejected for "100% CoC vote". The same claim got opposite treatment from the LLM reviewer.

**No made-up record IDs.** Every claim cited only record IDs that exist; the code check never fired. All ERR_FACT_NOT_IN_RECORD came from the LLM review.

## 3. Why there are flags now (compared with earlier runs)

- **Rejections are not new.** DEV_0004 had 8 rejected drafts and one FLAGGED turn too. DEV_0002 has more amounts (7 against DEV_0004's 2) and no lower-order reasons, which tempts lawyers to characterise the impugned order. Those characterisations were caught correctly.
- **The repetition check is unreliable.** Every turn of a side scores 0.91-0.96 similarity against its own earlier turns: same case, same issues, same record IDs. The hard threshold is 0.95, so it sits inside normal variation. Turn 8 passed at 0.950 while turn 5 was rejected at 0.954. Here it hit both sides (turns 5 and 6), so this case shows no bias, but each hit costs a lawyer call.
- **My changes did not cause flags.** D-100 only skips paid checks when a free check already rejects; D-102 changed extraction, which produced no hard errors here; D-103 affected the closings, and both passed.

## 4. Arguments

- **Law:** both sides stated s.30(2)(b) as the Law DB has it, "not less than the higher of liquidation value or plan distribution value under s.53 priority". Both judges did the same.
- **Facts:** all stayed within the record, apart from the rejected attempts above and the one flagged figure.
- **Back-and-forth:** THEMIS-GLOBAL marks every point as answered in the next turn, and nothing was ignored before the closings. The debate engaged properly.
- **Contradictions:** THEMIS-GLOBAL listed 3, all against the Respondent. They treat "liquidation value is nil, so nil is lawful" as contradicting the full two-comparator test. That is the same argument in short form, and the auditor's own instructions say a change of emphasis is not a contradiction. **Doubtful.** It lowers the Respondent's consistency score, and so feeds the tie-breaker that decided this case.

## 5. Judges

- **Textualist:** I1 is sound. On I2 it held the nil liquidation value "unproven" because the clerk recorded it as contested (C1). The real court accepted the plan.
- **Possible cause: the record.** If the judgment states the nil liquidation value as a finding or from the plan itself, the clerk's "contested" label tilts the case, as with DEV_0001. **Needs your clerk review of C1 against the judgment.**
- **Purposivist:** follows the real reasoning: a statutory floor, commercial wisdom and no positive entitlement.
- **Proceduralist:** produced no valid opinion in 3 of 3 runs (I-prefixed IDs, then IDs split into characters, then issue IDs as rules). This persona prompt and this model don't work together.

## 6. Cost (measured)

- **This case:** OpenRouter usage $1.468 → $1.733, so **$0.265** (session, baseline, evaluation, reflection).
- **DEV_0004 before today's changes:** about $0.50.
- **Reflection:** made no LLM call, because the case isn't marked reviewed. With the review it adds about $0.02-0.03.

Estimated share by call (from list prices; the real bill was about 35% lower):

| Call | Share |
| --- | --- |
| Lawyer drafts | 43% |
| Layer-2 review | 15% |
| Entailment | 14% |
| Judges | 13% |
| Strategy | 5% |
| Auditor | 4% |
| Extraction (reasoning off) | 3% |
| Baseline | 2% |

## 7. Decisions needed

1. **Repetition hard check.** Make it a warning on all turns, since it's noise at 0.95 with this embedder, or replace it with a claim-overlap measure. **Recommend: warning.**
2. **Proceduralist.** Rewrite its persona prompt or move the judges to another model. Until then every verdict comes from 2 judges, and ties fall to advocacy scores.
3. **Ties.** Two deciding judges tie often, so either let a tie stand as UNSTABLE instead of using advocacy scores, or restore two orders per persona (D-093 cut it to one).
4. **"100% / unanimous CoC" claims.** Is it fair to count these as not in the record when there is a sole financial creditor? This is a legal-inference question for you.
5. **Clerk review of DEV_0002's C1 (nil liquidation value).** Check whether it really is contested in the judgment.
