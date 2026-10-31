"""Generate one real article end-to-end (needs Ollama running) and print measurements.

Usage (repo root):  backend/.venv/Scripts/python.exe scripts/live_run.py "topic" [short|medium|long]
Runs from backend/ so relative settings resolve the same as the server.
"""

import json
import sys
import time
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent / "backend"
sys.path.insert(0, str(BACKEND))

from app.config import settings  # noqa: E402
from app.graph.build import build_graph  # noqa: E402
from app.graph.state import BlogState  # noqa: E402
from app.logging_config import configure_logging  # noqa: E402


def main() -> None:
    topic = sys.argv[1] if len(sys.argv) > 1 else "How to improve your sleep"
    length = sys.argv[2] if len(sys.argv) > 2 else "short"
    configure_logging()
    import logging

    logging.getLogger().setLevel(logging.WARNING)
    t0 = time.time()
    stamps: list[tuple[float, str]] = []

    def sink(event: dict) -> None:
        stamps.append((time.time() - t0, f"{event['stage']}: {event['message']}"))
        print(f"[{time.time() - t0:6.1f}s] {event['stage']:9} {event['message']}", flush=True)

    result = build_graph().invoke(
        BlogState(topic=topic, length=length, started_at=t0),
        config={"configurable": {"event_sink": sink}},
    )
    article = result["article"]
    summary = {
        "topic": topic, "length": length, "seconds": round(time.time() - t0, 1),
        "slug": article.slug, "status": article.status, "words": article.word_count,
        "sections": len(article.sections), "sources": len(article.sources),
        "cited_sources": len(article.cited_source_ids()), "images": len(article.images),
        "checks": f"{article.quality.checks_passed}/{article.quality.checks_total}",
        "llm_score": article.quality.llm_score, "attempts": len(article.attempts),
        "post_dir": str(settings.site_path / "posts" / article.slug),
    }
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
