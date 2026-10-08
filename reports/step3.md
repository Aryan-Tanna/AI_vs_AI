# LexArena: Step 3 report (drafting tools for side collections)

**Date:** 2026-10-07
**Commits:** `569dd73` (Step 3), `336687e` (byte-exact source files)
**Status:** built, tested and committed. Step 3 is **not ticked** until you've reviewed it. Step 2 is ticked.

## Decisions waiting on you

1. **Q-023: which sections to draft first, and where the official texts come from.**
   - **What I propose drafting first:**
     - **s.4:** the threshold notification of 24.03.2020;
     - **s.10A:** this needs a Law DB record first (Q-010);
     - **s.12A, s.29A, s.32A, s.240A;**
     - **the Limitation Act exclusion.**
   - **Where the texts are:**
     - **Acts and Ordinances:** IBBI's Acts page lists them for 2019–2026; older ones are on page 2.
     - **Notifications** such as S.O. 1205(E) are elsewhere.
   - **Question:** will you download those notifications, or shall I look for them on official sites?
2. **S-009:** I suggest registering IBBI's consolidated "IBC up to <date>" PDFs. Their footnotes give, for each section, when it was inserted and by which Act. One document could then produce verified "in force from" drafts for most sections, and you would still approve each one.
3. **The real draft below** is waiting for your decision. I recommend you reject it, for the reason given. I never approve or reject.

## PUSHBACK [MAJOR]: what `section_in_force` should key on (Q-024)

- **Why it matters:** "does this section exist?" decides visibility. If it keys on a fact date (plan approval, default, filing), the code silently decides whether a provision reaches older facts. That breaks D-007, which says contested readings are chosen by the argument, and INTENT fear 4: an honest argument about retrospectivity becomes impossible.
- **Evidence:** both models proposed `keyed_on: PLAN_APPROVAL` for s.32A, and nothing in the checks stops it.
- **Options:**
  - **A (recommended):** `section_in_force` must key on `DECISION`, the hearing date, enforced as a blocking check. A section is visible if it exists in law at the hearing. Whether it applies to earlier facts goes into other parameters keyed on fact dates, as SPEC C2's table does (threshold on FILING, the s.10A window on DEFAULT), or stays open for the lawyers to argue.
  - **B:** allow any key, and you judge each row. That's a legal call per row with no lawyer on the team.
  - **C:** as is. Rows like the s.32A draft would hide provisions on retrospectivity grounds.
- **Until you decide:** please **don't approve any `section_in_force` row keyed on anything other than `DECISION`**. The fix goes into the prompt's v2 (S-010) together with whichever option you choose.

## What the tool does, step by step

1. **Register an official document:** `lexarena sources add ...`.
   - It downloads the PDF, pins its SHA-256, extracts the text and pins that too.
   - A PDF with no text layer is refused. Nothing is OCR'd.
2. **Draft:** `lexarena draft overlay|predicate --statute ID --source ID --find TERM`.
   - Code first finds the provision in the document using your search terms. If they aren't found, no model call is spent.
   - Two models from different families (Gemini and gpt-oss) each get **only** the Law DB record and those excerpts. They are told not to use memory.
   - Their answers are compared field by field: AGREED, DISAGREED (the two drafts are linked), or proposed by one model only. Code never picks a winner.
3. **Checked mechanically. These block approval:**
   - a quote that isn't **verbatim** in the document;
   - a date that isn't written in its own quote, because dates are never inferred;
   - a label or parameter outside the configured vocabulary;
   - a value of the wrong type;
   - a predicate pointing at a Law DB item that doesn't exist.
