# PILOT_A running notes (Claude Code, from 2026-10-18)

Run: `PILOT_A`, mode LEARN, `--allow-draft-personas` (personas DRAFT, Proceduralist STALE). Cases in decision-date
order: DEV_0008 (NCLAT 2022-05-18), DEV_0009 (SC), DEV_0010 (SC), DEV_0007 (SC 2026-01-15). Memory empty at start
(lawyer_memory 0, judge_memory 0). Viewer: http://127.0.0.1:3005/session/<session id>.

Owner's instruction (2026-10-18): clerk through DEV_0017 only, then stop splitting and reviewing; focus on the
completed cases and keep notes as they run. Cases DEV_0012 and DEV_0014-0017 get the automatic leak scans only, not
a full split review.

## DEV_0008 — session DEV_0008_PILOT_A_4c092b

Status: COMPLETE through evaluation; reflection running at the time of writing.

**Result.** Bench 3-0 RESPONDENT (Textualist, Purposivist, Proceduralist; both orders each, no abstention; the
Proceduralist needed one revision) = real outcome RESPONDENT. Issues: I1 aligned, I2 not (bench PETITIONER on the
information-utility deemed-authentication issue, real RESPONDENT), I3 aligned: issue alignment 2/3. The single-LLM
baseline gave exactly the same calls (overall RESPONDENT, I2 PETITIONER), so on this case the debate added nothing
measurable over one model reading the record. THEMIS-GLOBAL: rebuttal depth LEX-P 0.84 (15 of 18 opposing points
answered, 2 conceded, 1 ignored), LEX-D 0.95 (13 of 14); one contradiction in LEX-P's 73 tracked claims. The auditor
wrote 41,787 output tokens in one call (reasoning). Personas ran as DRAFT (`--allow-draft-personas`).

**What works**
- Every turn is grounded: each cites 8-11 record IDs and 4-8 precedent IDs; statutes cited by ID from turn 5.
- Lookups answered (statute text, authority search, similar cases) and added to the asking side's memory.
- THEMIS-LOCAL caught one real overstatement: LEX-D turn 2 said the IU e-mails "went to both owner-directors"
  (the record says only that they went to addresses belonging to directors) -> ERR_FACT_NOT_IN_RECORD, revised,
  passed on attempt 2. No other hard error in 8 turns: no sign of over-rejection.
- Precedent cut-off held for the one 2022 precedent cited (2022_NCLAT_CHE_117, decided 2022-01-03, before
  2022-05-18).

**Problems seen**
1. **Speed: about 1.5 hours a case.** The verifier (Qwen 3.8 Flash) writes 8k-19k output tokens per Layer2Review
   and up to 16.5k per EntailmentBatch, nearly all reasoning, on 1k-4k inputs; single calls take 100-257 s.
   Cost is fine ($0.175 at turn 5, on track for ~$0.40), time is not: 10 cases is about 15 hours. Lever: reasoning
   effort for the verifier (Q-034; S-012 proposes the A/B). Your decision; not changed mid-run.
2. **Repetition climbs and the lawyers stop researching.** LEX-P's similarity to its own earlier turns: 0.91 (t3),
   0.94 (t5), 0.95 (t7) — warnings only (no rejection, as intended since R-037), but the argument stalls on the same
   three points. LEX-P asked no lookups after turn 1; LEX-D re-asked for IBC_2016_SEC_5 in turn 8, which it already
   held. Suggests the lawyer prompt should show which authorities are already held and push new material in
   rebuttals.
3. **"OPENING:" header in rebuttal turns.** LEX-D's turns 2, 4, 6 and 8 all start "OPENING: ... REBUTTAL: ...",
   including rebuttals. Cosmetic, but it shows the lawyer prompt's section labels leaking into the speech.
4. **WARN_PREREQUISITE_UNADDRESSED on every LEX-D turn** (Law DB checklist items of s.7 not addressed). Noise at
   this rate; check whether the checklist mapping expects items a respondent need not argue.
5. **Statutes return as "(UNVERIFIED)"**: the Law DB entries the lawyers look up are unverified records, as known
   (no lawyer review yet).

## Clerk notes from this pilot (for the 500)

- Leaks found in triage and redacted in place (D-129): e-mail addresses (DEV_0008), a project name with the group's
  name (DEV_0009), registration numbers written without "No." (DEV_0007, DEV_0011). Checks extended (D-128, D-132).
