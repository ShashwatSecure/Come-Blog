"""Static-site rendering: safe Markdown -> HTML, article/index pages, RSS, sitemap.

Everything user- or model-derived is HTML-escaped before any markup is added, and
links are restricted to http(s), so a hostile model output cannot inject script.
"""

import datetime as dt
import html
import json
import re
from email.utils import format_datetime

from app.config import settings
from app.domain import Article, ImageAsset

esc = html.escape

# --------------------------------------------------------------------------- markdown


_LINK = re.compile(r"\[([^\]]+)\]\((https?://[^\s)]+)\)")
_CITE = re.compile(r"\[(\d{1,2})\](?!\()")
_BOLD = re.compile(r"\*\*(.+?)\*\*")
_ITALIC = re.compile(r"(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])")
_CODE = re.compile(r"`([^`]+)`")


def inline(text: str, valid_ids: set[int] | None = None) -> str:
    out = esc(text, quote=True)
    out = _CODE.sub(r"<code>\1</code>", out)
    out = _BOLD.sub(r"<strong>\1</strong>", out)
    out = _ITALIC.sub(r"<em>\1</em>", out)
    out = _LINK.sub(lambda m: f'<a href="{m.group(2)}" rel="noopener noreferrer" target="_blank">{m.group(1)}</a>', out)

    def cite(match: re.Match) -> str:
        n = int(match.group(1))
        if valid_ids is not None and n not in valid_ids:
            return ""
        return f'<sup class="cite"><a href="#source-{n}" aria-label="Source {n}">{n}</a></sup>'

    return _CITE.sub(cite, out)


def markdown_to_html(md: str, valid_ids: set[int] | None = None) -> str:
    blocks: list[str] = []
    paragraph: list[str] = []
    items: list[str] = []
    list_tag = ""

    def flush_paragraph() -> None:
        if paragraph:
            blocks.append(f"<p>{inline(' '.join(paragraph), valid_ids)}</p>")
            paragraph.clear()

    def flush_list() -> None:
        nonlocal list_tag
        if items:
            body = "".join(f"<li>{inline(i, valid_ids)}</li>" for i in items)
            blocks.append(f"<{list_tag}>{body}</{list_tag}>")
            items.clear()
        list_tag = ""

    for raw in md.splitlines():
        line = raw.strip()
        bullet = re.match(r"^[-*•]\s+(.*)", line)
        numbered = re.match(r"^\d+[.)]\s+(.*)", line)
        quote = re.match(r"^>\s?(.*)", line)
        if not line:
            flush_paragraph()
            flush_list()
        elif bullet or numbered:
            flush_paragraph()
            tag = "ul" if bullet else "ol"
            if list_tag and list_tag != tag:
                flush_list()
            list_tag = tag
            items.append((bullet or numbered).group(1))
        elif quote:
            flush_paragraph()
            flush_list()
            blocks.append(f"<blockquote>{inline(quote.group(1), valid_ids)}</blockquote>")
        else:
            flush_list()
            paragraph.append(line)
    flush_paragraph()
    flush_list()
    return "\n".join(blocks)


def plain_markdown(md: str) -> str:
    """Markdown body for article.md: keep citation markers, they map to the Sources list."""
    return md.strip()


# --------------------------------------------------------------------------- css

