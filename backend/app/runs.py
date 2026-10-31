"""Background job runner: bounded queue, progress events, per-job status for polling."""

import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from typing import Literal

from langchain_core.messages import HumanMessage
from pydantic import BaseModel, Field

from app import research
from app.config import settings
from app.domain import Article
from app.graph.build import build_graph
from app.graph.llm import get_llm
from app.graph.state import BlogState
from app.logging_config import log_event, logging_context

JobStatus = Literal["queued", "running", "done", "failed"]


class JobEvent(BaseModel):
    at: float
    stage: str
    message: str


class Job(BaseModel):
    id: str
    topic: str
    status: JobStatus = "queued"
    created_at: float = Field(default_factory=time.time)
    started_at: float | None = None
    finished_at: float | None = None
    events: list[JobEvent] = Field(default_factory=list)
    slug: str | None = None
    error: str | None = None


class QueueFull(Exception):
    pass


class JobManager:
    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()
        self._pool = ThreadPoolExecutor(max_workers=settings.max_concurrent_jobs, thread_name_prefix="job")

    def _active(self) -> int:
        return sum(j.status in ("queued", "running") for j in self._jobs.values())

    def submit(self, topic: str, length: str, tone: str, audience: str, request_id: str | None) -> Job:
        with self._lock:
            if self._active() >= settings.max_queued_jobs:
                raise QueueFull
            job = Job(id=uuid.uuid4().hex[:12], topic=topic)
            self._jobs[job.id] = job
            self._trim()
        self._pool.submit(self._run, job.id, BlogState(topic=topic, length=length, tone=tone, audience=audience), request_id)
        log_event(20, "job_queued", job_id=job.id)
        return job

    def _trim(self, keep: int = 200) -> None:
        finished = sorted((j for j in self._jobs.values() if j.status in ("done", "failed")), key=lambda j: j.created_at)
        for old in finished[: max(0, len(finished) - keep)]:
            self._jobs.pop(old.id, None)

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            job = self._jobs.get(job_id)
            return job.model_copy(deep=True) if job else None

    def _event(self, job_id: str, event: dict) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job:
                job.events.append(JobEvent(at=time.time(), stage=event["stage"], message=event["message"]))

    def _run(self, job_id: str, state: BlogState, request_id: str | None) -> None:
        with self._lock:
            job = self._jobs[job_id]
            job.status, job.started_at = "running", time.time()
        started = time.perf_counter()
        with logging_context(run_id=job_id, request_id=request_id):
            log_event(20, "graph_started", topic_length=len(state.topic))
            try:
                result = build_graph().invoke(
                    state.model_copy(update={"started_at": time.time()}),
                    config={"configurable": {
                        "run_id": job_id, "request_id": request_id,
                        "event_sink": lambda e: self._event(job_id, e),
                    }},
                )
                article: Article = result["article"]
                with self._lock:
                    job.status, job.slug, job.finished_at = "done", article.slug, time.time()
                log_event(20, "graph_completed", duration_ms=round((time.perf_counter() - started) * 1000, 1), slug=article.slug)
            except Exception as exc:  # noqa: BLE001 - surface any failure to the polling client
                log_event(40, "graph_failed", exc_info=True)
                with self._lock:
                    job.status, job.finished_at = "failed", time.time()
                    job.error = f"{type(exc).__name__}: {str(exc)[:240]}"


_manager: JobManager | None = None
_manager_lock = threading.Lock()


def get_manager() -> JobManager:
    global _manager
    with _manager_lock:
        if _manager is None:
            _manager = JobManager()
        return _manager


def check_ollama() -> str:
    response = get_llm().invoke([HumanMessage(content="Reply with exactly: Ollama is up.")])
    content = response.content
    return (content if isinstance(content, str) else str(content)).strip()


def preview(topic: str) -> dict:
    """Instant, model-free preview: what research would be used for this topic."""
    bundle = research.research(topic)
    return {
        "topic": topic,
        "summary": bundle.summary,
        "sources": [s.model_dump() for s in bundle.sources],
        "images": len(bundle.images),
        "providers": bundle.providers,
    }
