# 07 - Results: baseline vs now

Measured 2026-10-31 with `scripts/metrics.py` and four real end-to-end runs on
this machine (`qwen2.5:3b` writer, `qwen3:4b` reviewer, CPU, Tavily key present,
Wikipedia/Commons blocked, see below).

## Project metrics

| Metric | Baseline | Now |
|---|---|---|
| Python files | 15 | 30 (22 source, 8 test) |
| Python lines | 629 | 3,109 (2,462 source, 647 test) |
| Tests | 9 passing, **1 failing** | **55 passing**, 0 failing |
| Ruff findings | 3 | 1 (stale `graph/search.py`, see Open items) |
| Docs lines (md) | 752 | 1,225 |

Tests by area: API 10, pipeline 10, quality 8, render 11, research 7, text 9.
The suite runs offline in about 3 s with no Ollama and no network.

## Product behaviour

| Capability | Baseline | Now |
|---|---|---|
| Output | one Markdown paragraph | HTML page + Markdown + JSON + cover art, plus index, RSS, sitemap |
| Article size | ~10 sentences, 1 section | 3-6 sections; measured 286-580 words |
| Sources shown to reader | 0 | 5 per post (measured), linked, numbered, "background" flagged when uncited |
| Links per article | 0 | 5 source links + citation anchors |
| Images | 0 | generated SVG cover on every post; licensed photos supported but **0 downloaded so far** |
| Quality gate | model's own flag | up to 23 deterministic checks + advisory reviewer score |
| Failed posts | silently saved | saved as `needs_review`, badged |
| Rewrites | regenerate whole draft | only failing sections |
| Draft history | 1 (final) | one record per pass |
| Tavily calls per session | 2 | 1 (cached 15 min) |
| Progress events | 0 delivered | delivered per stage via polling |
| Request model | blocks up to 180 s | `202` + job id, queue cap, `429` when full |
| Auth / rate limit / headers | none, CORS `*` | API key, per-IP limit, security headers, explicit CORS |

## Live runs

| # | Topic | Length | Time | Status | Checks | Reviewer | Words | Notes |
|---|---|---|---|---|---|---|---|---|
| 1 | How to improve your sleep | short | 473 s | needs_review | 17/18 | 0.0 | 388 | reviewer bug (06), blank excerpt |
| 2 | same | short | 289 s | needs_review | 15/15 | 0.0 | 286 | reviewer bug (06) |
| 3 | same | short | 491 s | published | 22/22 | 0.7 | 390 | JSON debris in takeaways (fixed after) |
| 4 | Why small teams need observability | medium | 349 s | published | 22/23 | 0.85 | 580 | 1 pass, clean takeaways |

Runs 1-3 are what found the defects fixed along the way. Run 4 is the first run
made entirely after the fixes. One run is an existence proof, not a rate:
**I have only 1 clean post-fix run, so I cannot claim a publish rate.**

Time is dominated by CPU inference: roughly 40-100 s per section and 20-60 s per
reviewer call. Section writing is parallel (2 workers) but the machine is the
bottleneck.

## Defects found by running it for real (not by tests)

1. Wikipedia and Commons return HTTP 403 without a contact in the User-Agent.
   Added `COMEBLOG_CONTACT`.
2. Reviewer scored good posts 0.0 (prompt wording, see 06). Fixed; reviewer
   made advisory because it is still noisy.
3. Blank excerpt shipped as an empty meta description. Fixed with a fallback.
4. Takeaways contained leaked JSON (`{`, `keytakeaway1:`). Fixed, plus a
   blocking check so it cannot ship silently again.

All four passed the unit tests when they were introduced; only live model
output exposed them.

## Open items (honest list)

- **Photos unverified.** No post has a downloaded photo, so the Commons parser,
  license filter and image download have only been tested against stubbed
  responses. Set `COMEBLOG_CONTACT` and run `scripts/live_run.py`.
- **Off-topic sections.** Runs 1-3 each included a "Heart-Healthy" section in a
  sleep article. The relevance check passes it (it mentions sleep). Needs a
  stronger model or embedding similarity.
- **Citation use is weak.** Run 4 cited 1 of 5 sources (`cites_sources`
  check failed, non-blocking). The writer is told to cite but a 3B model often
  does not.
- **Section length is on the low side** for short runs (42-128 words/section).
- **Pages never viewed in a browser.** Verified by HTTP status, structure, and
  string tests only; visual design and contrast are unconfirmed.
- **`backend/app/graph/search.py` is dead code** and is the one remaining lint
  finding. The sandbox refused the delete; remove it by hand.
- **Old posts in `output/site/posts`.** Two posts from runs 1-2 (flagged
  `needs_review`) are still there, and run 3's post carries the takeaway debris.
  Delete them from the Library tab or `DELETE /posts/{slug}`.
- In-memory jobs and rate limiter; no Docker, no CI.
- Nothing was committed or pushed. A copy of the pre-change tree is in
  `_snapshots/pre-production-2026-10-31/` (gitignored).