STYLE_CSS = """
:root{
  --bg:#fbfaf7;--surface:#ffffff;--ink:#1c1b19;--muted:#6b665e;--line:#e8e4db;
  --accent:#2f5bea;--accent-ink:#ffffff;--soft:#eef2ff;--shadow:0 1px 2px rgba(20,18,10,.05),0 8px 28px rgba(20,18,10,.07);
  --radius:16px;--measure:68ch;
  --serif:Georgia,"Iowan Old Style","Palatino Linotype",Palatino,serif;
  --sans:system-ui,-apple-system,"Segoe UI",Roboto,"Helvetica Neue",Arial,sans-serif;
}
@media (prefers-color-scheme:dark){:root{
  --bg:#121211;--surface:#1b1b19;--ink:#ecebe6;--muted:#a09b90;--line:#2c2b27;
  --accent:#8aa4ff;--accent-ink:#0d1020;--soft:#1d2233;--shadow:0 1px 2px rgba(0,0,0,.4),0 10px 30px rgba(0,0,0,.35);
}}
*{box-sizing:border-box}
html{scroll-behavior:smooth;-webkit-text-size-adjust:100%}
body{margin:0;background:var(--bg);color:var(--ink);font:17px/1.7 var(--sans)}
a{color:var(--accent);text-underline-offset:3px}
img{max-width:100%;height:auto;display:block}
.skip{position:absolute;left:-999px}.skip:focus{left:12px;top:12px;background:var(--surface);padding:8px 12px;border-radius:8px;z-index:9}
.wrap{width:min(1080px,100% - 40px);margin-inline:auto}
.site-header{border-bottom:1px solid var(--line);background:color-mix(in srgb,var(--bg) 88%,transparent);backdrop-filter:blur(10px);position:sticky;top:0;z-index:5}
.site-header .wrap{display:flex;align-items:center;justify-content:space-between;height:60px}
.brand{font:700 1.1rem var(--sans);letter-spacing:-.01em;color:var(--ink);text-decoration:none;display:flex;gap:10px;align-items:center}
.brand i{width:26px;height:26px;border-radius:8px;background:linear-gradient(135deg,var(--accent),#c04bd6);display:inline-block}
.nav a{margin-left:18px;color:var(--muted);text-decoration:none;font-size:.92rem}.nav a:hover{color:var(--ink)}
.progress{position:fixed;top:0;left:0;height:3px;width:0;background:var(--accent);z-index:10}
.hero{padding:56px 0 28px}
.hero h1,.post-head h1{font:700 clamp(2rem,5vw,3.3rem)/1.12 var(--serif);letter-spacing:-.02em;margin:.2em 0}
.hero p{color:var(--muted);font-size:1.15rem;max-width:56ch;margin:0}
.grid{display:grid;gap:24px;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));padding:12px 0 72px}
.card{background:var(--surface);border:1px solid var(--line);border-radius:var(--radius);overflow:hidden;box-shadow:var(--shadow);transition:transform .18s ease,box-shadow .18s ease;display:flex;flex-direction:column}
.card:hover{transform:translateY(-3px)}
.card a.cover{display:block;aspect-ratio:16/9;background-size:cover;background-position:center}
.card .body{padding:18px 20px 22px;display:flex;flex-direction:column;gap:8px;flex:1}
.card h2{font:700 1.28rem/1.25 var(--serif);margin:0}.card h2 a{color:inherit;text-decoration:none}
.card p{margin:0;color:var(--muted);font-size:.96rem}
.meta{display:flex;flex-wrap:wrap;gap:6px 14px;color:var(--muted);font-size:.85rem}
.tags{display:flex;gap:8px;flex-wrap:wrap}
.tag{background:var(--soft);color:var(--accent);padding:2px 10px;border-radius:99px;font-size:.78rem;font-weight:600;text-decoration:none}
.badge{background:#fff3cd;color:#7a5b00;padding:2px 10px;border-radius:99px;font-size:.78rem;font-weight:600}
.empty{padding:64px 0;text-align:center;color:var(--muted)}
.post-head{padding:44px 0 20px;max-width:820px}
.post-head .sub{font-size:1.25rem;color:var(--muted);margin:.4em 0 1em}
.byline{display:flex;gap:14px;align-items:center;color:var(--muted);font-size:.9rem;flex-wrap:wrap}
.figure-hero{margin:8px 0 8px;border-radius:var(--radius);overflow:hidden;box-shadow:var(--shadow)}
.figure-hero img{width:100%;max-height:520px;object-fit:cover}
.gradient-hero{height:260px;border-radius:var(--radius)}
figcaption{font-size:.8rem;color:var(--muted);padding:8px 2px}
.layout{display:grid;grid-template-columns:minmax(0,1fr) 240px;gap:56px;padding-bottom:40px}
@media(max-width:900px){.layout{grid-template-columns:1fr}.toc{display:none}}
.toc{position:sticky;top:84px;align-self:start;font-size:.9rem;border-left:2px solid var(--line);padding-left:16px}
.toc h3{font:700 .72rem var(--sans);letter-spacing:.08em;text-transform:uppercase;color:var(--muted);margin:0 0 10px}
.toc a{display:block;color:var(--muted);text-decoration:none;padding:4px 0}.toc a:hover,.toc a.on{color:var(--accent)}
article.prose{max-width:var(--measure);font:1.12rem/1.78 var(--serif)}
.prose h2{font:700 1.7rem/1.25 var(--sans);letter-spacing:-.015em;margin:2.2em 0 .5em;scroll-margin-top:84px}
.prose p{margin:0 0 1.15em}.prose ul,.prose ol{padding-left:1.3em;margin:0 0 1.2em}.prose li{margin:.35em 0}
.prose blockquote{margin:1.4em 0;padding:.2em 1.2em;border-left:4px solid var(--accent);color:var(--muted);font-style:italic}
.prose code{background:var(--soft);padding:1px 6px;border-radius:6px;font-size:.9em}
.prose figure{margin:1.8em 0}.prose figure img{border-radius:12px;width:100%}
sup.cite a{font:600 .7rem var(--sans);text-decoration:none;background:var(--soft);padding:1px 5px;border-radius:6px;margin-left:1px}
.takeaways{background:var(--soft);border-radius:var(--radius);padding:20px 24px;margin:0 0 2em;font-family:var(--sans)}
.takeaways h2{font-size:1rem;margin:0 0 .5em;text-transform:uppercase;letter-spacing:.07em}
.takeaways ul{margin:0;padding-left:1.2em}.takeaways li{margin:.3em 0;font-size:1rem}
.sources{max-width:var(--measure);border-top:1px solid var(--line);margin-top:3em;padding-top:1.4em;font-family:var(--sans)}
.sources h2{font-size:1.1rem;margin:0 0 .6em}.sources ol{padding-left:1.4em;margin:0}.sources li{margin:.5em 0;font-size:.93rem}
.sources .dom{color:var(--muted)}
.quality{max-width:var(--measure);margin:2em 0 0;font:.85rem var(--sans);color:var(--muted);background:var(--surface);border:1px solid var(--line);border-radius:12px;padding:12px 16px}
.quality b{color:var(--ink)}
.site-footer{border-top:1px solid var(--line);padding:28px 0 48px;color:var(--muted);font-size:.88rem}
.site-footer .wrap{display:flex;justify-content:space-between;gap:16px;flex-wrap:wrap}
@media print{.site-header,.toc,.progress,.site-footer{display:none}.layout{display:block}body{background:#fff;color:#000}}
@media(prefers-reduced-motion:reduce){*{transition:none!important;scroll-behavior:auto!important}}
"""

