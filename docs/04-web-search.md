# Web Search Grounding

## What changed

Come-Blog now has an optional Tavily search step before local model analysis.
The search adapter receives the user topic and returns a compact context made
from Tavily's generated answer and the most relevant result snippets. The
orchestrator uses that context to create the existing title, summary, and five
important points. The blog generator then receives the summary and points as it
did before, so the graph shape remains:

```text
topic -> web search -> orchestrator analysis -> generator -> evaluator -> writer
```

The standalone `POST /preview` endpoint uses the same search adapter, which
means the preview shown in Streamlit is grounded by the same current research
source as the subsequent graph run.

## Configuration

Tavily uses an API key from the environment-based settings:

```env
COMEBLOG_TAVILY_API_KEY=your-tavily-api-key
COMEBLOG_TAVILY_SEARCH_DEPTH=advanced
COMEBLOG_TAVILY_MAX_RESULTS=5
```

Get the key from the Tavily dashboard, then place it in the project's `.env`
file. The backend dependency is `tavily-python`, installed with the normal
backend command:

```bash
cd backend
pip install -e "[dev]"
```

Tavily's free tier and limits are subject to its current pricing and account
rules. The application does not require the key to start: when it is absent,
the search step is skipped and the local Ollama flow continues. If Tavily is
temporarily unavailable, the adapter logs the failure and the same fallback is
used. API keys and generated content are not written to logs.

## Implementation details

- `backend/app/graph/search.py` owns the Tavily client call and result shaping.
- `backend/app/graph/nodes.py` calls `search_topic()` at the start of the
  orchestrator node and includes the returned context in its structured prompt.
- `backend/app/runs.py` calls `search_topic()` for the preview endpoint.
- `BlogState.research_context` keeps the raw compact context available in the
  graph result without exposing it in the final Markdown output.
- The adapter imports the Tavily SDK lazily, and the node tests replace it with
  a deterministic stub, so unit tests do not make network requests.

Search snippets are treated as context rather than unquestionable truth. The
local model still writes the final prose, and the evaluator still checks the
result using the existing retry loop.

## Verification

Run the backend tests without an API key:

```bash
cd backend
python -m pytest -q
```

For a live check, configure the key, start Ollama and the backend, then request
a preview:

```bash
curl -X POST http://localhost:8000/preview \
  -H "Content-Type: application/json" \
  -d '{"topic":"How to reduce email overload at work"}'
```