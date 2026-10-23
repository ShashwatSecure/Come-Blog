from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from app.runs import check_ollama, generate_blog, generate_preview

app = FastAPI(title="Come-Blog API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # MVP only - tighten before any real deployment
    allow_methods=["*"],
    allow_headers=["*"],
)


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
def create_blog(req: TopicRequest) -> dict[str, object]:
    try:
        markdown, output_path, attempts = generate_blog(req.topic)
        return {
            "topic": req.topic,
            "markdown": markdown,
            "output_path": output_path,
            "attempts": [attempt.model_dump() for attempt in attempts],
        }
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}
