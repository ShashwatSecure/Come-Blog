"""Multi-provider research: Wikipedia + Wikimedia Commons (free) and Tavily (optional).

Every provider fails soft: a network problem degrades the article's sourcing, it never
blocks generation. All HTTP goes through `_get_json` / `_post_json` so tests can stub it.
"""

import html
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import quote

import httpx

from app.config import settings
from app.domain import ImageAsset, ResearchBundle, Source
from app.logging_config import log_event
from app.textutil import clamp_text, significant_tokens

WIKIPEDIA_API = "https://en.wikipedia.org/w/api.php"
COMMONS_API = "https://commons.wikimedia.org/w/api.php"
TAVILY_API = "https://api.tavily.com/search"

_cache: dict[str, tuple[float, ResearchBundle]] = {}
_cache_lock = threading.Lock()
_TAG = re.compile(r"<[^>]+>")


def _client() -> httpx.Client:
    return httpx.Client(
        timeout=settings.http_timeout_s,
        headers={"User-Agent": settings.user_agent},
        follow_redirects=True,
    )


def _get_json(url: str, params: dict) -> dict:
    with _client() as client:
        response = client.get(url, params=params)
        response.raise_for_status()
        return response.json()


def _post_json(url: str, payload: dict, headers: dict | None = None) -> dict:
    with _client() as client:
        response = client.post(url, json=payload, headers=headers)
        response.raise_for_status()
        return response.json()


def keyword_query(topic: str, limit: int = 6) -> str:
    """Strip filler words so encyclopedic search works on phrasing like 'How to reduce X'."""
    seen: list[str] = []
    for token in re.findall(r"[A-Za-z0-9][A-Za-z0-9'-]*", topic):
        if token.lower() in significant_tokens(token) and token.lower() not in seen:
            seen.append(token.lower())
    return " ".join(seen[:limit]) or topic


def _plain(value: str) -> str:
    return html.unescape(_TAG.sub("", value or "")).strip()


# --------------------------------------------------------------------------- Wikipedia


def _wikipedia(topic: str) -> tuple[list[Source], list[ImageAsset]]:
    wanted = significant_tokens(topic)
    for query in dict.fromkeys([keyword_query(topic), topic]):
        data = _get_json(
            WIKIPEDIA_API,
            {
                "action": "query", "format": "json", "formatversion": 2,
                "generator": "search", "gsrsearch": query, "gsrlimit": 4,
                "prop": "extracts|info|pageimages", "exintro": 1, "explaintext": 1,
                "exlimit": "max", "inprop": "url", "piprop": "thumbnail", "pithumbsize": 1200,
            },
        )
        pages = sorted(data.get("query", {}).get("pages", []), key=lambda p: p.get("index", 99))
        sources: list[Source] = []
        images: list[ImageAsset] = []
        for page in pages:
            extract = (page.get("extract") or "").strip()
            title = page.get("title", "")
            if not extract or "may refer to" in extract[:200]:
                continue
            if wanted and not (wanted & significant_tokens(f"{title} {extract[:300]}")):
                continue
            url = page.get("fullurl") or f"https://en.wikipedia.org/wiki/{quote(title.replace(' ', '_'))}"
            sources.append(Source(id=0, title=f"{title} - Wikipedia", url=url,
                                  snippet=clamp_text(extract, 900), provider="wikipedia"))
            thumb = page.get("thumbnail") or {}
            if thumb.get("source") and thumb.get("width", 0) >= 600:
                images.append(ImageAsset(
                    url=thumb["source"], alt=title, credit=f"Wikipedia: {title}",
                    credit_url=url, width=thumb.get("width"), height=thumb.get("height"),
                ))
        if sources:
            return sources, images
    return [], []


# --------------------------------------------------------------------------- Commons


