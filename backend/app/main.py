import logging
import time
import uuid
from contextlib import asynccontextmanager
from typing import Literal

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app import runs, store
from app.config import settings
from app.domain import Length, Tone
from app.logging_config import configure_logging, log_event, logging_context
from app.security import SECURITY_HEADERS, SITE_CSP, rate_limit, require_api_key

configure_logging()


@asynccontextmanager
async def lifespan(_: FastAPI):
    settings.site_path.mkdir(parents=True, exist_ok=True)
    store.rebuild_site()
    log_event(logging.INFO, "startup", site=str(settings.site_path), auth=bool(settings.api_key))
    yield


app = FastAPI(title="Come-Blog API", version="1.0.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["Content-Type", "X-API-Key", "X-Request-ID"],
)


@app.middleware("http")
async def request_middleware(request: Request, call_next):
    request_id = request.headers.get("x-request-id", "")[:64] or str(uuid.uuid4())
    request.state.request_id = request_id
    started = time.perf_counter()
    with logging_context(request_id=request_id, method=request.method, path=request.url.path):
        try:
            response = await call_next(request)
        except Exception:
            log_event(logging.ERROR, "request_failed", exc_info=True)
            raise
        response.headers["x-request-id"] = request_id
        for key, value in SECURITY_HEADERS.items():
            response.headers.setdefault(key, value)
        if request.url.path.startswith("/site"):
            response.headers.setdefault("Content-Security-Policy", SITE_CSP)
            response.headers.setdefault("Cache-Control", "no-cache")
        log_event(logging.INFO, "request_completed", status_code=response.status_code,
                  duration_ms=round((time.perf_counter() - started) * 1000, 2))
        return response


class TopicRequest(BaseModel):
    topic: str = Field(min_length=3, max_length=300)


class CreateBlogRequest(TopicRequest):
    length: Length = "medium"
    tone: Tone = "conversational"
    audience: str = Field("general readers", min_length=3, max_length=80)


class JobResponse(BaseModel):
    id: str
    status: Literal["queued", "running", "done", "failed"]
    topic: str
    stage: str = ""
    message: str = ""
    progress: float = 0.0
    events: list[runs.JobEvent] = []
    elapsed_s: float = 0.0
    slug: str | None = None
    url: str | None = None
    error: str | None = None


_STAGES = ["research", "plan", "write", "assemble", "review", "publish", "done"]


def _job_response(job: runs.Job) -> JobResponse:
    last = job.events[-1] if job.events else None
    stage = last.stage if last else ""
    progress = 1.0 if job.status == "done" else ((_STAGES.index(stage) + 0.5) / len(_STAGES) if stage in _STAGES else 0.02)
    end = job.finished_at or time.time()
    return JobResponse(
        id=job.id, status=job.status, topic=job.topic, stage=stage, message=last.message if last else "",
        progress=round(min(progress, 0.99) if job.status != "done" else 1.0, 2), events=job.events,
        elapsed_s=round(end - (job.started_at or job.created_at), 1), slug=job.slug,
        url=f"/site/posts/{job.slug}/index.html" if job.slug else None, error=job.error,
    )


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "version": app.version}


@app.get("/ollama/check", dependencies=[Depends(require_api_key), Depends(rate_limit)])
def ollama_check() -> dict[str, str]:
    try:
        return {"message": runs.check_ollama()}
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Ollama unavailable: {type(exc).__name__}") from exc


@app.post("/preview", dependencies=[Depends(require_api_key), Depends(rate_limit)])
def preview(req: TopicRequest) -> dict:
    try:
        return runs.preview(req.topic)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Research failed: {type(exc).__name__}") from exc


@app.post("/blogs", status_code=202, dependencies=[Depends(require_api_key), Depends(rate_limit)])
def create_blog(req: CreateBlogRequest, request: Request) -> JobResponse:
    try:
        job = runs.get_manager().submit(req.topic.strip(), req.length, req.tone, req.audience.strip(), request.state.request_id)
    except runs.QueueFull:
        raise HTTPException(status_code=429, detail="Generation queue is full; try again shortly", headers={"Retry-After": "30"}) from None
    return _job_response(job)


@app.get("/jobs/{job_id}", dependencies=[Depends(require_api_key)])
def get_job(job_id: str) -> JobResponse:
    job = runs.get_manager().get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Unknown job")
    return _job_response(job)


@app.get("/posts", dependencies=[Depends(require_api_key)])
def list_posts() -> dict:
    articles = store.list_articles()
    return {
        "stats": store.stats(articles),
        "posts": [
            {"slug": a.slug, "title": a.title, "excerpt": a.excerpt, "tags": a.tags, "status": a.status,
             "words": a.word_count, "reading_minutes": a.reading_minutes, "sources": len(a.sources),
             "images": len(a.images), "created_at": a.created_at, "url": f"/site/posts/{a.slug}/index.html"}
            for a in articles
        ],
    }


@app.get("/posts/{slug}", dependencies=[Depends(require_api_key)])
def get_post(slug: str) -> dict:
    article = store.load_article(slug)
    if article is None:
        raise HTTPException(status_code=404, detail="Post not found")
    return article.model_dump(mode="json")


@app.get("/posts/{slug}/markdown", dependencies=[Depends(require_api_key)])
def get_post_markdown(slug: str) -> FileResponse:
    path = store.posts_dir() / slug / "article.md"
    if store.load_article(slug) is None or not path.is_file():
        raise HTTPException(status_code=404, detail="Post not found")
    return FileResponse(path, media_type="text/markdown", filename=f"{slug}.md")


@app.delete("/posts/{slug}", status_code=204, dependencies=[Depends(require_api_key), Depends(rate_limit)])
def delete_post(slug: str) -> None:
    if not store.delete_article(slug):
        raise HTTPException(status_code=404, detail="Post not found")


@app.get("/", include_in_schema=False)
def root() -> RedirectResponse:
    return RedirectResponse("/site/index.html")


class SiteFiles(StaticFiles):
    """Serve the generated site from the *current* settings.site_path (resolved per request)."""

    def __init__(self) -> None:
        super().__init__(directory=settings.site_path, html=True, check_dir=False)

    async def get_response(self, path, scope):
        self.all_directories = self.get_directories(settings.site_path, None)
        return await super().get_response(path, scope)


app.mount("/site", SiteFiles(), name="site")