4. **Listed for you to judge** (code can't answer these):
   - numbers written in words;
   - a missing commencement date;
   - always: "Is this the version of the law that applied?" and "Which case date does this rule turn on?"
5. **Review:** you run `lexarena review approve ID --by NAME` or `review reject ID --by NAME --reason ...`.
   - A draft with blocking problems can't be approved.
   - Each decision records who decided and when, and you commit it to git.
6. **Load:** `lexarena review load` **re-checks** every APPROVED item against the document and the current Law DB before storing it. A hand-edited "APPROVED" file with problems is refused.
7. **STALE:** each predicate is tied to the exact text of its Law DB item, by hash.
   - **Item moves:** the predicate follows it.
   - **Item's text changes:** the predicate goes STALE and is never served.
   - **Text restored:** the predicate is approved again.

## Real output

**The source:** IBC (Amendment) Act, 2020 (Act No. 1 of 2020), from ibbi.gov.in. It's 5 pages with a clean text layer (1,280 / 3,735 / 3,411 / 3,426 / 1,517 characters).

**The draft for `IBC_2016_SEC_32A`:** two live calls, and both models agreed.

```
row:      section_in_force = true, keyed_on PLAN_APPROVAL, effective_from 2019-12-28
checks:   source_text           VERIFIED   "10. After section 32 of the principal Act, the following section shall be inserted, namely:—"
          effective_from_quote  VERIFIED   "the 28th day of December, 2019"
          effective_from_date   MATCHED    2019-12-28
          value_quote           NOT_FOUND  the models added a closing quote mark after "32A." that is not in the Act
blocking: value_quote: quote not found verbatim in the source
judge:    Is this the provision as it applied to cases on these dates ...?
          Is PLAN_APPROVAL the case date this rule turns on?
```

What this shows:
- **The verbatim check caught a small but real alteration.** The models added a closing quote mark after `32A.` that isn't in the Act, so the draft can't be approved as it stands.
- **The date was verified, not remembered.** "The 28th day of December, 2019" comes from s.1(2) of the Act: "It shall be deemed to have come in force on the 28th day of December, 2019".
- **The choice of `PLAN_APPROVAL` is a trap, not just a judgment call (Q-024).** Keyed on PLAN_APPROVAL, s.32A would be **hidden from everyone** (lawyers, THEMIS, judges) in any case whose plan was approved before 28.12.2019. That silently decides retrospectivity, which is exactly what courts argue about. See the pushback below.

The file is `review/temporal_overlay/OV_IBC_2016_SEC_32A_e363b79890.json`. **My recommendation:** reject it, with the reason "value_quote not verbatim". The next round needs a prompt fix (S-010 below).

**A source we can't use (R-020):** the IBC (Amendment) **Ordinance**, 2020, which inserted s.10A. On IBBI's site its operative page has only 47 characters of text: it's a Hindi-font Gazette scan. The tool would refuse to quote it. The later Act, or a consolidated text, has to be used instead.

**All live model calls work:** all 9 roles, including the two new drafters, answered on the first attempt.

## Test results (actual output)

```
offline:      380 passed, 125 skipped     (run after the last change)
integration:  119 passed                  (real MongoDB, run after the last change)
ruff, mypy:   clean
```

**Tests first:** I wrote the tests first again, and they found three real problems before any code shipped:
- **Hyphenated line breaks:** "Gov-/ernment" in PDFs needed the matching rule extended.
- **Draft IDs:** IDs ignored the quotes, so a bad draft could clash with a good one.
- **A test gap:** my test couldn't catch a source re-registered after drafting. I added that test.

**Planted bugs:** 8 of 8 turned the suite red:

| Planted bug | Result |
| --- | --- |
| quotes not checked | 5 failed |
| inferred dates allowed | 1 failed |
| approving despite blocking problems | 1 failed |
| loader trusts the review file | 1 failed |
| loader ignores a changed source | 1 failed, once the new test was added |
| loader loads drafts | 1 failed |
| never marks STALE | 1 failed |
| vocabulary not enforced | 1 failed |

## Definition of done

- [x] **Acceptance:**
  - you can approve or reject drafts in `review/`;
  - a changed Law DB item marks its predicate STALE (integration test).
- [x] Tests written first; all passing; planted bugs caught.
- [x] **No law or tuning literals.** The only legal text in the repo is the registered official PDF and the one DRAFT. Tests use a fictional "Test Act".
- [x] **No path to sealed data:** drafting reads only the Law DB and registered sources, and loading runs in the offline ingest process.
- [x] DECISIONS D-041; OPEN_QUESTIONS Q-023, R-020, S-009.

## Retrospective

- **Harder than expected:**
  - **Official PDFs vary wildly.** One Act has a clean text layer; the Ordinance before it has none.
  - **Shell escaping on Windows** garbled two files mid-step. I now write fixes as script files.
- **What I'd do differently:** search the source text for the exact clause before the first drafting call, and tune the prompt on that. The first live draft was lost to one added quote mark.
- **Changes to later steps:**
  - **Step 6 (clerk):** must use `vocabulary.case_date_labels`, so overlay rows and case dates use the same labels.
  - **Step 7 (THEMIS layer 1):** reads only APPROVED, non-STALE predicates via `LawRepository.predicates()`.

## Suggestion

**S-010:** make the overlay prompt quote smaller spans.
- **What:** split `value_quote` into the exact operative words only, with no surrounding punctuation, and show the models one worked example built from the fictional Test Act.
- **Benefit:** fewer blocked drafts like the one above.
- **Cost:** one prompt version bump (`drafting/overlay.v2`). A retry wouldn't help: the LLM cache replays the identical answer until the prompt version changes.
- **Serves:** non-negotiable 8.
