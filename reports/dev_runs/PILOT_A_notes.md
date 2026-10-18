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
