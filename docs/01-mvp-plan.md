# Come-Blog — MVP Plan

## 1. Goal

A multi-agent blog-writing system. User gives a topic → an orchestrator plans
sections → parallel workers draft each section → an evaluator checks/refines
each draft in a loop → a reducer assembles the final post → output is a
Markdown file, viewable/downloadable from a UI.

This doc defines the MVP only. No auth, no multi-user, no persistence beyond
the filesystem, no cloud deploy yet — but structured so those are additive,
not rewrites.

## 2. Tech stack (all free / open source, local-first)

| Layer | Choice | Why |
|---|---|---|
| LLM runtime | **Ollama** (already installed) | Local, free, no API keys |
| Model | `llama3.1:8b` (or `qwen2.5:7b-instruct`) | Good instruction-following at a size that runs on a laptop; swappable via config |
| Orchestration | **LangGraph** | Native support for dynamic fan-out (`Send` API) for the worker step, cycles (evaluator↔worker loop), typed state |
| LLM client | **langchain-ollama** | Official LangGraph-compatible Ollama chat wrapper |
| Backend API | **FastAPI** | Async, typed, easy to wrap the graph behind an HTTP+streaming API; production-friendly |
| Server | **Uvicorn** | Standard ASGI server for FastAPI |
| UI | **Streamlit** | Matches your call — fastest path to a usable UI, calls the FastAPI backend over HTTP (keeps UI and agent logic decoupled for later swap/scale) |
| Validation | **Pydantic v2** | Shared schema between graph state, API request/response |
| Config | **pydantic-settings** + `.env` | Model name, Ollama host, timeouts, max workers — all env-overridable |
| Output | Markdown file under `output/` dir, named `{slug}-{timestamp}.md` | Simple, inspectable, git-ignorable |
| Package/env mgmt | **uv** (or plain `venv` + `pip`) | Fast, reproducible installs |
| Testing | **pytest** | Unit test the graph nodes with a fake/mock LLM |
| Lint/format | **ruff** | Single fast tool for both |

No vector DB, no RAG, no auth, no Docker yet — explicitly deferred (see §6).

## 3. Graph design (LangGraph)

```
START
  │
  ▼
orchestrator  — plans topic into N sections (title + brief + key points)
  │  (LangGraph Send → dynamic fan-out, one Send per section)
  ▼
worker (×N, parallel)  — drafts one section from its brief
  │
  ▼
evaluator (×N, parallel, same fan-out branch)  — scores + critiques the draft
  │
  ├─ score < threshold AND attempts < max_retries → loop back to worker
  │  (worker revises using the critique)
  │
  └─ score ≥ threshold OR attempts == max_retries → send to reducer
  ▼
reducer  — merges all accepted sections into one coherent post
          (intro/outro, consistent tone, de-dup, flow) — single LLM call
  │
  ▼
write_markdown  — writes final post to output/*.md
  │
  ▼
END
```

Key decision vs. your original sketch: **evaluator sits between worker and
reducer, per-section, in a loop** — exactly your instinct. The reducer only
ever sees already-accepted sections, so it focuses purely on stitching/flow,
not quality-fixing.

### State shape (Pydantic, shared across graph)

```python
class SectionPlan(BaseModel):
    id: str
    title: str
    brief: str          # what this section should cover
    key_points: list[str]

class SectionDraft(BaseModel):
    id: str
    title: str
    content: str
    attempt: int = 1

class SectionEvaluation(BaseModel):
    id: str
    score: float         # 0-1
    passed: bool
    feedback: str

class BlogState(BaseModel):
    topic: str
    sections: list[SectionPlan] = []
    drafts: dict[str, SectionDraft] = {}      # keyed by section id
    evaluations: dict[str, SectionEvaluation] = {}
    final_markdown: str | None = None
    output_path: str | None = None
```

Per-section loop state (worker/evaluator subgraph) carries `attempt` count;
`max_retries` (default 2) is a config value, hard cap to avoid infinite loops
and runaway Ollama calls.

### Nodes

- **orchestrator**: one LLM call, structured output (Pydantic) → list of
  `SectionPlan`. Enforce min 2 / max 6 sections for MVP sanity.
- **worker**: one LLM call per section. On retry, includes prior draft +
  evaluator feedback in the prompt.
- **evaluator**: one LLM call per section, structured output
  (`score`, `passed`, `feedback`). Threshold configurable (default 0.7).
- **reducer**: one LLM call, takes all passed drafts in section order →
  full blog with intro/conclusion, consistent voice.
- **write_markdown**: pure Python, no LLM — writes `final_markdown` to disk
  with frontmatter (title, topic, generated_at).

### Dynamic fan-out

Implemented with LangGraph's `Send` from the orchestrator's conditional edge
— one `Send("worker", {...})` per `SectionPlan`. Worker→evaluator is a fixed
edge per branch; evaluator's conditional edge either `Send`s back to worker
(same section id) or routes to a join point that waits for all branches
before entering `reducer` (LangGraph handles this via the fan-in on the
shared state).

## 4. Backend API (FastAPI)

Minimal surface for MVP:

- `POST /blogs` — body `{"topic": str}` → starts a run, returns `{"run_id": str}`
- `GET /blogs/{run_id}` — returns status (`planning|writing|evaluating|reducing|done|error`) + progress (section count done) + final markdown + file path once `done`
- Runs execute as a background task (FastAPI `BackgroundTasks` is enough for MVP; no queue/worker infra yet)
- In-memory dict for run state (MVP only — no DB yet, see §6)

Streaming (SSE or polling) is nice-to-have, not MVP-critical: Streamlit will
poll `GET /blogs/{run_id}` every ~2s while status != done.

## 5. UI (Streamlit)

Single page:
1. Text input: topic
2. "Generate Blog" button → calls `POST /blogs`
3. Progress area: polls status, shows current stage + per-section pass/fail
4. On done: renders markdown, shows a "Download .md" button

## 6. Explicitly deferred (not in MVP)

- Docker/containerization and actual cloud deployment
- Persistent DB (Postgres) for run history — in-memory for now
- Auth/multi-tenancy
- Web search / RAG for factual grounding
- Streaming token-by-token UI
- Horizontal scaling / task queue (Celery/RQ)
- CI/CD pipeline

These are the natural "next" steps once the MVP flow is proven end-to-end;
listed here so the production-grade shape is visible even though we aren't
building it yet.

## 7. Repo layout (target)

```
Come-Blog/
├── docs/
│   └── 01-mvp-plan.md
├── backend/
│   ├── app/
│   │   ├── main.py            # FastAPI app, routes
│   │   ├── config.py          # pydantic-settings
│   │   ├── graph/
│   │   │   ├── state.py       # Pydantic models
│   │   │   ├── nodes.py       # orchestrator/worker/evaluator/reducer/writer
│   │   │   └── build.py       # assembles the LangGraph graph
│   │   └── runs.py            # in-memory run registry
│   ├── tests/
│   └── pyproject.toml
├── ui/
│   └── streamlit_app.py
├── output/                    # generated .md files (gitignored)
├── .env.example
├── .gitignore
└── README.md
```

## 8. Milestones

1. `backend/app/graph` — build + unit test the graph with a stub LLM (no Ollama dependency in tests)
2. Wire real Ollama model in, manual end-to-end run via a small script
3. FastAPI wrapper around the graph + in-memory run store
4. Streamlit UI hitting the API
5. README with setup instructions (install Ollama model, run backend, run UI)
