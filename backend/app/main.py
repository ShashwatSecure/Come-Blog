import datetime as dt
import logging
import time
import uuid
from contextlib import asynccontextmanager
from typing import Any, Literal

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app import runs, store
from app.config import settings
from app.domain import Article, Length, Tone
from app.logging_config import configure_logging, log_event, logging_context
from app.security import SECURITY_HEADERS, SITE_CSP, rate_limit, require_api_key

configure_logging()


@asynccontextmanager
async def lifespan(_: FastAPI):
    settings.site_path.mkdir(parents=True, exist_ok=True)
    store.rebuild_site()
    log_event(logging.INFO, "startup", site=str(settings.site_path), auth=bool(settings.api_key))
    yield


DESCRIPTION = """
Local-first blog generator. Submit a topic and the service researches it (Wikipedia, Wikimedia Commons, Tavily),
plans and writes a cited article with a local Ollama model, runs deterministic quality gates, and publishes a static
blog under `/site`.

**Typical flow**

1. `POST /preview` (optional): see the research that would be used. No model is called.
2. `POST /blogs`: returns `202` and a job id.
3. Poll `GET /jobs/{id}` until `status` is `done` or `failed`, then open the returned `url`.

**Auth:** when the server sets `COMEBLOG_API_KEY`, send it in the `X-API-Key` header (use *Authorize* above).
Generation and mutation endpoints are rate limited per client IP and return `429` with `Retry-After`.
"""

TAGS = [
    {"name": "System", "description": "Liveness and dependency checks."},
    {"name": "Generation", "description": "Research preview and asynchronous blog generation jobs."},
    {"name": "Posts", "description": "Read, export and delete published posts."},
]

app = FastAPI(
    title="Come-Blog API",
    version="1.0.0",
    description=DESCRIPTION,
    openapi_tags=TAGS,
    lifespan=lifespan,
)
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
    topic: str = Field(min_length=3, max_length=300, description="What the post is about.", examples=["Why small teams need observability"])


class CreateBlogRequest(TopicRequest):
    length: Length = Field("medium", description="short = 3 sections, medium = 4, long = 6.")
    tone: Tone = "conversational"
    audience: str = Field("general readers", min_length=3, max_length=80, description="Who the post is written for.")


class JobResponse(BaseModel):
    id: str = Field(description="Job id to poll at GET /jobs/{id}.")
    status: Literal["queued", "running", "done", "failed"]
    topic: str
    stage: str = Field("", description="Current pipeline stage: research, plan, write, assemble, review, publish or done.")
    message: str = ""
    progress: float = Field(0.0, ge=0, le=1, description="Approximate completion, 0 to 1.")
    events: list[runs.JobEvent] = []
    elapsed_s: float = 0.0
    slug: str | None = Field(None, description="Set once the post is saved.")
    url: str | None = Field(None, description="Relative URL of the published post.")
    error: str | None = None


class ErrorResponse(BaseModel):
    detail: str


class HealthResponse(BaseModel):
    status: Literal["ok"]
    version: str


class MessageResponse(BaseModel):
    message: str


class PreviewSource(BaseModel):
    id: int
    title: str
    url: str
    domain: str = ""
    snippet: str = ""
    provider: str = ""


class PreviewResponse(BaseModel):
    topic: str
    summary: str
    sources: list[PreviewSource]
    images: int = Field(description="Number of candidate open-licensed images found.")
    providers: list[str] = Field(description="Research providers that returned data.")


class PostSummary(BaseModel):
    slug: str
    title: str
    excerpt: str
    tags: list[str]
    status: Literal["published", "needs_review"]
    words: int
    reading_minutes: int
    sources: int
    images: int
    created_at: dt.datetime
    url: str


class LibraryStats(BaseModel):
    posts: int
    words: int
    images: int
    sources: int
    needs_review: int


class PostList(BaseModel):
    stats: LibraryStats
    posts: list[PostSummary]


# Responses shared by routes behind auth / rate limiting, so they appear in the spec.
_AUTH: dict[int | str, dict[str, Any]] = {401: {"model": ErrorResponse, "description": "Missing or invalid X-API-Key."}}
_LIMITED: dict[int | str, dict[str, Any]] = {429: {"model": ErrorResponse, "description": "Rate or queue limit hit; see Retry-After."}}
_NOT_FOUND: dict[int | str, dict[str, Any]] = {404: {"model": ErrorResponse, "description": "No such resource."}}


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


@app.get("/health", tags=["System"], summary="Liveness probe")
def health() -> HealthResponse:
    """Always unauthenticated and cheap; use it for container or load-balancer health checks."""
    return HealthResponse(status="ok", version=app.version)


