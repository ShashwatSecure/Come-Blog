import time
import uuid

from fastapi import FastAPI, HTTPException
from fastapi import Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import cast

from app.runs import DraftAttempt, check_ollama, generate_preview, run_blog_graph
from app.logging_config import configure_logging, logger

configure_logging()
app = FastAPI(title="Come-Blog API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # MVP only - tighten before any real deployment
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def request_logging_middleware(request: Request, call_next):
    request_id = request.headers.get("x-request-id", str(uuid.uuid4()))
    request.state.request_id = request_id
    started = time.perf_counter()
    logger.info(
        "request_started",
        extra={"event": "request_started", "request_id": request_id, "method": request.method, "path": request.url.path},
    )
    try:
        response = await call_next(request)
    except Exception:
        logger.exception(
            "request_failed",
            extra={"event": "request_failed", "request_id": request_id, "method": request.method, "path": request.url.path, "duration_ms": round((time.perf_counter() - started) * 1000, 2)},
        )
        raise
    duration_ms = round((time.perf_counter() - started) * 1000, 2)
    response.headers["x-request-id"] = request_id
    logger.info(
        "request_completed",
        extra={"event": "request_completed", "request_id": request_id, "method": request.method, "path": request.url.path, "status_code": response.status_code, "duration_ms": duration_ms},
    )
    return response


class CreateBlogRequest(BaseModel):
    topic: str = Field(min_length=3, max_length=300)


class TopicRequest(BaseModel):
    topic: str = Field(min_length=3, max_length=300)


@app.get("/ollama/check")
def ollama_check() -> dict[str, str]:
    try:
        return {"message": check_ollama()}
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.post("/preview")
def preview(req: TopicRequest) -> dict[str, str]:
    try:
        return {"topic": req.topic, "preview": generate_preview(req.topic)}
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.post("/blogs")
def create_blog(req: TopicRequest, request: Request) -> dict[str, object]:
    try:
        result = run_blog_graph(req.topic, request_id=request.state.request_id)
        attempts = cast(list[DraftAttempt], result["attempts"])
        result["attempts"] = [attempt.model_dump() for attempt in attempts]
        return result
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}
