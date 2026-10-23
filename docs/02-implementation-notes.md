# Come-Blog — Implementation Notes (MVP)

Companion to [`01-mvp-plan.md`](01-mvp-plan.md). This doc explains **why**
the implementation looks the way it does and **how** the pieces fit
together, so future changes can be made with the original reasoning intact.

## 1. Repo layout (as built)

```
Come-Blog/
├── docs/
│   ├── 01-mvp-plan.md
│   └── 02-implementation-notes.md
├── backend/
│   ├── pyproject.toml
│   ├── app/
│   │   ├── main.py            # FastAPI app, 3 routes
│   │   ├── config.py          # pydantic-settings, env-driven
│   │   ├── runs.py            # in-memory run registry + graph execution
│   │   └── graph/
│   │       ├── state.py       # Pydantic state models (BlogState, SectionWorkState, ...)
│   │       ├── llm.py         # get_llm() factory — single seam for mocking
│   │       ├── nodes.py       # orchestrator/worker/evaluator/reducer/writer
│   │       └── build.py       # LangGraph graph assembly (subgraph + fan-out)
│   └── tests/
│       ├── conftest.py        # FakeLLM — no Ollama needed to run tests
│       └── test_nodes.py      # unit tests for every node + routing logic
├── ui/
│   ├── streamlit_app.py
│   └── requirements.txt
├── output/                    # generated .md files (gitignored, .gitkeep tracked)
├── .env.example
└── .gitignore
```

## 2. Why a subgraph for worker/evaluator/retry?

**How:** `build.py` compiles a small `StateGraph(SectionWorkState)`
(`worker → evaluator → [retry back to worker | accept]`) and registers the
*compiled subgraph itself* as the `"worker"` node of the parent
`StateGraph(BlogState)`. The parent fans out with
`Send("worker", SectionWorkState(...))` — one per planned section.

**Why:** This is the cleanest way to express "N independent per-section
retry loops run in parallel, then join" in LangGraph:
- Each `Send` gets its own isolated `SectionWorkState` (topic + one
  `SectionPlan` + its own `attempt` counter) — sections can't see or
  interfere with each other's retry state.
- The retry loop (worker ↔ evaluator) stays entirely inside the subgraph,
  so the parent graph's control flow is a flat, readable pipeline:
  `orchestrator → worker(×N) → reducer → write_markdown`.
- This directly implements the correction you made to the original
  sketch: the evaluator sits **between worker and reducer, per section, in
  a loop**, not as a single global check after reduction. Each section is
  independently refined before the reducer ever sees it.

## 3. Why `Annotated[dict, merge_fn]` / `Annotated[list, operator.add]` on state

**How:** `drafts`, `evaluations` are `Annotated[dict[str, T], _merge_dict]`;
`accepted_ids` is `Annotated[list[str], operator.add]`.

**Why:** LangGraph fans out N parallel branches that each return a *partial*
state update (e.g. `{"drafts": {"s3": draft}}`). By default LangGraph would
need a reducer function to know how to combine N such partial updates into
one state — without it, concurrent writes to the same key across branches
raise an `InvalidUpdateError`. Declaring a merge reducer (`_merge_dict` for
dicts keyed by section id, `operator.add` for the accepted-id list) tells
LangGraph "last-writer-wins per key" / "concatenate" respectively, which is
exactly the semantics we want: each branch only ever writes its own
section's key, so merges are always additive, never actually conflicting.

## 4. Why a conditional "join" edge instead of a plain edge into reducer

**How:** `_join_check` in `build.py` is the conditional router after the
`"worker"` node. It compares `state.accepted_ids` against the full set of
planned section ids; only once every section has reached `accept_section`
does it route to `"reducer"` — otherwise it routes to `END` for that
particular invocation of the node (LangGraph re-invokes the router each
time a parallel branch completes and merges state).

**Why:** With dynamic fan-out (`Send`), LangGraph runs the `"worker"` node
once per `Send`, each as its own execution of the subgraph, completing at
different times. We must not reduce until *all* sections are in — the gate
pattern is the standard LangGraph idiom for "wait for every fanned-out
branch before continuing," since there's no fixed number of edges into
`reducer` to rely on.

## 5. Why Pydantic structured output for orchestrator/evaluator but plain text for worker/reducer

**Why:** Orchestrator and evaluator produce data the graph needs to
*branch on or iterate over* (section list, pass/fail + score) — asking the
model for `with_structured_output(Schema)` removes a whole class of parsing
bugs (bad JSON, missing fields) that would otherwise need defensive
handling. Worker and reducer produce prose that's consumed as-is (markdown
body text); forcing it through a schema would add no safety and would
constrain the model's writing unnecessarily.

## 6. Why `get_llm()` is a function, not a module-level client

**Why:** Tests must run without Ollama installed/running (CI, other
machines). `app/graph/llm.py` exposes a factory function so
`tests/conftest.py` can `monkeypatch.setattr("app.graph.nodes.get_llm", ...)`
and swap in `FakeLLM`, which mimics both the plain-invoke and
`with_structured_output` interfaces `ChatOllama` exposes. All 10 node-level
unit tests run in under 2 seconds with zero network/model dependency.

