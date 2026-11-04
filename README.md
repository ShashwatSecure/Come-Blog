# Come-Blog

A local-first blog generator. Give it a topic and it researches, plans, writes,
reviews and publishes a real blog post: designed HTML page, cited sources with
links, licensed images with credits, RSS, sitemap and a Markdown export. The
models run on your machine through Ollama.

## What you get per post

| File | Purpose |
|---|---|
| `index.html` | The article page: table of contents, reading progress, dark mode, print styles, SEO and JSON-LD |
| `article.md` | Portable Markdown with citations as real links |
| `article.json` | Full data: sections, sources, quality report, every writing pass |
| `cover.svg` / `image-N.jpg` | Generated cover art and/or downloaded open-licensed photos with credit lines |

The site lives in `output/site/` (`index.html` card grid, `feed.xml`, `sitemap.xml`)
and is plain static files, so it can be hosted anywhere.

## How it works

```
research -> plan -> write sections -> quality gates -> reviewer -> publish
                         ^                                  |
                         +---- rewrite failing sections <---+  (bounded)
```

See [`docs/production/`](docs/production/) for the design notes and measured results.

## Architecture

```mermaid
flowchart LR
    UI["Streamlit UI<br/>:8501"] -->|"HTTP + X-API-Key"| API["FastAPI<br/>:8000"]
    API -->|"POST /blogs -> 202"| Q["In-memory job queue<br/>bounded worker pool"]
    Q --> P
    subgraph P["LangGraph pipeline"]
        direction LR
        R[research] --> PL[plan] --> W[write sections] --> QG[quality gates] --> RV[reviewer] --> PU[publish]
        RV -. "rewrite weakest section (bounded)" .-> W
    end
    R <-->|"search, images"| EXT["Wikipedia, Commons, Tavily (optional)"]
    PL & W & RV <-->|"prompts"| OL["Ollama<br/>writer + reviewer models"]
    PU --> OUT[("output/site/<br/>posts/slug/index.html, article.md, article.json, images<br/>index.html, feed.xml, sitemap.xml")]
    API -->|"GET /site/*"| OUT
    UI -.->|"GET /jobs/id (poll)"| API
```

The API accepts a job and returns immediately; a worker runs the pipeline and the UI polls
for progress. Everything the pipeline produces is plain files under `output/`, which the API
also serves at `/site/`.

## Setup

Requires Python 3.11+ and [Ollama](https://ollama.com).

```bash
ollama pull qwen2.5:3b      # writer
ollama pull qwen3:4b        # reviewer

cd backend
python -m venv .venv
.venv\Scripts\activate       # PowerShell; use source .venv/bin/activate on macOS/Linux
pip install -e ".[dev]"
cd ../ui && pip install -r requirements.txt
```

Copy `.env.example` to `.env` and set at least:

- `COMEBLOG_CONTACT` - a URL or email. **Required** for Wikipedia/Commons: Wikimedia
  blocks clients that do not identify themselves.
- `COMEBLOG_TAVILY_API_KEY` - optional, adds current web results.

## Run

```bash
cd backend && uvicorn app.main:app --port 8000     # API + the published site
cd ui && streamlit run streamlit_app.py            # create and manage posts
```

- Create posts in Streamlit (http://localhost:8501), pick length, tone and audience.
- Read the blog at http://localhost:8000/site/index.html.

Generation on small CPU-bound models takes minutes; the UI shows live progress.

## API

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/health` | Liveness |
| `GET` | `/ollama/check` | Model reachability |
| `POST` | `/preview` | Research preview (sources, summary) |
| `POST` | `/blogs` | Queue a job, returns `202` and a job id |
| `GET` | `/jobs/{id}` | Status, stage, progress, events, resulting URL |
| `GET` | `/posts`, `/posts/{slug}`, `/posts/{slug}/markdown` | Library |
| `DELETE` | `/posts/{slug}` | Delete a post |

Set `COMEBLOG_API_KEY` to require an `X-API-Key` header on everything except `/health`.

## Configuration

All settings use the `COMEBLOG_` prefix; see `.env.example` for the full list
(models, research providers, quality threshold, attempts, site branding, rate
limits, CORS).

## Tests

```bash
cd backend
python -m pytest -q          # no Ollama and no network needed
python -m ruff check app tests
python ../scripts/metrics.py # project metrics used in docs/production
```

Real end-to-end run (needs Ollama): `python ../scripts/live_run.py "your topic" short`

## Limits

- Job state and the rate limiter are in memory (single process).
- Small local models can drift off-topic; the reviewer loop contains this but
  posts that miss the bar are marked **needs review** rather than hidden.
- CI runs lint and the offline test suite on every push and pull request (`.github/workflows/ci.yml`).
