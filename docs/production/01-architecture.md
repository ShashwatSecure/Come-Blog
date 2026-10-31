# 01 - Architecture: from one paragraph to a published site

## Decision

Keep LangGraph and the fixed-workflow shape (see the earlier workflow-vs-agent
discussion), but change what flows through it. The old graph produced one
10-sentence string. The new graph produces a structured `Article` and publishes
a static site from it.

```
 research -> plan -> write (parallel sections) -> assemble + gates -> review
                        ^                                              |
                        |                                   passed or attempts exhausted?
                        +------------ prepare_retry <---- no           |
                                    (rewrites ONLY failing sections)   v yes
                                                                   publish -> END
```

| Node | What it does | LLM? |
|---|---|---|
| `research` | Wikipedia + Commons (free) and Tavily (optional) in parallel; dedupe, number sources, collect open-licensed images | no |
| `plan` | Title, subtitle, excerpt, tags, N section headings with key points. Falls back to a template plan if the small model breaks the schema | writer model |
| `write` | Writes sections in parallel (2 workers). On retry only the failing sections are rewritten, using reviewer feedback | writer model |
| `assemble` | Takeaways + closing, builds the `Article`, runs 8+ deterministic quality checks | writer model (wrap-up only) |
| `review` | Independent model scores the post and names the weakest section; skipped gracefully if the model is down | evaluator model |
| `publish` | Downloads images, writes `article.json`, `article.md`, `index.html`, cover art, rebuilds index/feed/sitemap | no |

Still a workflow, not an agent: the developer owns the routing. The only
autonomy is a bounded rewrite loop (`COMEBLOG_MAX_ATTEMPTS`, default 2).

## Module map (22 source files)

| Layer | Files |
|---|---|
| Domain | `domain.py` (Article, Source, QualityReport...), `textutil.py` |
| Pipeline | `graph/build.py`, `graph/nodes.py`, `graph/state.py`, `graph/llm.py` |
| Research | `research.py`, `images.py` |
| Quality | `quality.py` |
| Output | `render.py` (HTML/CSS/RSS/sitemap/Markdown), `store.py` |
| Service | `main.py`, `runs.py` (job queue), `security.py`, `config.py`, `logging_config.py` |

## Defects from the baseline fixed here

| Baseline defect | Resolution |
|---|---|
| Draft history lost | `AttemptRecord` per pass stored in `article.json` |
| 0.7 threshold unenforced | `QualityReport.passed` requires blocking checks AND `llm_score >= pass_threshold` |
| Tavily called twice | One cached `research()` call shared by preview and generation (15 min TTL) |
| Progress events never delivered | `event_sink` wired to the job manager; polled by the UI |
| Download had a duplicate title | UI now downloads the server-built Markdown unchanged |
| Attempt limit hard-coded twice | `COMEBLOG_MAX_ATTEMPTS` |
| Graph recompiled per request | `@lru_cache` on `build_graph()` |
| `tavily` missing broke a test | Tavily is called over plain `httpx`; no SDK dependency |

## Trade-offs

- **No new dependencies.** The sandbox blocked `pip install`, so everything uses
  `httpx`, `jinja`-free f-string templates and the standard library. A real
  Markdown library and Jinja2 would be nicer; the renderer is small, escapes
  everything, and is covered by tests.
- **Static output.** Posts are plain files, so the blog can be hosted anywhere
  (any static host, S3, GitHub Pages) without the API.
- **Two models kept.** `qwen2.5:3b` writes, `qwen3:4b` reviews, as before.