@app.get(
    "/ollama/check", tags=["System"], summary="Check the local model server",
    dependencies=[Depends(require_api_key), Depends(rate_limit)],
    responses={**_AUTH, **_LIMITED, 503: {"model": ErrorResponse, "description": "Ollama is not reachable or the model is missing."}},
)
def ollama_check() -> MessageResponse:
    """Confirms Ollama is running and the configured writer model responds."""
    try:
        return MessageResponse(message=runs.check_ollama())
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Ollama unavailable: {type(exc).__name__}") from exc


@app.post(
    "/preview", tags=["Generation"], summary="Preview the research for a topic",
    dependencies=[Depends(require_api_key), Depends(rate_limit)],
    responses={**_AUTH, **_LIMITED, 502: {"model": ErrorResponse, "description": "Research providers failed."}},
)
def preview(req: TopicRequest) -> PreviewResponse:
    """Runs only the research step (no language model), so it returns quickly. Results are cached for 15 minutes."""
    try:
        return PreviewResponse.model_validate(runs.preview(req.topic))
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Research failed: {type(exc).__name__}") from exc


@app.post(
    "/blogs", status_code=202, tags=["Generation"], summary="Start generating a blog post",
    dependencies=[Depends(require_api_key), Depends(rate_limit)],
    responses={**_AUTH, **_LIMITED},
)
def create_blog(req: CreateBlogRequest, request: Request) -> JobResponse:
    """Queues a generation job and returns immediately with `202`. Poll `GET /jobs/{id}`.

    Generation takes minutes on a CPU-only machine. If the queue is full the API answers `429` with `Retry-After`.
    """
    try:
        job = runs.get_manager().submit(req.topic.strip(), req.length, req.tone, req.audience.strip(), request.state.request_id)
    except runs.QueueFull:
        raise HTTPException(status_code=429, detail="Generation queue is full; try again shortly", headers={"Retry-After": "30"}) from None
    return _job_response(job)


@app.get(
    "/jobs/{job_id}", tags=["Generation"], summary="Get generation job status",
    dependencies=[Depends(require_api_key)], responses={**_AUTH, **_NOT_FOUND},
)
def get_job(job_id: str) -> JobResponse:
    """Poll every few seconds. `status` ends as `done` (then `url` is set) or `failed` (then `error` is set)."""
    job = runs.get_manager().get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Unknown job")
    return _job_response(job)


@app.get("/posts", tags=["Posts"], summary="List posts", dependencies=[Depends(require_api_key)], responses=_AUTH)
def list_posts() -> PostList:
    """Newest first, with library-wide totals."""
    articles = store.list_articles()
    return PostList(
        stats=LibraryStats(**store.stats(articles)),
        posts=[
            PostSummary(
                slug=a.slug, title=a.title, excerpt=a.excerpt, tags=a.tags, status=a.status,
                words=a.word_count, reading_minutes=a.reading_minutes, sources=len(a.sources),
                images=len(a.images), created_at=a.created_at, url=f"/site/posts/{a.slug}/index.html",
            )
            for a in articles
        ],
    )


@app.get(
    "/posts/{slug}", tags=["Posts"], summary="Get a post as JSON", response_model=Article,
    dependencies=[Depends(require_api_key)], responses={**_AUTH, **_NOT_FOUND},
)
def get_post(slug: str) -> dict:
    """The full article: sections, sources, images, quality report and every generation attempt."""
    article = store.load_article(slug)
    if article is None:
        raise HTTPException(status_code=404, detail="Post not found")
    return article.model_dump(mode="json")


@app.get(
    "/posts/{slug}/markdown", tags=["Posts"], summary="Download a post as Markdown",
    dependencies=[Depends(require_api_key)], responses={**_AUTH, **_NOT_FOUND, 200: {"content": {"text/markdown": {}}}},
    response_class=FileResponse,
)
def get_post_markdown(slug: str) -> FileResponse:
    path = store.posts_dir() / slug / "article.md"
    if store.load_article(slug) is None or not path.is_file():
        raise HTTPException(status_code=404, detail="Post not found")
    return FileResponse(path, media_type="text/markdown", filename=f"{slug}.md")


@app.delete(
    "/posts/{slug}", status_code=204, tags=["Posts"], summary="Delete a post",
    dependencies=[Depends(require_api_key), Depends(rate_limit)], responses={**_AUTH, **_NOT_FOUND, **_LIMITED},
)
def delete_post(slug: str) -> None:
    """Removes the post folder and rebuilds the index, feed and sitemap. This cannot be undone."""
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
