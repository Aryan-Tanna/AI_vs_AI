# Using Claude Code on LexArena

## Before the first session

Put these in your repository:

| Path | What it is | Where it comes from |
| --- | --- | --- |
| `CLAUDE.md` | Always-loaded instructions | This pack |
| `docs/INTENT.md` | Your goals, fears, fixed choices | This pack (edit freely; it's your voice) |
| `docs/ARCHITECTURE.md` | Condensed architecture | This pack |
| `docs/DATA_FORMATS.md` | Frozen formats, side collections, predicate grammar, config | This pack |
| `docs/BUILD_PLAN.md` | Ordered steps with acceptance criteria | This pack |
| `docs/DECISIONS.md` | Decision log, pre-filled | This pack |
| `docs/OPEN_QUESTIONS.md` | Claude Code's log of questions, risks and suggestions | This pack (empty template) |
| `docs/SPEC.md` | The full issues-and-fixes register | Export the "LexArena: Issues & Fixes Register" doc to Markdown |
| `docs/archive/` | Your original blueprint documents | Your files; historical only |
| `data/samples/law_db_sample.json` | 10–20 real Law DB records | Your Law DB |
| `data/samples/precedents_sample.jsonl` | 20–50 real precedent records | Your precedent DB |
| `data/dev/` | 10–15 judgment PDFs **not** among the 500 | Same source as your 500 |
| `data/law_db/`, `data/precedents/` | Full Law DB and precedent files | Your files |

Keep the 500 judgments out of the repo until Phase 2.

## Prompt 1: first session (paste as-is)

```
You are joining LexArena as lead engineer and technical critic (CLAUDE.md section 2). Before writing any code:

1. Read CLAUDE.md, docs/INTENT.md and docs/ARCHITECTURE.md (already loaded), then read docs/SPEC.md, docs/DATA_FORMATS.md, docs/BUILD_PLAN.md, docs/DECISIONS.md and docs/OPEN_QUESTIONS.md in full. Skim docs/archive/ only to understand history; it is superseded wherever it conflicts.

2. Look at data/samples/ and tell me whether the real records match DATA_FORMATS.md. List every mismatch (missing fields, ID styles, date formats) without changing any data.

3. In your own words, write:
   a) what LexArena does, end to end, in under 300 words;
   b) my non-negotiables and the fears each one protects against;
   c) the access rules for case_ground_truth and private turn data.

4. Push back. Using the PUSHBACK format in CLAUDE.md section 5.2, challenge:
   - every contradiction, gap or ambiguity across the documents (quote the conflicting lines);
   - any decision in DECISIONS.md you believe is wrong or risky, even though I made it;
   - any acceptance criterion in BUILD_PLAN.md that could pass while the feature is broken;
   - anything you think is over-engineered for a first version.
   Do not soften this to be agreeable. I would rather hear it now than after Step 9.

5. Contribute. Give up to 5 suggestions of your own (benefit, cost, what they serve). Record them, and any risks you see, in docs/OPEN_QUESTIONS.md.

6. Propose how you will execute BUILD_PLAN Step 0, including the exact files you will create.

Do not write code in this session. Stop after step 6 and wait for my answers.
```

## Prompt 2: start any build step

```
We are on BUILD_PLAN Step <N>: <name>.

Reply in the "before writing code" structure from CLAUDE.md section 7:
1. Understanding: deliverables, "done when" criteria, and the SPEC, DATA_FORMATS and DECISIONS entries that constrain this step.
2. Plan: files, public interfaces, schemas touched, tests you will write first.
3. Pushback: anything that would hardcode a legal value or tuning number, touch a frozen format, give a component access it should not have, or fail to meet the criteria. Also challenge the step itself if its scope or order looks wrong.
4. Questions: only ones whose answers change what you build.
5. Suggestions: up to 3.

Wait for my go-ahead. After I approve: tests first, then code, then run the tests and show real sample output from dev data. Finish with the "after implementing" structure, the definition-of-done checklist (CLAUDE.md section 11), and a short retrospective.
```

## Prompt 3: legal drafting (overlay rows, predicates, persona prompts)

```
Draft <what> for <statute IDs> into review/ as DRAFT items.

Rules:
- Every item must quote the exact statute or notification text it encodes in source_text, with its source reference.
- If the text does not literally fix a number, date or condition, do not encode it as a closed rule: mark it as an open parameter or leave it to the LLM layer, and say why.
- Run the draft past the secondary model in config and list every disagreement.
- Do not load anything. I will review and mark items APPROVED.
```

## Prompt 4: review a clerked case

```
Show me the clerk output for <case_id> next to the judgment paragraphs it cites.
For every stipulated fact, exhibit card, amount and date, show the source paragraph text.
List all extraction flags, anything the leakage scan caught, and any field you were unsure about.
Do not fix anything until I respond.
```

## Prompt 5: bug fix during a run (Phase 2)

```
A bug was found during run <run_id>: <description>.

1. Explain the root cause and which sessions it affected.
2. Propose the smallest fix that changes no tuning value, prompt or threshold.
3. After my approval: fix it, bump the code version, record it in DECISIONS.md, and list the sessions that must be re-run.
```

## Prompt 6: critical review (after every 3 or 4 steps, and before Phase 2)

```
Step back from the current task and review LexArena as a sceptical reviewer would, someone trying to show the results are invalid.

1. Find the three weakest points in what we've built so far: leakage paths, bias between agents, verifier errors, untested assumptions, or metrics that could look good while the system is wrong. For each, show the evidence and use the PUSHBACK format.
2. Check the code against every non-negotiable in CLAUDE.md section 4. Grep for literals that look like legal values or tuning numbers, and test every path to sealed data.
3. Re-read docs/INTENT.md. Is anything we've built drifting from what I said I want? Say so plainly.
4. Update docs/OPEN_QUESTIONS.md with every new risk.

No code changes in this session.
```

## Habits that keep it on track

- Start each session with Prompt 2. Even when a step looks small, the restatement catches drift.
- Ask for real JSON from dev cases at the end of every step.
- If Claude Code proposes changing a frozen format, a sealed-data rule or a non-negotiable, say no and ask for an alternative.
- Re-read `docs/DECISIONS.md` at the start of Phase 2, and keep it current.