- Another proceeding's dates labelled as this case's key dates (DEV_0013, D-133): the agent-view prompt should
  say key dates are this proceeding's own.
- Overlap check over-excluded 65 precedents on DEV_0010 ('asset reconstruction' as name words, D-130).
- Gemini free tier: 3.8 Flash quota spent by 09:17 UTC; repair round looped on DEV_0012. DEV_0012-0017 clerked by
  Claude agents through the handoff (D-127, D-131), marked CLERKED_BY_CLAUDE.

## Clerk phase closed (2026-10-18, owner: "clerk till DEV_0017 only")

| Case | Clerked by | Review | Probe | Notes |
| --- | --- | --- | --- | --- |
| DEV_0007 | Gemini (earlier) | Claude triage (note file) | NOT_IDENTIFIED | 3 registration numbers redacted (D-129, D-132) |
| DEV_0008 | Gemini 3.8 | Claude triage | NOT_IDENTIFIED | 2 e-mail addresses redacted |
| DEV_0009 | Gemini 3.8 | Claude triage | IDENTIFIED | "IREO" project name redacted; report apart |
| DEV_0010 | Gemini 3.8 | Claude triage | NOT_IDENTIFIED | 65 precedents over-excluded (safe direction) |
| DEV_0011 | Gemini 3.8 | Claude triage | NOT_IDENTIFIED | court number without "No." redacted; F9 wrong date caught by entailment and repaired |
| DEV_0012 | Gemini names/routing + Claude extraction | — | — | BLOCKED: source paragraphs of 8.9k-10.8k chars exceed Groq's 8k-token request with the 4,096 cap (my D-130 change); needs a batching fix |
| DEV_0013 | Gemini names/routing + Claude extraction | Claude triage | IDENTIFIED | borrower's CIRP dates dropped as key dates (D-133) |
| DEV_0014 | Claude | automatic scans only | NOT_IDENTIFIED | |
| DEV_0015 | Claude | automatic scans only | NOT_IDENTIFIED | no key dates stated for this proceeding |
| DEV_0016 | Claude | automatic scans only | NOT_IDENTIFIED | no key dates; second appellant unnamed |
| DEV_0017 | Claude | automatic scans only | IDENTIFIED | hyphen-joined real name in source P2 (not in agent view); fixed D-136; a bid-bond amount left out (digits and words disagree) |

Handoff lessons: the shared prompt folder let one agent answer another case's prompt (deleted within a minute; the
consumed answer was verified to be the right case's); `clerk run --handoff` now lists only its own prompt (D-134).

**Lessons written by DEV_0008's reflection** (first lessons in an empty memory): 5 lawyer lessons (3 for
FINANCIAL_CREDITOR, 2 for SUSPENDED_DIRECTOR) and 1 judge lesson. All general; no names, pseudonyms or base rates.
Watch: the judge lesson restates the court's holding on deemed authentication under the Information Utilities
regulations ("Regulation 21(3)"), which is not in the Law DB, so the rule it teaches is not traceable to verified
statute text (R-035 date scope applies too). PILOT_A was stopped after DEV_0008's reflection (DEV_0009 had just
started on the old prompts; its partial session is abandoned).

# PILOT_B (from 2026-10-18 ~11:20 UTC)

Same LEARN memory as PILOT_A (6 lessons from DEV_0008), D-135 prompts and checks. Nine cases in date order:
DEV_0009, DEV_0010, DEV_0011, DEV_0013, DEV_0007, DEV_0014, DEV_0015, DEV_0016, DEV_0017. Expected ~1.5 h and ~$0.45
a case. Watch: repetition similarity per turn, lookups after turn 1, "OPENING:" labels, prerequisite warnings only at
closings, lessons pinned at session start.

## Repetition: read by Claude, turn by turn (owner asked for a check by reading, not only the metric)