def _commons_images(topic: str) -> list[ImageAsset]:
    data = _get_json(
        COMMONS_API,
        {
            "action": "query", "format": "json", "formatversion": 2,
            "generator": "search", "gsrsearch": f"{keyword_query(topic)} filetype:bitmap",
            "gsrnamespace": 6, "gsrlimit": 10,
            "prop": "imageinfo", "iiprop": "url|size|mime|extmetadata", "iiurlwidth": 1200,
        },
    )
    pages = sorted(data.get("query", {}).get("pages", []), key=lambda p: p.get("index", 99))
    images: list[ImageAsset] = []
    for page in pages:
        info = (page.get("imageinfo") or [{}])[0]
        meta = info.get("extmetadata") or {}
        license_name = _plain((meta.get("LicenseShortName") or {}).get("value", ""))
        if info.get("mime") not in {"image/jpeg", "image/png"}:
            continue
        if (info.get("width") or 0) < 900 or (info.get("height") or 0) < 500:
            continue
        if not license_name or "non-free" in license_name.lower() or "fair use" in license_name.lower():
            continue
        title = re.sub(r"^File:|\.[A-Za-z]{3,4}$", "", page.get("title", "")).replace("_", " ")
        alt = _plain((meta.get("ObjectName") or {}).get("value", "")) or title
        artist = clamp_text(_plain((meta.get("Artist") or {}).get("value", "")), 60) or "Unknown author"
        images.append(ImageAsset(
            url=info.get("thumburl") or info.get("url", ""), alt=clamp_text(alt, 140),
            credit=f"{artist}, {license_name}, via Wikimedia Commons",
            credit_url=info.get("descriptionurl", ""),
            width=info.get("thumbwidth") or info.get("width"),
            height=info.get("thumbheight") or info.get("height"),
        ))
    return images


# --------------------------------------------------------------------------- Tavily


def _tavily(topic: str) -> tuple[str, list[Source]]:
    payload = {
        "query": topic, "search_depth": settings.tavily_search_depth,
        "max_results": settings.tavily_max_results, "include_answer": True,
    }
    data = _post_json(TAVILY_API, payload, {"Authorization": f"Bearer {settings.tavily_api_key}"})
    sources = [
        Source(id=0, title=clamp_text(r.get("title") or "Untitled source", 120), url=r["url"],
               snippet=clamp_text(r.get("content", ""), 900), provider="tavily")
        for r in data.get("results", []) if r.get("url") and r.get("content")
    ]
    return (data.get("answer") or "").strip(), sources


# --------------------------------------------------------------------------- Orchestration


def _dedupe(sources: list[Source]) -> list[Source]:
    unique: dict[str, Source] = {}
    for source in sources:
        unique.setdefault(source.url.split("#")[0].rstrip("/").lower(), source)
    return list(unique.values())


def _safely(label: str, fn, default):
    try:
        return fn()
    except Exception as exc:  # noqa: BLE001 - research must never block generation
        log_event(30, "research_provider_failed", provider=label, error=type(exc).__name__)
        return default


def research(topic: str) -> ResearchBundle:
    """Gather sources, an overview and open-licensed images for `topic` (cached briefly)."""
    key = topic.strip().lower()
    now = time.monotonic()
    with _cache_lock:
        hit = _cache.get(key)
        if hit and now - hit[0] < settings.research_cache_ttl_s:
            log_event(20, "research_cache_hit")
            return hit[1].model_copy(deep=True)

    started = time.perf_counter()
    jobs: dict[str, object] = {}
    with ThreadPoolExecutor(max_workers=3) as pool:
        if settings.wikipedia_enabled:
            jobs["wikipedia"] = pool.submit(_safely, "wikipedia", lambda: _wikipedia(topic), ([], []))
            jobs["commons"] = pool.submit(_safely, "commons", lambda: _commons_images(topic), [])
        if settings.tavily_api_key.strip():
            jobs["tavily"] = pool.submit(_safely, "tavily", lambda: _tavily(topic), ("", []))
        results = {name: future.result() for name, future in jobs.items()}

    wiki_sources, wiki_images = results.get("wikipedia", ([], []))
    answer, tavily_sources = results.get("tavily", ("", []))
    commons_images = results.get("commons", [])

    # Tavily first: it is query-targeted and current; Wikipedia adds stable background.
    merged = _dedupe(tavily_sources + wiki_sources)[: settings.max_sources]
    for index, source in enumerate(merged, start=1):
        source.id = index
    images = list(dict.fromkeys(i.url for i in commons_images + wiki_images))
    by_url = {i.url: i for i in commons_images + wiki_images}
    summary = answer or (clamp_text(wiki_sources[0].snippet, 500) if wiki_sources else "")

    bundle = ResearchBundle(
        topic=topic, summary=summary, sources=merged,
        images=[by_url[u] for u in images][:6],
        providers=sorted({s.provider for s in merged}),
    )
    log_event(20, "research_completed", sources=len(merged), images=len(bundle.images),
              providers=bundle.providers, duration_ms=round((time.perf_counter() - started) * 1000, 1))
    with _cache_lock:
        _cache[key] = (now, bundle.model_copy(deep=True))
    return bundle


def clear_cache() -> None:
    with _cache_lock:
        _cache.clear()
