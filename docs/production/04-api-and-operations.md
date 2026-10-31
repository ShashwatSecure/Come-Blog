# 04 - API, security and operations

## From a blocking call to jobs

Baseline: `POST /blogs` blocked for up to 180 s and returned everything at once.

| Endpoint | Purpose |
|---|---|
| `GET /health` | liveness (always open) |
| `GET /ollama/check` | model reachability |
| `POST /preview` | research preview (sources, summary, image count); no model needed |
| `POST /blogs` -> `202 {id}` | queue a generation job |
| `GET /jobs/{id}` | status, stage, progress 0-1, last events, elapsed, final URL, error |
| `GET /posts`, `GET /posts/{slug}`, `GET /posts/{slug}/markdown` | library |
| `DELETE /posts/{slug}` | remove a post and rebuild the site |
| `/site/...` | the published blog (static files) |

`POST /blogs` accepts `length` (short/medium/long), `tone`, `audience`.

## Job manager

- Bounded worker pool (`COMEBLOG_MAX_CONCURRENT_JOBS`, default 1, since one
  local GPU/CPU serves both models).
- Queue cap (`COMEBLOG_MAX_QUEUED_JOBS`) returns `429 + Retry-After` instead of
  growing without limit.
- Finished jobs are trimmed to the most recent 200.
- Failures return `ExceptionType: message` truncated to 240 characters, never a
  traceback.

## Security

| Control | Detail |
|---|---|
| API key | `COMEBLOG_API_KEY`; constant-time compare; all routes except `/health` and the static site |
| Rate limit | sliding window per client IP, `Retry-After` header; proxy headers only trusted when `COMEBLOG_TRUST_PROXY_HEADERS=true` |
| CORS | explicit origin list, methods and headers (baseline was `*`) |
| Headers | `nosniff`, `X-Frame-Options`, `Referrer-Policy`, `Permissions-Policy`; CSP on the generated site |
| Input | topic 3-300 chars; `length`/`tone` are enums; slugs are validated against path traversal |
| Output | every model/user-derived string HTML-escaped; links limited to http(s); JSON-LD escapes `<`, `>`, `&` so a hostile title cannot close its script tag |
| SSRF | images fetched only from `upload.wikimedia.org` over HTTPS, streamed with a size cap |
| Secrets | the Tavily key is sent in an `Authorization` header and never logged |

## Reliability

- Every external dependency degrades instead of failing: research providers,
  reviewer model, planner schema, wrap-up schema, image downloads.
- Half-written posts are removed on error; a corrupt `article.json` is skipped
  in listings rather than taking the site down.
- Duplicate titles get `-2`, `-3` slugs.
- Ollama client timeout is configurable (`COMEBLOG_OLLAMA_TIMEOUT_S`, 240 s).

## Known gaps (not done)

- Job state and the rate limiter are in memory; a restart loses running jobs and
  a multi-process deployment would need a shared store (Redis).
- No container image or CI definition was added.
- The `CSP` allows inline script/style because the page uses a small inline
  script and inline styles; a nonce-based policy is the next hardening step.