**DEV_0008 (old prompts): real repetition, a mutual loop.** From turn 3 every turn re-argues I1, I2, I3 in the same
order with the same record IDs (F2, F6, EX-4, F7, C2) and mostly the same authorities. LEX-D ends turns 4, 6, 8 and 10
with an almost identical "CLOSING: I1 ... I2 ... I3 ... Dismiss the appeal and uphold ..." block; LEX-P's I3 paragraph
("we do not say the suit is an automatic bar ... the AA had to decide it, not assume/infer it") recurs in turns 3, 5, 7
and 9. New material per turn is thin (turn 5: one precedent on account entries; turn 6: no pre-existing-dispute bar
under s.7; turn 8: no share-subscription document). They do engage (each turn opens on the other's last point); they
run out of material. Structural cause: three narrow issues and a small record (9 stipulated, 2 contested, 4
exhibits) are exhausted by turn 4, but the schedule asks for 8 rounds.

**DEV_0009 (D-135 prompts): a debate that moves.** No part labels. Each turn takes the opponent's newest point and
adds something: R4 "your own date places the claim after CoC approval"; P5 "CoC approval is not the cut-off, s.31
binds on AA approval"; R6 "s.31 binds the plan as submitted, it cannot reclassify" + 3 new precedents; P7 "18.4(xix)
cited only to expose the category error" + 1 new precedent; R8 + 2 new precedents. Both say "I have nothing new on
C1" instead of re-arguing it; the petitioner's closing opens "I will not repeat the record". The hearing narrows to
the decisive question (CoC vs AA approval as the cut-off; clause 18.4(xi) vs 18.4(xix)). Core positions are still
restated, as advocacy does (my estimate ~30%, against ~70-80% in DEV_0008). All 2025 precedents cited were decided
before the case date (2025-09-09). Possible identifier left in DEV_0009's record: "a Hamlet plot" (likely a project
name); the case is already reported apart (probe IDENTIFIED).

Option if loops persist on small records: let a side "rest" (a one-line turn) when it has nothing new, or scale the
number of rebuttal rounds to the record size. Both change the turn schedule (an INTENT choice): owner's decision.

DEV_0009's first PILOT_B attempt failed after its 10 turns: the THEMIS-GLOBAL auditor reasoned to its 65,536-token cap
with no answer (D-138: reasoning_effort medium). PILOT_B is FAILED by design (a learning run never skips a case);
the same nine cases run as PILOT_C, and DEV_0009's hearing replays from the cache.

## DEV_0009 (PILOT_C) result

Bench PETITIONER = real PETITIONER. I1 aligned, I2 not (bench RESPONDENT, real PETITIONER). Single-LLM baseline also
PETITIONER. Sentence-level self-repetition: LEX-P 8%, LEX-D 21% (DEV_0008 on old prompts: 37% and 36%). Whole-turn
similarity is ~0.90 even between opposing sides (0.899 here, 0.908 on DEV_0008), so it cannot measure repetition.
Reflection paused once on an upstream rate limit (Qwen via OpenRouter); resumed.

## Upstream rate limits (2026-10-18 evening)

Qwen 3.8 Flash on its pinned host (Alibaba, via OpenRouter, `allow_fallbacks: false`) returned "Provider returned
error" rate limits three times (reflection 15:35, verifier 18:28, extractor 18:39 UTC). The OpenRouter key itself is
fine ($5.12 of its $50 limit). Not switched to other hosts mid-pilot: another host can serve another quantization,
which would change THEMIS between cases. A resumer waits 20 minutes and resumes after each rate-limit pause (12 tries
at most; log reports/dev_runs/resume_loop.log). DEV_0011 re-runs from turn 1 because its opening prompt changed (D-140).
DEV_0010 result: bench RESPONDENT = real; single-LLM PETITIONER (wrong); first case where the bench beat the baseline.

## Claude's full audits (2026-10-19 night; owner: "verify all the arguments, all the thinking, everything")

Method per case: every published turn, every THEMIS check (each attempt and its reasons), every lookup and answer,
all six opinions, the verdict, the transcript audit and the lessons, read in full; every model's hidden reasoning
scanned by script (attempts to identify the real case, outside law, real party names from the source title, loops)
with every hit read; and an independent no-LLM cross-check of every record ID, statute, precedent (exact UID and
date before the case) and every date and amount in a factual claim against its cited record items.