# --------------------------------------------------------------------------- shared chrome


def _gradient(hue: int) -> str:
    return (f"background:linear-gradient(135deg,hsl({hue} 70% 52%),hsl({(hue + 48) % 360} 72% 44%) 55%,"
            f"hsl({(hue + 110) % 360} 65% 38%))")


def cover_svg(article: Article) -> str:
    """Deterministic generated cover art (no network, no text injection: title is escaped)."""
    h = article.hue
    c1, c2, c3 = f"hsl({h} 72% 52%)", f"hsl({(h + 50) % 360} 74% 46%)", f"hsl({(h + 120) % 360} 66% 36%)"
    seed = int(article.slug.encode().hex()[:8] or "0", 16) if article.slug else 0
    shapes = []
    for i in range(7):
        x = (seed * (i + 3) * 37) % 1200
        y = (seed * (i + 5) * 91) % 560
        r = 60 + (seed * (i + 2) * 13) % 190
        opacity = 0.10 + ((seed >> i) % 5) * 0.035
        shapes.append(f'<circle cx="{x}" cy="{y}" r="{r}" fill="#fff" fill-opacity="{opacity:.2f}"/>')
    words = article.title.split()
    lines, line = [], ""
    for word in words:
        if len(line) + len(word) + 1 > 26 and line:
            lines.append(line)
            line = word
        else:
            line = f"{line} {word}".strip()
    lines.append(line)
    text = "".join(
        f'<tspan x="72" dy="{0 if i == 0 else 62}">{esc(t)}</tspan>' for i, t in enumerate(lines[:3])
    )
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1200 630" role="img" '
        f'aria-label="{esc(article.title)}"><defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1">'
        f'<stop offset="0" stop-color="{c1}"/><stop offset=".55" stop-color="{c2}"/><stop offset="1" stop-color="{c3}"/>'
        f'</linearGradient></defs><rect width="1200" height="630" fill="url(#g)"/>{"".join(shapes)}'
        '<rect x="72" y="72" width="64" height="8" rx="4" fill="#fff" fill-opacity=".85"/>'
        f'<text x="72" y="{300 - 31 * (len(lines[:3]) - 1)}" fill="#fff" font-family="Georgia,serif" font-weight="700" font-size="54">{text}</text>'
        f'<text x="72" y="566" fill="#fff" fill-opacity=".85" font-family="system-ui,sans-serif" font-size="26">{esc(settings.site_title)}</text></svg>'
    )


