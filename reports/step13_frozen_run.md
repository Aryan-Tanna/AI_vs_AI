# Run DEV_FROZEN_2

- status: **COMPLETE**
- mode: FROZEN; ablations: none; dry run: False
- code 1107fd6ef5522d96b1b9966c7c108ef06a72bda0-dirty; config v1 (8770042a5063)
- cases: 1 of 1 finished

## Cases (run order)

| # | case | split | SESSION | BASELINE | EVALUATE | REFLECT | memory unchanged |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | DEV_0001 | DEV | NOT_BUILT | DONE | SKIPPED | SKIPPED | yes |

## Memory

FROZEN run: 1 cases checked; snapshots ['MEMORY_NOT_BUILT']; unchanged: **True**; reflection ran 0 times.

## Quota used in the window

- gemini-2.5-flash on gemini_api: 8 requests, 32643 tokens
- gemini-3.5-flash on gemini_api3: 6 requests, 23059 tokens
- openai/gpt-oss-120b on Groq_API1: 1 requests, 1134 tokens
- openai/gpt-oss-120b on Groq_API4: 3 requests, 11165 tokens
- qwen/qwen3.8-27b on Groq_API3: 7 requests, 15455 tokens

## Evaluation

0 evaluated cases; bootstrap 2000 resamples, level 0.95, seed 7.

### HEADLINE (0 cases; 0 unstable; 0 mixed)

| level | system | predicted / eligible | accuracy | CI | balanced acc. | macro-F1 |
| --- | --- | --- | --- | --- | --- | --- |
| verdict | BENCH | 0 / 0 | - | - | - | - |
| verdict | SINGLE_LLM | 0 / 0 | - | - | - | - |
| verdict | MAJORITY_CLASS | 0 / 0 | - | - | - | - |
| verdict | McNemar bench vs single-LLM | 0 pairs | 0 vs 0 | p = 1.000 | | |
| issues | BENCH | 0 / 0 | - | - | - | - |
| issues | SINGLE_LLM | 0 / 0 | - | - | - | - |
| issues | MAJORITY_CLASS | 0 / 0 | - | - | - | - |
| issues | McNemar bench vs single-LLM | 0 pairs | 0 vs 0 | p = 1.000 | | |

### ALL (0 cases; 0 unstable; 0 mixed)

| level | system | predicted / eligible | accuracy | CI | balanced acc. | macro-F1 |
| --- | --- | --- | --- | --- | --- | --- |
| verdict | BENCH | 0 / 0 | - | - | - | - |
| verdict | SINGLE_LLM | 0 / 0 | - | - | - | - |
| verdict | MAJORITY_CLASS | 0 / 0 | - | - | - | - |
| verdict | McNemar bench vs single-LLM | 0 pairs | 0 vs 0 | p = 1.000 | | |
| issues | BENCH | 0 / 0 | - | - | - | - |
| issues | SINGLE_LLM | 0 / 0 | - | - | - | - |
| issues | MAJORITY_CLASS | 0 / 0 | - | - | - | - |
| issues | McNemar bench vs single-LLM | 0 pairs | 0 vs 0 | p = 1.000 | | |

### MEMORISED (0 cases; 0 unstable; 0 mixed)

| level | system | predicted / eligible | accuracy | CI | balanced acc. | macro-F1 |
| --- | --- | --- | --- | --- | --- | --- |
| verdict | BENCH | 0 / 0 | - | - | - | - |
| verdict | SINGLE_LLM | 0 / 0 | - | - | - | - |
| verdict | MAJORITY_CLASS | 0 / 0 | - | - | - | - |
| verdict | McNemar bench vs single-LLM | 0 pairs | 0 vs 0 | p = 1.000 | | |
| issues | BENCH | 0 / 0 | - | - | - | - |
| issues | SINGLE_LLM | 0 / 0 | - | - | - | - |
| issues | MAJORITY_CLASS | 0 / 0 | - | - | - | - |
| issues | McNemar bench vs single-LLM | 0 pairs | 0 vs 0 | p = 1.000 | | |

### EVIDENCE_DECIDED (0 cases; 0 unstable; 0 mixed)

| level | system | predicted / eligible | accuracy | CI | balanced acc. | macro-F1 |
| --- | --- | --- | --- | --- | --- | --- |
| verdict | BENCH | 0 / 0 | - | - | - | - |
| verdict | SINGLE_LLM | 0 / 0 | - | - | - | - |
| verdict | MAJORITY_CLASS | 0 / 0 | - | - | - | - |
| verdict | McNemar bench vs single-LLM | 0 pairs | 0 vs 0 | p = 1.000 | | |
| issues | BENCH | 0 / 0 | - | - | - | - |
| issues | SINGLE_LLM | 0 / 0 | - | - | - | - |
| issues | MAJORITY_CLASS | 0 / 0 | - | - | - | - |
| issues | McNemar bench vs single-LLM | 0 pairs | 0 vs 0 | p = 1.000 | | |

## Notes

- SESSION is not built yet (Step 9): no bench verdicts, so no case could be evaluated
