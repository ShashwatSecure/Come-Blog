# Come-Blog Progress

## 1. Starting intuition

- Build a local-first blog writer using Ollama, FastAPI, Streamlit, and Markdown output.
- Begin with a richer agent design: orchestrator, parallel workers, evaluator, reducer, and retry loops.
- Keep models local and free so the system can be tested without API keys or cloud cost.

## 2. First implementation: LangGraph MVP

- Implemented a LangGraph pipeline:
  - `orchestrator` planned sections.
  - `worker` drafted each section.
  - `evaluator` scored sections and supplied feedback.
  - Failed sections retried with feedback.
  - `reducer` assembled the final article.
  - `write_markdown` saved the result to `output/*.md`.
- Added dynamic fan-out and fan-in for independent section branches.
- Added Pydantic state models and structured LLM output for plans and evaluations.
- Added a fake LLM test seam so the graph could be tested without Ollama.
- Result: **10/10 unit tests passed**.

## 3. First real-world issue: too much complexity too early

- Repeated live runs did not produce Markdown reliably.
- Ollama itself was tested directly with `qwen2.5:3b`:
  - Model availability: passed.
  - Plain-text generation: passed.
  - JSON generation: passed.
  - Streaming: passed.
- The request remained `running` before producing events or a file.
- Conclusion: the main problem was not an outdated Ollama installation; the graph and background execution path made failures difficult to isolate.

## 4. Simplification for a reliable baseline

- Removed the active LangGraph path from the user-facing flow.
- Replaced it with three direct interactions:
  1. Check whether Ollama is responding.
  2. Generate a short 3-4 line topic preview.
  3. Ask whether the user wants a complete blog.
- The blog call generates a simple 10-sentence draft and saves a Markdown file.
- Added explicit endpoints:
  - `GET /ollama/check`
  - `POST /preview`
  - `POST /blogs`
- Verified the simplified path on a fresh backend:
  - Health endpoint: **HTTP 200**.
  - Ollama check: **HTTP 200**, returned `Ollama is up.`.
  - Preview endpoint: **HTTP 200** with useful topic content.

## 5. Level-up: writer plus independent evaluator

- Kept `qwen2.5:3b` as the writer.
- Added `qwen3:4b` as a separate evaluator model.
- The evaluator returns structured data:
  - score from `0.0` to `1.0`;
  - concise feedback for the writer.
- Current quality threshold: **0.7**.
- Current maximum: **3 draft iterations**.
- The flow is now:

```text
Topic
  -> first draft
  -> evaluator score + feedback
  -> revise with feedback when score < 0.7
  -> repeat, maximum 3 drafts
  -> save and download final Markdown
```

- The UI displays every draft, its score, and its feedback before showing the final blog.
- The final API response includes the complete attempt history.

## 6. Practical model tuning

- `qwen3:4b` initially timed out during evaluation when its reasoning mode was enabled on CPU.
- Direct requests to that model exceeded **90 seconds**.
- Disabled unnecessary reasoning for the evaluator through the LangChain Ollama client.
- Evaluator response time then dropped to approximately **20.6 seconds** for a live call.
- This was a concrete example of improving the system through measurement rather than assuming the model or Ollama installation was broken.

## 7. Current verified state

- Full review-loop API smoke test: **HTTP 200**.
- Successful sample result:
  - attempts: **1**;
  - evaluator score: **0.95**;
  - final Markdown: non-empty;
  - output path: valid `.md` file.
- Regression suite: **10 tests passed**.
- Compile checks: passed.
- The system is now easier to observe, debug, and extend than the original graph-first flow.

## 8. Current limits and next sensible steps

- The API call is still synchronous; long model calls block until the loop finishes.
- Draft history is returned after generation rather than streamed live during each evaluator call.
- The evaluator model must be installed locally and may be CPU-bound.
- The next improvement should be bounded progress reporting for each draft/evaluation stage, followed by stronger response schemas and integration tests for forced retry cases.

## 9. Return to LangGraph with a simpler flow

- Reintroduced LangGraph as the active `/blogs` execution path, keeping the
  design intentionally sequential:

```text
START
  -> orchestrator
  -> generator
  -> evaluator
  -> writer
  -> END
```

- The orchestrator now returns a blog title, a concise 3-4 line summary, and
  exactly five strong points that should be covered by the article.
- The generator uses the topic and five points to write a simple 10-sentence
  draft.
- The evaluator can route the draft back to the generator with feedback, with a
  hard maximum of three attempts.
- The writer saves the accepted result as a downloadable Markdown file.
- Dynamic fan-out, parallel workers, reducer logic, and section subgraphs are
  deliberately not part of this first working graph version.

## 10. Production-oriented backend logging

- Added structured JSON logging for HTTP requests, graph runs, and individual
  graph nodes.
- Each request and graph run records a correlation ID, start/completion event,
  status, duration, and failure traceback where applicable.
- Node logs record the node name and execution duration, making slow Ollama
  calls and failed graph stages visible without logging prompts or generated
  article content.
- Request IDs are propagated from FastAPI into the LangGraph configuration so
  HTTP, graph, and node events can be correlated.

## 11. Evaluator robustness fixes

- Local evaluator models sometimes returned percentage scores such as `100`
  instead of decimal scores such as `1.0`.
- Added score normalization at the shared state model boundary, so values like
  `100` and `70` become `1.0` and `0.7` while the internal threshold remains
  `0.7`.
- Unified the evaluator output model used by the node and `BlogState` to avoid
  Pydantic validation failures between graph steps.
- Tightened the evaluator prompt to request a decimal score from `0.0` to `1.0`.

## 12. Markdown output format

- Removed YAML frontmatter from generated Markdown files.
- The writer now produces exactly one title heading followed by the article
  body:

```markdown
# Article title

Article content...
```

- The writer also defensively removes frontmatter, duplicate leading titles,
  and surrounding whitespace if an upstream result includes them.

## 13. Current verified state

- Backend regression suite: **11 tests passed**.
- Score normalization check: `BlogEvaluation(score=100, ...)` produces `1.0`.
- Markdown writer test: passed with the title-and-content-only format.
- Graph compilation: successful as a `CompiledStateGraph`.
- Live generation still requires Ollama and both configured local models.
