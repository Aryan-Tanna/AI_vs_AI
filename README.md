# LexArena

A multi-agent adversarial simulation of NCLAT insolvency appeals under the Insolvency and Bankruptcy Code,
2016:
- appellant and respondent advocate agents
- a per-turn verifier (THEMIS-LOCAL) that checks facts, arithmetic, provisions and citations, never the merits
- a whole-transcript audit
- a bench of judge agents
- evaluation against the real NCLAT orders

**Research simulation, not legal advice.** Simulated orders are never presented as real tribunal orders.

| Document | What it covers |
|---|---|
| [CLAUDE.md](CLAUDE.md) | Source of truth: design, legal rules, data model, decisions, build plan |
| [docs/ROADMAP.md](docs/ROADMAP.md) | What is done, what is a stand-in, what to do next |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | Architecture (image: [docs/architecture.png](docs/architecture.png)) |
| [docs/schema/README.md](docs/schema/README.md) | Public case DB record structure |
| [docs/examples/public_case_example.md](docs/examples/public_case_example.md) | Worked example: splitting a judgment |

## Setup

Requirements:
- Python ≥ 3.12
- [Claude Code](https://code.claude.com) installed and logged in with your Claude subscription

```
pip install -e ".[dense,dev]"                                       # dense = bge-small retrieval (optional)
python -m pytest                                                     # 110 tests, no model calls
```

Do **not** set `ANTHROPIC_API_KEY`. If it's set, Claude Code bills the API instead of the subscription, so the
backend refuses to start. Runs use the owner's own account; don't share one login across a team.

## Build the data

```
python -m lexarena.ingest.build_reference          # raw precedent files -> data/canonical/reference_cases.jsonl
python -m lexarena.retrieval.build_index --dense   # bge-small-en-v1.5 vectors -> data/index/ (~40 min on CPU)
python -m lexarena.ingest.build_silver            # silver train/dev cases -> data/silver/ (no model calls)
python scripts/validate_public_db.py               # validate public_db/ (the simulation cases)
```

Sources (precedent DBs, law DBs, web access, MCP servers) are declared in
[config/sources.yaml](config/sources.yaml). Any JSON/JSONL precedent file can be added with a field mapping.

## Run

```
python -m lexarena.cli smoke                                   # one tiny call: login, tools, isolation
python -m lexarena.cli enqueue debate --split dev --run-id dev1
python -m lexarena.cli run --wait                              # works within 5-hour windows, resumes after resets
python -m lexarena.cli status
python -m lexarena.cli evaluate --run-id dev1 --split dev    # metrics vs sealed ground truth
LEX_MODE=live python -m lexarena.cli run                       # live mode: open web search (no answer key)
```

The default mode is `eval`. It's closed and reproducible: only sources that respect the date cutoff are used,
and web access is limited to official statute sites.

## Layout

```
lexarena/   config, llm (subscription backend, cache), session (queue, runner, ledger), sources, ingest,
            retrieval, law, rules (+ Z3), themis, agents, tools, orchestrator, schemas, cli
config/     sources.yaml
data/seed/  curated seed data (SC landmarks: year only, unverified)
docs/       architecture, roadmap, schema, examples
scripts/    audit, schema export, public DB validator
tests/      unit and integration tests (fake backend; no subscription usage)
```

The raw folders `nclat_precedents*/`, `law_db/` and `law2db/` are read-only inputs.