def _page(title: str, body: str, *, description: str, root: str, canonical: str = "", extra_head: str = "",
          image: str = "", kind: str = "website", script: str = "") -> str:
    og_image = f'<meta property="og:image" content="{esc(image)}">' if image else ""
    canon = f'<link rel="canonical" href="{esc(canonical)}">' if canonical else ""
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{esc(title)}</title>
<meta name="description" content="{esc(description)}">
{canon}
<meta property="og:title" content="{esc(title)}">
<meta property="og:description" content="{esc(description)}">
<meta property="og:type" content="{kind}">
<meta name="twitter:card" content="summary_large_image">
{og_image}
<link rel="alternate" type="application/rss+xml" title="{esc(settings.site_title)}" href="{root}feed.xml">
<link rel="stylesheet" href="{root}assets/style.css">
{extra_head}
</head>
<body>
<a class="skip" href="#main">Skip to content</a>
<div class="progress" id="progress"></div>
<header class="site-header"><div class="wrap">
  <a class="brand" href="{root}index.html"><i></i>{esc(settings.site_title)}</a>
  <nav class="nav"><a href="{root}index.html">All posts</a><a href="{root}feed.xml">RSS</a></nav>
</div></header>
<main id="main">
{body}
</main>
<footer class="site-footer"><div class="wrap">
  <span>&copy; {dt.datetime.now(dt.UTC).year} {esc(settings.site_title)}. {esc(settings.site_tagline)}</span>
  <span>Written by local AI models. Every claim links to its source.</span>