Cross-check, DEV_0008 to DEV_0011: 510 lawyer claims, 394 precedent citations, 179 statute citations; 0 bad record
IDs, 0 statutes outside the Law DB, 0 precedents decided on or after the case date, 0 dates or amounts missing from
their cited items. One citation by bare precedent ID (DEV_0009 T2) is ambiguous: precedent IDs are not unique in the
precedent DB (2018_NCLAT_DEL_57, 2020_NCLAT_DEL_513, 2020_NCLAT_DEL_1005, 2024_NCLAT_DEL_197 each hold two different
judgments; 2020_NCLAT_DEL_1003, 1004 and 1005#371d... are the same judgment three times). The system resolves only
exact UIDs, so a bare ID fails safe (unverifiable, never the wrong judgment). Owner's data to clean.

Found and fixed: D-141 (THEMIS false rejection of a party's own relief, DEV_0010 T7); D-142 (judges reasoning from
remembered law and trying to identify the real case: DEV_0008 Purposivist, DEV_0010 Textualist and Proceduralist,
DEV_0011 Textualist); D-143 (DEV_0010's Proceduralist named the real appellant in its reasoning: the case is moved
to the memorised group although the clerk's probe said NOT_IDENTIFIED; the probe under-detects).
Seen, not changed: retrieval returns off-topic precedents for some queries (word match on "threshold"); DEV_0011 T5
THEMIS called a loose description of two precedents "the opposite" (borderline strict; the revision passed);
DEV_0010 verdict right for different reasons (issue alignment 0/2); the Textualist's overall result flipped with the
order in DEV_0010 and it abstained as designed.

## DEV_0011 (PILOT_C) result

Real outcome MIXED (no verdict comparison, by design). Bench PETITIONER 2-0 (Purposivist abstained); issues 2/2
aligned (I1 RESPONDENT, I2 PETITIONER). Single-LLM baseline PETITIONER. **Claude's mistake: DEV_0011 was scanned and
redacted but never marked `clerk triage`, so reflection wrote no lessons ("neither owner-reviewed nor accepted
triage"); reflection runs once per session, so its lessons are lost.** Marked afterwards; every later case was
checked and is marked. Reasoning scan: the Textualist asked itself "which is the correct outcome? let's think about
the actual case" and guessed another company's case; no real party named (judge prompt v4; v5 forbids this).
DEV_0011 full read: a sharp hearing on whether an NCLT order made in a registration-stage (Rule 63) appeal can be the
statutory notice to cure, plus an unframed limitation point that all three judges rightly declined to decide.
THEMIS: 2 drafts rejected, both over-strict: T5 called a loose description of two precedents "the opposite"; T6 was
rejected for "F5 records only that..." (F5 also says "subject to costs") and for "the only notice and order" where
F9 names a notice of 10.09.2023 and F3 one of 10.10.2023 -- a date inconsistency inside the judgment itself (the clerk
had flagged it). Revisions passed. Bench: Purposivist's I2 and overall flipped with the order (abstained as
designed); 2-0 PETITIONER.

THEMIS rejection tally so far (DEV_0008-0011): 6 rejected drafts; 1 real error caught (DEV_0008 T2), 1 clear false
rejection (DEV_0010 T7, fixed D-141), 4 over-strict or borderline (DEV_0011 T5, T6x2 on one draft, and the "only"
pattern). Calibration item after the pilot: the fidelity reviewer treats "only"/exclusive wording and source-internal
inconsistencies as hard errors.
Bench order bias: in DEV_0010 and DEV_0011 one judge's result flipped with presentation order and both times the side
presented FIRST won (primacy on close questions). Abstention removed both, so no verdict changed; the hearing
metrics' first-presented-wins count tracks it.

## What THEMIS let through: independent second check (DEV_0008-0011)

Method: a separate Claude agent (another model family from THEMIS's Qwen) judged every PUBLISHED claim against the
case material and the cited precedents' ratios; Claude then verified every flag against the source before counting it.
| Case | Claims | Supported | Statute-only (not checkable) | Confirmed misses | Notes |
| --- | --- | --- | --- | --- | --- |
| DEV_0008 | 134 | 129 | 4 | 1 overstatement | T1: "the record does not show ... an interest stipulation", but F6/EX-1 show the IU loan "at a 14 percent rate of interest"; later turns corrected it themselves |
| DEV_0009 | 121 | 116 | 4 | 0 | the reviewer's one flag (T4 "the Appellants' own case treats 07.02.2020 as operative") is borderline: the appellant had conceded it "for argument" in T3, which the packet did not include |
| DEV_0010 | 138 | 121 | 12 | 2 precedent misattributions | Prafulla Gadge (2022_NCLAT_DEL_498) is about the 24.03.2020 Section 4 Rs 1 crore notification; the petitioner used it for the 2019 Ordinance's allottee threshold. THEMIS: T05-C2 and T07-C17 SUPPORTS (missed); T03-C6 and T09-C14 NOT_ADDRESSED (warned). Swaminarayan (2025_NCLAT_DEL_885) stretched by the respondent (borderline). The bench was not misled: it decided I2 against the petitioner and one opinion named the mismatch |
| DEV_0011 | 117 | 112 | 5 | 0 | F9 dates the notice 10.09.2023, F3/EX-1 10.10.2023: an inconsistency inside the judgment, which the agents themselves noticed |
Totals: 510 claims, 0 invented facts, 0 invented precedents or later precedents (cross-check), 3 confirmed misses
(1 overstatement, 2 misattributions; about 1 in 170). Why: THEMIS's precedent check asks for the ratio's words only
when it says CONTRADICTS (entailment.v1: "For SUPPORTS and NOT_ADDRESSED give ratio_quote: ''"), so a SUPPORTS
verdict needs no evidence and a surface match ("enhanced threshold ... after notification") can pass. Only a
contradiction is a hard error by design (SPEC D8, verify-don't-obstruct). Calibration proposal for after the pilot:
require the supporting passage for SUPPORTS too, and treat SUPPORTS without one as NOT_ADDRESSED.

## DEV_0013 (PILOT_C) result

Bench RESPONDENT 3-0, unanimous in both presentation orders, no abstention; both issues RESPONDENT. Real outcome
RESPONDENT on both issues: verdict and 2/2 issues aligned. Single-LLM baseline RESPONDENT. Every opinion cites the
guarantee section and two precedents with record IDs; four opinions used their one revision.
THEMIS (old prompts, before D-145): 3 drafts rejected, same pattern: two said an exhibit "contains no" clause where the
record lists only what it does contain (defensible: nothing else is known; "the record shows no such clause" passes),
one rejected "the documents are admitted" (borderline strict: exhibits are presumed genuine).
Cross-check: 142 claims, 60 precedent and 53 statute citations, 0 problems (IDs, dates, future precedents). No case
name in any published turn or opinion outside the precedents served.
Independent check of what THEMIS passed (142 claims): 119 supported, 20 statute-only; flags verified by Claude:
- T8 RESPONDENT "the second [issue] was not reached": WRONG; the lower order says the NCLAT decided its second issue and
  "nonetheless dismissed the appeal on its first view". A real THEMIS miss; not decisive (judges decided I1 on the
  instrument's text).
- T6 RESPONDENT cites a s.60(5) summary-jurisdiction ratio for s.7: an analogy, borderline, not a clear misattribution.
- T9 PETITIONER "triggered by default, not by a prior demand": the cited ratio says liability is "triggered upon
  default" but also that formal invocation is a sine qua non (in the personal-guarantor rules); partly supported,
  borderline.
Name scan: flagged a bank party; false alarm (its name was in served precedent titles); fixed D-147.
Lessons: 6 written (4 creditor, 1 debtor, 1 judge), strategy only, no names or figures, law named only indirectly;
L-01 says "request the document", which a closed record does not allow (R-050).
DEV_0011 THEMIS replay on the D-145 prompts: planted errors 3/3 caught; T6 over-strict rejection gone; T5 still
rejected (borderline, unchanged).

## DEV_0007 (PILOT_D, first case after D-145..D-147) result

Bench RESPONDENT 3-0 in both orders, no abstention; real RESPONDENT; both issues aligned (LAW-driven). Baseline
RESPONDENT. Probe NOT_IDENTIFIED, name scan clean.
THEMIS: 1 draft rejected (T4 RESPONDENT "short payment [F8]": F8 gives amounts paid, not the agreed instalment, and
C1 contests default) -- correct. Cross-check: 133 claims, 131 precedent and 52 statute citations, 0 problems.
Independent check (133 claims): 114 supported, 17 statute-only, 0 invented facts, 0 misattributions, 2 OVERSTATED
(verified by Claude): T5-C3 and T7-C1 PETITIONER turn Kotak Mahindra's ratio ("where the creditor's acceptance
expressly reserves the right ... revive") from a sufficient condition into a required one and drop its post-
limitation framing. A THEMIS pass that a stricter reviewer would note; not decisive (the petitioner lost; no
opinion relied on it). Borderline analogies (Rule 11, allottee threshold) noted, not flagged.
Lessons: 5 written, strategy only. Reflection rejected one candidate as "names a party ('commercial')": an ordinary
word that is part of a real party name; the name filter is over-strict on common words (calibration item).
