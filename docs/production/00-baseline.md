# 00 - Baseline (before the production work)

Measured on 2026-10-31 on branch `develop`, with uncommitted working-tree
changes included. Every later step in this folder is compared against these
numbers. `scripts/metrics.py` reproduces them.

## What the product was

A topic goes in, one 10-sentence paragraph comes out, wrapped in a `# title`
heading and saved as Markdown. There was no HTML, no images, no links, no
sources shown to the reader, and no persistence beyond one `.md` file.

## Measured numbers

| Metric | Baseline | Notes |
|---|---|---|
| Python source files (backend + ui + tests) | 15 | `git ls-files` + untracked |
| Python lines | 629 | physical lines |
| Test result | 9 passed, **1 failed** | `test_search_topic_formats_tavily_context` fails: `ModuleNotFoundError: tavily` |
| Ruff findings | 3 | `UP035`, `B039`, `I001` |
| Output formats | 1 (Markdown) | |
| Article length | ~10 sentences, 1 section | hard-coded in the prompt |
| Images per article | 0 | |
| Clickable links per article | 0 | search sources were used but never shown |
| Source citations in output | 0 | |
| Pass/fail gate | model's own `passed` flag | the documented 0.7 threshold was never enforced in code |
| Draft history returned | 1 draft (final only) | UI said "Draft history" but only ever had one entry |
| Tavily calls per preview + blog session | 2 | `/preview` and the orchestrator both searched the same topic |
| Progress events delivered | 0 | `_emit` calls had no `event_sink` wired up |
| Request model | synchronous, blocks up to 180 s | |
| Persistence | 1 file in `output/` | no index, no listing, no metadata |
| Run history / stats | none | |
| Auth / rate limiting / security headers | none | CORS `*` |
| Download correctness | wrong | UI prepended a second `# topic` heading |
| Container / CI | none | |

## Known defects carried into the plan

1. Draft history lost (only last attempt kept).
2. 0.7 threshold not enforced in code.
3. Duplicate Tavily call per session.
4. Progress events never delivered.
5. Download adds a duplicate title.
6. Attempt limit `3` hard-coded in two places.
7. Graph recompiled on every request.
8. `tavily` missing from the venv, so one test fails on a clean checkout.

## Constraints for this work

- No commit, no push, no OS or system files touched.
- The sandbox denied `pip install`, so **no new third-party dependencies**.
  Everything new is standard library plus packages already in the venv
  (`langgraph`, `langchain-ollama`, `fastapi`, `pydantic`, `httpx`).
- Local models only: `qwen2.5:3b` (writer) and `qwen3:4b` (evaluator), both
  confirmed present in Ollama on this machine.
