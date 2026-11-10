"""Background job runner: bounded queue, progress events, per-job status for polling."""

import logging
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from typing import Literal

from langchain_core.messages import HumanMessage
from langgraph.types import Command
from pydantic import BaseModel, Field

from app import research
from app.config import settings
from app.domain import Article
from app.graph.build import build_graph, forget_run
from app.graph.llm import get_llm
from app.graph.state import BlogState
from app.logging_config import log_event, logging_context

JobStatus = Literal["queued", "running", "awaiting_input", "done", "failed"]
InputKind = Literal["plan", "review"]
# Actions each pause accepts.
ALLOWED_ACTIONS: dict[str, set[str]] = {"plan": {"continue"}, "review": {"rewrite", "publish"}}


class JobEvent(BaseModel):
    at: float
    stage: str
    message: str


class PendingInput(BaseModel):
    kind: InputKind = Field(description="plan: approve/edit the outline. review: act on the evaluator's feedback.")
    payload: dict = Field(default_factory=dict, description="What the pipeline produced and is asking you about.")


class Job(BaseModel):
    id: str
    topic: str
    interactive: bool = False
    status: JobStatus = "queued"
    created_at: float = Field(default_factory=time.time)
    started_at: float | None = None
    finished_at: float | None = None
    events: list[JobEvent] = Field(default_factory=list)
    pending: PendingInput | None = None
    slug: str | None = None
    error: str | None = None


class QueueFull(Exception):
    pass


class NotAwaitingInput(Exception):
    pass


class JobManager:
    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()
        self._pool = ThreadPoolExecutor(max_workers=settings.max_concurrent_jobs, thread_name_prefix="job")

    def _active(self) -> int:
        # Paused jobs hold checkpointed state, so they count toward the queue limit too.
        return sum(j.status in ("queued", "running", "awaiting_input") for j in self._jobs.values())

    def submit(self, topic: str, length: str, tone: str, audience: str, request_id: str | None, interactive: bool = False) -> Job:
        with self._lock:
            if self._active() >= settings.max_queued_jobs:
                raise QueueFull
            job = Job(id=uuid.uuid4().hex[:12], topic=topic, interactive=interactive)
            self._jobs[job.id] = job
            self._trim()
        state = BlogState(topic=topic, length=length, tone=tone, audience=audience, interactive=interactive)
        self._pool.submit(self._run, job.id, state, request_id)
        log_event(logging.INFO, "job_queued", job_id=job.id, interactive=interactive)
        return job

    def resume(self, job_id: str, reply: dict, request_id: str | None) -> Job:
        """Hand a person's decision back to a paused job. Raises KeyError, NotAwaitingInput or ValueError."""
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                raise KeyError(job_id)
            if job.status != "awaiting_input" or job.pending is None:
                raise NotAwaitingInput
            kind = job.pending.kind
            action = reply.get("action")
            if action not in ALLOWED_ACTIONS[kind]:
                raise ValueError(f"'{action}' is not valid at the {kind} step; use one of {sorted(ALLOWED_ACTIONS[kind])}")
            if kind == "review" and action == "rewrite" and not job.pending.payload.get("can_rewrite", False):
                raise ValueError("The rewrite limit is reached; the draft can only be published")
            if kind != "plan" and reply.get("plan"):
                raise ValueError("An outline can only be edited at the plan step")
            job.status, job.pending = "running", None
            job.events.append(JobEvent(at=time.time(), stage=kind, message=_describe_reply(kind, reply)))
            snapshot = job.model_copy(deep=True)
        self._pool.submit(self._run, job_id, Command(resume=reply), request_id)
        log_event(logging.INFO, "job_resumed", job_id=job_id, kind=kind, action=action)
        return snapshot

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

    def _run(self, job_id: str, graph_input: BlogState | Command, request_id: str | None) -> None:
        with self._lock:
            job = self._jobs[job_id]
            job.status = "running"
            job.started_at = job.started_at or time.time()
            interactive = job.interactive
        if isinstance(graph_input, BlogState):
            graph_input = graph_input.model_copy(update={"started_at": time.time()})
        started = time.perf_counter()
        with logging_context(run_id=job_id, request_id=request_id):
            log_event(logging.INFO, "graph_resumed" if isinstance(graph_input, Command) else "graph_started", topic_length=len(job.topic))
            try:
                graph = build_graph(checkpointed=True) if interactive else build_graph()
                result = graph.invoke(
                    graph_input,
                    config={"configurable": {
                        "thread_id": job_id, "run_id": job_id, "request_id": request_id,
                        "event_sink": lambda e: self._event(job_id, e),
                    }},
                )
                interrupts = result.get("__interrupt__") if isinstance(result, dict) else None
                if interrupts:
                    payload = interrupts[0].value
                    with self._lock:
                        job.status, job.pending = "awaiting_input", PendingInput(kind=payload["kind"], payload=payload)
                    self._event(job_id, {"stage": payload["kind"], "message": _WAITING[payload["kind"]]})
                    log_event(logging.INFO, "graph_paused", kind=payload["kind"])
                    return
                article: Article = result["article"]
                with self._lock:
                    job.status, job.slug, job.finished_at = "done", article.slug, time.time()
                log_event(logging.INFO, "graph_completed", duration_ms=round((time.perf_counter() - started) * 1000, 1), slug=article.slug)
            except Exception as exc:  # noqa: BLE001 - surface any failure to the polling client
                log_event(logging.ERROR, "graph_failed", exc_info=True)
                with self._lock:
                    job.status, job.finished_at = "failed", time.time()
                    job.error = f"{type(exc).__name__}: {str(exc)[:240]}"
            if interactive:
                forget_run(job_id)


_WAITING = {
    "plan": "Waiting for you to approve or edit the outline.",
    "review": "Waiting for your call on the evaluator's feedback: rewrite or publish.",
}


def _describe_reply(kind: str, reply: dict) -> str:
    if kind == "plan":
        return "You edited the outline." if reply.get("plan") else "You approved the outline."
    if reply.get("action") == "publish":
        return "You chose to publish this draft."
    points = reply.get("feedback_points")
    if points is None:
        return "You asked for a rewrite with the evaluator's feedback."
    return f"You asked for a rewrite with {len(points)} feedback point(s)."


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
