# Read before the pilot (written night of 2026-10-11/12)

I've built and committed everything you asked for before the pilot. All 1,115 offline tests and 166 Docker integration tests pass. Nothing has run against a live model since these changes; the first live calls are tomorrow morning.

## What's ready

1. **Money guard.** A run pauses before any stage that would take total spend past **$11** (counted from 12 Oct, across all pilot batches).
   - A paid model call with no price in the config also pauses the run, so a paid route can't slip in unnoticed.
   - I checked it against the real call log: it gives $1.55 for 11 Oct, the same as my hand calculation.
   - The clerk's repair step, which ran away to 65,000 tokens last time, now has its own cap.
2. **Free cache replays.** With `LEXARENA_CACHE_ONLY=1` a run only uses saved answers and never calls a paid model. The DEV_0007 replay stopped at the first step yesterday's fix changed, and cost $0.
3. **Knowledge base:**
   - **Lessons:** each side gets the top 5 lessons plus 5 random ones, chosen by the same rule for both sides.
   - **Law versions:** a lesson only reaches a case decided under the same version of the law, so 2019 law can't teach a 2025 case. Each lesson records its case's year.
   - **Lookups:** lawyers can ask for statutes, precedent searches, a precedent's rule, or their own lessons. The answer arrives before their next turn, at no extra API cost.
   - **Judges:** can look up statutes and their own lessons, but can't search precedents (they decide on what counsel cited).
4. **Reflection** now checks each side's arguments against the real judgment for named mistakes: missed evidence, unanswered points, wrong law version, misstated law, weak authority, misread facts, and strategy.
5. **Triage.** For the pilot, my split check can stand in for your review so the cases can teach. It's recorded separately from your own review, and every lesson says which kind of review it came from. One config switch (`memory.accept_claude_triage`) turns this off.
6. **Courtroom website** at **http://127.0.0.1:3005**. It shows:
   - each side's private preparation, then every turn as it's argued;
   - every attempt THEMIS sent back, and why;
   - the auditor's map of the hearing and all six judge opinions;
   - the verdict next to the real judgment, once evaluated.

   DEV_0002 and DEV_0007 are loaded. Those two older sessions have no "thinking" text; new sessions record it if DeepSeek sends it, which I haven't confirmed yet. The site runs only on your PC. To start it: `cd web && npm run start`. Phone access is a separate decision, because the models' thinking text can mention real names they remember.

## The "doesn't spoil anything" check

**Problems found and fixed:**
- **Lookups made the two sides' inputs unequal.** A statute one side looked up was going into the section both sides are meant to share identically. Now only that side sees it. My first test missed this; a new test catches it.
- **Running the pilot in batches could leak the future.** If batches ran out of date order, a lesson from a later case could reach an earlier one. Planning a run now refuses that.

**Confirmed clean:**
- **Searches and lookups** use the same date cut-off and excluded precedents as before.
- **Agents never see the decision date;** it's removed before the case reaches them.
- **The new trace files** are read by the website only, never by a model.
- **The clerk is never traced**, so real names never reach those files.
- **The real outcome** appears only after evaluation.
- **Years on lessons** are for you only; agents never see them.

**Two small risks left:**
- Lookups mean more searches, so if the clerk's overlap check missed a case's own judgment in the precedent database, the agents now have more chances to hit it.
- Statute lookups could hint roughly at a case's date. The record's own dates already show that much.

## Corrections and answers

- **Budget:** $20 − $3.91 = **$16.09 left**. A case really costs **about $0.40**, not the $0.215 I quoted earlier.
  - The 20-case pilot will cost about $9.
  - The full 500 still doesn't fit in $60. The pilot's measured cost will tell us which way to go.
- **SBI and TCS:** my notes say they're DEV_0001's own Supreme Court appeal and DEV_0004, so they're not part of the 500.
- **Not done on purpose:** I didn't switch any review step to "low reasoning". The pilot first measures quality at full reasoning, and it fits the budget anyway.

## Tomorrow

1. Smoke calls, then one DEV_0007 session through the money guard (~$0.40). If the new lookups misbehave, I set both to 0 in config and run without them.
2. Read each PDF's decision date, clerk the cases in date order on free Gemini keys, and run my split check on each.
3. Run the sessions in batches as cases are ready, and watch them live in the courtroom.

**I need from you:**
- the 20 PDFs, confirmed not part of the 500;
- **more free Gemini keys**: 7 keys clerk about 8–10 cases a day, so 20 cases take about 2 days.

**One open item:** a moderate security advisory remains in PostCSS, bundled with Next 15. It isn't exploitable for a viewer that runs only on your machine and reads only our own files.

## Where things are recorded

- Decisions: `docs/DECISIONS.md` D-109 to D-117.
- Risks and suggestions: `docs/OPEN_QUESTIONS.md` R-042 to R-046, S-012, S-013.
- Commits: aa5a01c, 4a910f1, 1c4f4b5, d4fcb7c, 2795fd5, 565ff11 (not pushed).