</div></footer>
{script}
</body>
</html>
"""


_PROGRESS_JS = """<script>
(function(){var p=document.getElementById('progress');if(!p)return;
function f(){var h=document.documentElement;var s=h.scrollTop/(h.scrollHeight-h.clientHeight||1);p.style.width=Math.min(100,s*100)+'%'}
addEventListener('scroll',f,{passive:true});f();
var links=[].slice.call(document.querySelectorAll('.toc a'));
if('IntersectionObserver' in window&&links.length){var io=new IntersectionObserver(function(es){es.forEach(function(e){
if(e.isIntersecting){links.forEach(function(l){l.classList.toggle('on',l.getAttribute('href')==='#'+e.target.id)})}})},{rootMargin:'-20% 0px -70% 0px'});
document.querySelectorAll('.prose h2[id]').forEach(function(h){io.observe(h)})}})();
</script>"""


def _date(article: Article) -> str:
    return article.created_at.strftime("%b %d, %Y").replace(" 0", " ")


def _hero_image(article: Article) -> ImageAsset | None:
    return next((i for i in article.images if i.filename), None)


def _figure(image: ImageAsset, cls: str = "") -> str:
    credit = esc(image.credit)
    if image.credit_url.startswith("http"):
        credit = f'<a href="{esc(image.credit_url)}" rel="noopener noreferrer" target="_blank">{credit}</a>'
    return (f'<figure class="{cls}"><img src="{esc(image.filename)}" alt="{esc(image.alt)}" loading="lazy" '
            f'width="{image.width or 1200}" height="{image.height or 675}"><figcaption>{credit}</figcaption></figure>')


# --------------------------------------------------------------------------- article page


def article_page(article: Article) -> str:
    ids = {s.id for s in article.sources}
    hero = _hero_image(article)
    extras = [i for i in article.images if i.filename and i is not hero]
    toc = "".join(f'<a href="#{esc(s.id)}">{esc(s.heading)}</a>' for s in article.sections)

    sections_html: list[str] = []
    for index, section in enumerate(article.sections):
        figure = ""
        if extras and index in (1, 3) and extras:
            figure = _figure(extras.pop(0))
        sections_html.append(
            f'<h2 id="{esc(section.id)}">{esc(section.heading)}</h2>\n'
            f"{markdown_to_html(section.body_md, ids)}\n{figure}"
        )

    takeaways = ""
    if article.takeaways:
        takeaways = ('<aside class="takeaways"><h2>Key takeaways</h2><ul>'
                     + "".join(f"<li>{esc(t)}</li>" for t in article.takeaways) + "</ul></aside>")
    closing = f'<h2 id="wrap-up">Wrap-up</h2>\n{markdown_to_html(article.closing, ids)}' if article.closing else ""
    if closing:
        toc += '<a href="#wrap-up">Wrap-up</a>'

    sources = ""
    if article.sources:
        cited = article.cited_source_ids()
        rows = "".join(
            f'<li id="source-{s.id}"><a href="{esc(s.url)}" rel="noopener noreferrer" target="_blank">{esc(s.title)}</a> '
            f'<span class="dom">- {esc(s.domain)}{"" if s.id in cited else " (background)"}</span></li>'
            for s in article.sources
        )
        sources = f'<section class="sources" aria-labelledby="src-h"><h2 id="src-h">Sources</h2><ol>{rows}</ol></section>'

    q = article.quality
    quality = (
        f'<div class="quality"><b>Editorial checks:</b> {q.checks_passed}/{q.checks_total} automated checks passed'
        + (f" &middot; reviewer score <b>{q.llm_score:.2f}</b>" if q.llm_score is not None else "")
        + f" &middot; {len(article.attempts)} writing pass{'es' if len(article.attempts) != 1 else ''}"
        + (f" &middot; model {esc(article.model)}" if article.model else "")
        + "</div>"
    )
    badge = '<span class="badge">Needs human review</span>' if article.status == "needs_review" else ""
    tags = "".join(f'<a class="tag" href="../../index.html#{esc(t)}">#{esc(t)}</a>' for t in article.tags)
    cover = (_figure(hero, "figure-hero") if hero else
             '<figure class="figure-hero"><img class="generated-cover" src="cover.svg" width="1200" height="630" '
             f'alt="Generated cover art for {esc(article.title)}"></figure>')

    body = f"""
<div class="wrap">
  <header class="post-head">
    <div class="tags">{tags}{badge}</div>
    <h1>{esc(article.title)}</h1>
    {f'<p class="sub">{esc(article.subtitle)}</p>' if article.subtitle else ''}
    <div class="byline"><span>By {esc(settings.author_name)}</span><span>{_date(article)}</span>
      <span>{article.reading_minutes} min read</span><span>{article.word_count:,} words</span></div>
  </header>
  {cover}
  <div class="layout">
    <article class="prose">
      {takeaways}
      {chr(10).join(sections_html)}
      {closing}
      {sources}
      {quality}
    </article>
    <nav class="toc" aria-label="Table of contents"><h3>On this page</h3>{toc}</nav>
  </div>
</div>"""

    canonical = f"{settings.base_url.rstrip('/')}/site/posts/{article.slug}/"
    ld = json.dumps({
        "@context": "https://schema.org", "@type": "BlogPosting", "headline": article.title,
        "description": article.excerpt, "datePublished": article.created_at.isoformat(),
        "wordCount": article.word_count, "keywords": article.tags,
        "author": {"@type": "Person", "name": settings.author_name},
        "image": [f"{canonical}{hero.filename}"] if hero else [],
        "citation": [s.url for s in article.sources],
    }).replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
    return _page(
        f"{article.title} | {settings.site_title}", body, description=article.excerpt, root="../../",
        canonical=canonical, kind="article", image=f"{canonical}{hero.filename}" if hero else "",
        extra_head=f'<script type="application/ld+json">{ld}</script>', script=_PROGRESS_JS,
    )


# --------------------------------------------------------------------------- index


def _card(article: Article) -> str:
    hero = _hero_image(article)
    cover_file = hero.filename if hero else "cover.svg"
    cover_style = f"background-image:url('posts/{esc(article.slug)}/{esc(cover_file)}')"
    tags = "".join(f'<span class="tag">#{esc(t)}</span>' for t in article.tags[:3])
    badge = '<span class="badge">Needs review</span>' if article.status == "needs_review" else ""
    return f"""<article class="card" data-tags="{esc(' '.join(article.tags))}">
  <a class="cover" style="{cover_style}" href="posts/{esc(article.slug)}/index.html" aria-label="{esc(article.title)}"></a>
  <div class="body">
    <div class="tags">{tags}{badge}</div>
    <h2><a href="posts/{esc(article.slug)}/index.html">{esc(article.title)}</a></h2>
    <p>{esc(article.excerpt)}</p>
    <div class="meta"><span>{_date(article)}</span><span>{article.reading_minutes} min read</span><span>{len(article.sources)} sources</span></div>
  </div>
