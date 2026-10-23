# Come-Blog

A simple local blog writer powered by Ollama.

Come-Blog lets you enter a topic, see a short preview, generate a first draft, review it with a second local model, and download the final blog as a Markdown file.

## How It Works

```text
Enter a topic
    |
Check Ollama
    |
Generate a 3-4 line preview
    |
Choose: generate the complete blog
    |
Writer creates a draft
    |
Evaluator scores the draft and gives feedback
    |
Writer revises it when the score is below 0.7
    |
Stop after a good score or after 3 drafts
    |
Download the final .md file
```

The two local models have separate jobs:

- **Writer:** `qwen2.5:3b`
- **Evaluator:** `qwen3:4b`

The evaluator runs without reasoning mode because this keeps scoring faster on a CPU-based machine.

## What You Need

- Python 3.11 or newer
- Ollama
- The two local models:

```bash
ollama pull qwen2.5:3b
ollama pull qwen3:4b
```

Make sure Ollama is running before starting the application. Its default address is `http://localhost:11434`.

## Setup

### 1. Install backend dependencies

From the project root:

```bash
cd backend
python -m venv .venv
```

Activate the environment:

**Git Bash:**

```bash
source .venv/Scripts/activate
```

**PowerShell:**

```powershell
.venv\Scripts\Activate.ps1
```

Install the backend and development dependencies:

```bash
pip install -e ".[dev]"
```

### 2. Install UI dependencies

Open a second terminal:

```bash
cd ui
pip install -r requirements.txt
```

## Run the App

Start the backend from the project root:

```bash
uvicorn app.main:app --reload --port 8000
```

Start the Streamlit interface in another terminal:

```bash
cd ui
streamlit run streamlit_app.py
```

Open the URL shown by Streamlit, usually:

```text
http://localhost:8501
```

## Using the Interface

1. Enter a topic.
2. Click **Check Ollama**.
3. Click **Get Topic Preview**.
4. Click **Yes, generate the blog**.
5. Review each draft, its evaluator score, and its feedback.
6. Download the final Markdown file.

Generated files are saved under `output/` with a topic-based name and timestamp.

## API Endpoints

The FastAPI backend exposes four small endpoints:

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/health` | Confirm that the backend is running |
| `GET` | `/ollama/check` | Confirm that the configured writer model responds |
| `POST` | `/preview` | Generate a short topic preview |
| `POST` | `/blogs` | Generate, evaluate, revise, and save a blog |

Example request:

```bash
curl -X POST http://localhost:8000/preview \
  -H "Content-Type: application/json" \
  -d "{\"topic\":\"How to reduce email overload at work\"}"
```

The `/blogs` response contains:

- the topic;
- the final Markdown body;
- the saved output path;
- every draft attempt with its score and feedback.

## Configuration

Configuration is loaded from `.env` using the `COMEBLOG_` prefix.

| Variable | Default | Meaning |
|---|---|---|
| `COMEBLOG_OLLAMA_HOST` | `http://localhost:11434` | Ollama server address |
| `COMEBLOG_OLLAMA_MODEL` | `qwen2.5:3b` | Writer model |
| `COMEBLOG_EVALUATOR_MODEL` | `qwen3:4b` | Evaluation model |
| `COMEBLOG_OLLAMA_TEMPERATURE` | `0.4` | Writer/evaluator temperature |
| `COMEBLOG_EVALUATOR_PASS_THRESHOLD` | `0.7` | Score required to stop revising |
| `COMEBLOG_MAX_DRAFT_ITERATIONS` | `3` | Maximum number of drafts |
| `COMEBLOG_OUTPUT_DIR` | `../output` | Markdown output directory |

Example `.env`:

```env
COMEBLOG_OLLAMA_MODEL=qwen2.5:3b
COMEBLOG_EVALUATOR_MODEL=qwen3:4b
COMEBLOG_EVALUATOR_PASS_THRESHOLD=0.7
COMEBLOG_MAX_DRAFT_ITERATIONS=3
```

## Tests

The unit tests use a fake LLM, so they do not need Ollama:

```bash
cd backend
python -m pytest -q
```

Current verified baseline: **10 tests passed**.

## Project Structure

```text
Come-Blog/
├── backend/
│   ├── app/
│   │   ├── main.py          # FastAPI routes
│   │   ├── config.py        # Environment-based settings
│   │   ├── runs.py          # Blog generation and review loop
│   │   └── graph/llm.py     # Cached Ollama model factory
│   ├── tests/               # Unit tests
│   └── pyproject.toml
├── ui/
│   ├── streamlit_app.py     # Interactive interface
│   └── requirements.txt
├── docs/
│   └── progress.md          # Project progression and evidence
└── output/                  # Generated Markdown files
```

## Current Scope

This is a local MVP. It intentionally has:

- no login or multi-user support;
- no database or run history;
- synchronous blog generation;
- no web search or external factual grounding;
- no cloud deployment.

The project is being built incrementally: first make the local path reliable, then add more sophisticated orchestration only when the simpler flow is stable.
