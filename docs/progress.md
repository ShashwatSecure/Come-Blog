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