## 7. Why retries are capped and feedback is carried forward explicitly

**How:** `SectionWorkState.attempt` starts at 1; `prepare_retry` increments
it and stashes `previous_draft`/`previous_feedback` into state before
looping back to `worker`. `route_after_evaluation` forces acceptance once
`attempt >= settings.max_worker_retries` regardless of score.

**Why:** An LLM evaluator can get stuck rejecting a section it will never
rate highly (ambiguous brief, model limitations) — without a hard cap this
becomes an infinite loop burning local compute indefinitely. Carrying the
previous draft + concrete feedback into the next worker prompt (rather than
just re-asking "try again") gives the retry a real chance of fixing the
actual issue instead of regenerating a similar draft blind.

## 8. Why in-memory run registry + FastAPI `BackgroundTasks` instead of a queue

**Why:** This is explicitly MVP scope (see plan doc §6, "Deferred"). A
task queue (Celery/RQ) and a persistent store (Postgres) are the right call
once this needs to survive process restarts or scale past one backend
instance — but for a first working version, `BackgroundTasks` + a
`dict[str, RunRecord]` is zero extra infrastructure and keeps the whole
stack runnable with two `pip install`s and no external services besides
Ollama. `runs.py` isolates this choice behind `RunRegistry`, so swapping the
storage/execution backend later doesn't touch the graph or API route code.

## 9. How live output reaches the Streamlit UI

The MVP keeps the existing polling protocol rather than adding a second
streaming transport. The reducer calls the Ollama model with `llm.stream()`
and sends each text chunk to a `stream_sink` callback supplied through the
LangGraph config. `RunRegistry` appends those chunks to
`RunRecord.final_markdown`, which is already returned by
`GET /blogs/{run_id}`.

The Streamlit app polls that endpoint every two seconds and renders the
accumulated Markdown through one `st.empty()` placeholder. The placeholder
is replaced on each poll, so the preview grows without duplicating earlier
content. The final graph result still replaces the preview before the
download button is shown.

The orchestrator and section branches also publish lightweight progress
events through the same LangGraph configurable context. This sets the total
section count immediately after planning and increments the accepted count
as parallel branches finish, so the UI is informative while workers and
evaluators are still running.

The run record also keeps a human-readable `events` timeline. Nodes append
messages such as "Researching the topic", "Working on ...", "Evaluating ...",
and "Accepted ..." through an `event_sink` callback. The Streamlit activity
panel polls and redraws the latest events, making the graph's execution flow
visible without exposing internal LangGraph state or adding another transport.

This currently streams prose from the final assembly stage. Worker and
evaluator calls still complete their structured work before the reducer
starts; streaming their text directly would require a richer event model
because those calls run in parallel and their outputs should not be merged
into one article preview prematurely.

## 10. Config: why `qwen2.5:3b` as the default model

The application uses the locally installed `qwen2.5:3b` Ollama model by
default. It is instruction-tuned and fast enough for 2-6 sequential/parallel
section calls plus an evaluator call on a laptop. The model is overridable via
`COMEBLOG_OLLAMA_MODEL` in `.env` — swap to another model after pulling it with
`ollama pull`, without changing application code.

## 11. How to run it

```bash
# 1. Ensure Ollama is running and has the configured model
ollama pull qwen2.5:3b

# 2. Backend
cd backend
python -m venv .venv && .venv/Scripts/activate   # PowerShell: .venv\Scripts\Activate.ps1
pip install -e ".[dev]"
cp ../.env.example ../.env   # optional: override model/thresholds
uvicorn app.main:app --reload --port 8000

# 3. UI (separate terminal)
cd ui
pip install -r requirements.txt
streamlit run streamlit_app.py
```

Run tests (no Ollama required):
```bash
cd backend && python -m pytest -q
```

## 12. Validation performed

- `python -m pytest -q` — 10/10 unit tests pass against `FakeLLM`, covering
  every node and both routing branches (`accept` / `retry`, including the
  max-retries-forces-accept edge case).
- End-to-end smoke run via `build_graph().invoke(...)` against a live local
  Ollama model, confirming the full
  `orchestrator → worker/evaluator loop (×N parallel) → reducer → write_markdown`
  pipeline produces a real `.md` file in `output/`.
- FastAPI and Streamlit layers were code-reviewed against the plan's API
  contract (`POST /blogs`, `GET /blogs/{run_id}`) but exercising them live
  requires two running processes; see §11 to run them yourself.

## 13. Known MVP limitations (carried over from the plan, now concrete)

- Process restart loses all run history (in-memory registry).
- No limit on concurrent runs — a second `POST /blogs` while one is
  running will fan out more Ollama calls concurrently; fine for local use,
  not for shared/production deployment.
- No retry/backoff around Ollama connection errors — a dropped connection
  mid-run surfaces as `status: error` with the exception message.
- CORS is wide open (`allow_origins=["*"]`) — acceptable for local dev only.
