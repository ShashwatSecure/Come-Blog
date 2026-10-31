# 02 - Research, images and links

The brief asked for a real blog: images, links, everything. This step makes
sourcing visible and legal.

## Sources and links

- Providers run in parallel and fail soft: `wikipedia` (free), `commons` (free,
  images), `tavily` (optional key, current web results).
- Results are de-duplicated by normalised URL, numbered `[1]..[n]`, and the
  numbers are given to the writer, which is told to cite with `[n]` and never
  invent facts.
- The renderer turns `[n]` into a superscript link to `#source-n`, and the page
  ends with a **Sources** list linking to the original pages (`rel="noopener
  noreferrer"`). Sources that were researched but not cited are labelled
  "(background)" instead of pretending they were used.
- `article.md` converts citations to real links: `[[1](https://...)]`.
- Unknown citation ids (the model inventing `[9]`) are a **blocking** quality
  failure and are dropped from the HTML so they never become dead links.

## Images

| Rule | Why |
|---|---|
| Only `image/jpeg` / `image/png`, at least 900x500 | no icons or thumbnails as heroes |
| License must be present and not "non-free" / "fair use" | publishable without legal risk |
| Credit line `Author, License, via Wikimedia Commons` linking to the file page | attribution requirement of CC licenses |
| Download only from `https://upload.wikimedia.org`, size-capped (2 MB default), magic-byte sniffed | prevents SSRF, huge files and mislabelled content |
| Served from the post folder, not hot-linked | the post still works if the source disappears |
| No photo found -> deterministic generated SVG cover (title + gradient + shapes) | every post still has a designed hero; the title is escaped |

## Wikimedia robot policy (found during live testing)

The first live run got HTTP 403 from Wikipedia and Commons:
`Please respect our robot policy`. Wikimedia blocks clients that do not identify
themselves with contact information. Fix: a `COMEBLOG_CONTACT` setting that is
appended to the User-Agent. Without it, those two providers degrade silently
(logged as `research_provider_failed`) and generation continues with Tavily
sources and the generated cover.

**Not verified live:** Wikipedia/Commons parsing and image download are covered
by unit tests with stubbed HTTP payloads, but have not been exercised against the
real services, because no contact value was configured. Set `COMEBLOG_CONTACT`
and run `scripts/live_run.py` to confirm.

## Tests added

7 research tests: keyword extraction, merge/filter/numbering, caching, total
provider failure, Tavily-first ordering and dedupe, untrusted-host rejection,
image content sniffing.
