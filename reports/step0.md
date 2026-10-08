# LexArena: Step 0 report

**Date:** 2026-10-06
**Commits:** `1e42647` (Step 0), `7d91f18` (review fixes)
**Status:** built, tested and committed. Not yet ticked in `docs/BUILD_PLAN.md`; that waits until you've looked at the output below.
**One gap:** the database part is written but has never run, because Docker isn't detectable on this machine yet.

## What I built

- **Project setup:** a `uv`-managed environment (Python 3.12, lockfile), ruff, mypy in strict mode, and pytest. Tests that call real APIs or need Docker only run when asked.
- **`config/config.v1.yaml`:** every tunable value, each tagged with where it came from: the SPEC, a decision, a measurement, or a placeholder of mine for Step 14 to calibrate. Every field is required, so a missing or unknown key fails at load. The loader also refuses:
  - THEMIS on the same model family as the lawyers;
  - two clerk models from the same family;
  - verifiers and extractors above temperature 0;
  - weight groups that don't sum to 1.
- **LLM client:** returns schema-checked JSON. Retries and backoff come from config, and invalid output is repaired with a versioned prompt. It fails immediately in four cases, rather than retrying:
  - a request that is too large;
  - output cut off at the token limit;
  - a quota wait longer than allowed;
  - a refusal.

  Responses are cached under a key that covers everything that can change the output. Logs hold IDs and hashes only, never prompt text, because clerk prompts contain real party names.
- **Providers:** one adapter for OpenAI-style APIs (Groq now; your paid DeepSeek and Qwen later need only config) and one for Gemini.
- **CLI:** `lexarena config show` and `lexarena llm smoke`. CLAUDE.md §12 lists the commands.
- **Docker:** `docker-compose.yml` for MongoDB, Qdrant and Redis, bound to localhost only, with separate Mongo users for the app and the sealed ground truth.

## Test results

- **Offline:** 200 passed. The 9 skipped are 5 live and 4 Docker tests. ruff and mypy are clean.
- **Live:** all 7 roles returned schema-checked JSON (exit 0):

  ```
  {"role": "lawyer", "model": "openai/gpt-oss-120b", "value": {"answer": 365, "unit": "days"}, "attempts": 1}
  {"role": "verifier", "model": "qwen/qwen3.8-27b", "value": {"answer": 365, "unit": "days"}, "attempts": 1}
  {"role": "judge", "model": "gemini-2.5-flash", "value": {"answer": 365, "unit": "days"}, "attempts": 1}
  {"role": "clerk_primary", "model": "gemini-3.5-flash", "value": {"answer": 365, "unit": "days"}, "attempts": 2}
  ... auditor, clerk_secondary and reflection: ok
  ```

- **Nested schemas,** like the real case records will need, also work live on all three model families.
- **I checked the important tests by planting bugs** (a code default in config, broken cache keys, a leaked key in a tracked file, a non-normalised hash) and confirmed each turns a test red. One cache test had been passing for the wrong reason; I replaced it with tests that catch the bug.
- **There's no dev-case JSON yet:** Step 0 doesn't touch case data. The first real output from your data comes in Step 2 (Law DB validation report).

## What live testing found

- **Groq free tier:** at most 7,000 input tokens per request and 1,000 requests a day.
- **Gemini free tier: 20 requests a day per model.** `gemini-3.8-flash` failed most calls with "high demand", then used up its quota, so I moved those roles to `gemini-3.5-flash` (clerk) and `gemini-2.5-flash` (judge, auditor, reflection). This means the clerk can realistically process only one or two dev cases a day.
- **Two bugs found and fixed:**
  - A spent Gemini quota asks the caller to wait 4.2 hours, and the client would have slept that long. It now fails at once.
  - The config hash depended on line endings, so the same commit hashed differently on Windows and Linux. It's now normalised.

## Definition of done

- [x] Acceptance criteria met with real output (above)
- [x] Tests written first, all passing in this session
- [x] No law or tuning literals: an automatic scanner test enforces it
- [ ] No path to sealed data, tested: **not yet.** The two-user Mongo setup has never run without Docker; the real access-control work is Step 1.
- [x] DECISIONS (D-025 to D-031) and OPEN_QUESTIONS (R-014, R-015, Q-017, Q-018) updated

**Changes outside the code:**

- I appended 13 variables to your `.env.local`: the config path, generated local-only Mongo passwords, and the service URLs. Your API keys are untouched.
- DATA_FORMATS now has short "superseded by D-0xx" notes where your decisions changed a rule.

## Retrospective

- **Harder than expected:** the free tiers. I'll check quotas before choosing models from now on.
- **What I'd do differently:** test my own tests with planted bugs from the start; that's how the false-passing cache test turned up.
- **Change for later steps:** calibration (Step 14) must run on your paid DeepSeek and Qwen models, still on the dev set only. Values tuned on Groq and Gemini won't carry over (R-014).

## Before Step 1

1. **Docker:** finish the install or restart Windows, then I'll run the 4 service tests. Step 1 (access control) needs a running MongoDB.
2. **Groq accounts:** config uses keys from 3 different Groq accounts, one per role. Pooling free accounts may break Groq's terms. Confirm this is acceptable, or I'll put all Groq roles on one key.
3. **Approve Step 0** so I can tick it and start Step 1.

These two can wait:

- **Q-017:** in Phase 2, which model family do the judges use? I recommend the verifier's family, so judges never score text written by their own model.
- **Q-018:** should I add superseded notes to `SPEC.md`, or will you update the source doc?