</article>"""


def index_page(articles: list[Article]) -> str:
    if articles:
        grid = f'<div class="grid">{"".join(_card(a) for a in articles)}</div>'
    else:
        grid = '<div class="empty"><h2>No posts yet</h2><p>Generate your first article from the Come-Blog app.</p></div>'
    body = f"""<div class="wrap">
  <section class="hero"><h1>{esc(settings.site_title)}</h1><p>{esc(settings.site_tagline)}</p></section>
  {grid}
</div>"""
    return _page(settings.site_title, body, description=settings.site_tagline, root="",
                 canonical=settings.base_url.rstrip("/") + "/site/")


def not_found_page() -> str:
    body = '<div class="wrap"><section class="hero"><h1>Page not found</h1><p><a href="index.html">Back to all posts</a></p></section></div>'
    return _page("Not found | " + settings.site_title, body, description="Page not found", root="")


# --------------------------------------------------------------------------- feeds


def rss_feed(articles: list[Article]) -> str:
    base = settings.base_url.rstrip("/") + "/site"
    items = "".join(
        f"<item><title>{esc(a.title)}</title><link>{base}/posts/{a.slug}/index.html</link>"
        f"<guid>{base}/posts/{a.slug}/index.html</guid><pubDate>{format_datetime(a.created_at)}</pubDate>"
        f"<description>{esc(a.excerpt)}</description></item>"
        for a in articles[:30]
    )
    return (f'<?xml version="1.0" encoding="UTF-8"?><rss version="2.0"><channel><title>{esc(settings.site_title)}</title>'
            f"<link>{base}/index.html</link><description>{esc(settings.site_tagline)}</description>{items}</channel></rss>")


def sitemap(articles: list[Article]) -> str:
    base = settings.base_url.rstrip("/") + "/site"
    urls = [f"<url><loc>{base}/index.html</loc></url>"] + [
        f"<url><loc>{base}/posts/{a.slug}/index.html</loc><lastmod>{a.created_at.date().isoformat()}</lastmod></url>"
        for a in articles
    ]
    return f'<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{"".join(urls)}</urlset>'


# --------------------------------------------------------------------------- markdown export


def to_markdown(article: Article) -> str:
    """Portable Markdown with real links: citations become footnote-style links to sources."""
    by_id = {s.id: s for s in article.sources}

    def link_citations(text: str) -> str:
        return _CITE.sub(lambda m: f"[[{m.group(1)}]({by_id[int(m.group(1))].url})]" if int(m.group(1)) in by_id else "", text)

    hero = _hero_image(article)
    lines = [f"# {article.title}", ""]
    if article.subtitle:
        lines += [f"*{article.subtitle}*", ""]
    lines += [f"_{_date(article)} · {article.reading_minutes} min read · {', '.join('#' + t for t in article.tags)}_", ""]
    if hero:
        lines += [f"![{hero.alt}]({hero.filename})", f"*{hero.credit}*", ""]
    if article.takeaways:
        lines += ["## Key takeaways", "", *[f"- {t}" for t in article.takeaways], ""]
    for section in article.sections:
        lines += [f"## {section.heading}", "", link_citations(plain_markdown(section.body_md)), ""]
    if article.closing:
        lines += ["## Wrap-up", "", link_citations(plain_markdown(article.closing)), ""]
    if article.sources:
        lines += ["## Sources", "", *[f"{s.id}. [{s.title}]({s.url})" for s in article.sources], ""]
    return "\n".join(lines).rstrip() + "\n"
