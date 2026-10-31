"""Filesystem store: one folder per post under output/site/posts, plus a rebuilt index/feed."""

import json
import shutil
import threading
from pathlib import Path

from app import render
from app.config import settings
from app.domain import Article, ImageAsset
from app.images import download_images
from app.logging_config import log_event

_lock = threading.Lock()


def posts_dir() -> Path:
    return settings.site_path / "posts"


def _unique_slug(slug: str) -> str:
    candidate, n = slug, 2
    while (posts_dir() / candidate).exists():
        candidate = f"{slug}-{n}"
        n += 1
    return candidate


def save_article(article: Article, candidate_images: list[ImageAsset]) -> Article:
    with _lock:
        slug = _unique_slug(article.slug)
        folder = posts_dir() / slug
        try:
            images = download_images(candidate_images, folder)
            article = article.model_copy(update={"slug": slug, "images": images})
            (folder).mkdir(parents=True, exist_ok=True)
            (folder / "article.json").write_text(article.model_dump_json(indent=2), encoding="utf-8")
            (folder / "cover.svg").write_text(render.cover_svg(article), encoding="utf-8")
            (folder / "article.md").write_text(render.to_markdown(article), encoding="utf-8")
            (folder / "index.html").write_text(render.article_page(article), encoding="utf-8")
        except Exception:
            shutil.rmtree(folder, ignore_errors=True)  # never leave a half-written post
            raise
        rebuild_site()
    log_event(20, "article_saved", slug=slug, words=article.word_count, images=len(article.images), status=article.status)
    return article


def load_article(slug: str) -> Article | None:
    path = posts_dir() / slug / "article.json"
    if not path.is_file() or Path(slug).name != slug:
        return None
    return Article.model_validate_json(path.read_text(encoding="utf-8"))


def list_articles() -> list[Article]:
    articles: list[Article] = []
    if posts_dir().is_dir():
        for path in posts_dir().glob("*/article.json"):
            try:
                articles.append(Article.model_validate_json(path.read_text(encoding="utf-8")))
            except Exception:  # noqa: BLE001 - skip a corrupt post, keep the site up
                log_event(30, "article_unreadable", path=path.parent.name)
    return sorted(articles, key=lambda a: a.created_at, reverse=True)


def delete_article(slug: str) -> bool:
    folder = posts_dir() / slug
    if Path(slug).name != slug or not (folder / "article.json").is_file():
        return False
    with _lock:
        shutil.rmtree(folder)
        rebuild_site()
    log_event(20, "article_deleted", slug=slug)
    return True


def rebuild_site() -> None:
    """Rewrite index, feed, sitemap, stylesheet and 404 from the posts on disk."""
    site = settings.site_path
    articles = list_articles()
    (site / "assets").mkdir(parents=True, exist_ok=True)
    (site / "assets" / "style.css").write_text(render.STYLE_CSS, encoding="utf-8")
    (site / "index.html").write_text(render.index_page(articles), encoding="utf-8")
    (site / "feed.xml").write_text(render.rss_feed(articles), encoding="utf-8")
    (site / "sitemap.xml").write_text(render.sitemap(articles), encoding="utf-8")
    (site / "404.html").write_text(render.not_found_page(), encoding="utf-8")
    (site / "stats.json").write_text(json.dumps(stats(articles), indent=2), encoding="utf-8")


def stats(articles: list[Article] | None = None) -> dict:
    articles = list_articles() if articles is None else articles
    return {
        "posts": len(articles),
        "words": sum(a.word_count for a in articles),
        "images": sum(len(a.images) for a in articles),
        "sources": sum(len(a.sources) for a in articles),
        "needs_review": sum(a.status == "needs_review" for a in articles),
    }
