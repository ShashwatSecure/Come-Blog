import datetime as dt
import os

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field
from slugify import slugify

from app.config import settings
from app.graph.llm import get_llm
from app.graph.state import (
    BlogEvaluation,
    BlogState,
)


class SimpleTopicAnalysis(BaseModel):
    title: str
    summary: str
    strong_points: list[str] = Field(min_length=5, max_length=5)


def _emit(config: dict | None, message: str) -> None:
    event_sink = (config or {}).get("configurable", {}).get("event_sink")
    if event_sink:
        event_sink(message)


def analyze_topic_node(state: BlogState, config: dict | None = None) -> dict:
    _emit(config, "Analyzing the topic and identifying the five essential points...")
    result: SimpleTopicAnalysis = get_llm().with_structured_output(SimpleTopicAnalysis).invoke(
        [
            SystemMessage(content="You are a precise topic analyst and blog editor."),
            HumanMessage(content=(
                f"Topic: {state.topic}\n\nReturn a concise 3-4 line summary and exactly five "
                "strong, distinct points that must be present in a useful blog, essay, or paragraph "
                "about this topic. Make each point concrete and relevant."
            )),
        ]
    )
    return {"blog_title": result.title, "summary": result.summary, "strong_points": result.strong_points}


def generate_blog_node(state: BlogState, config: dict | None = None) -> dict:
    _emit(config, f"Generating the blog draft (attempt {state.attempt} of 3)...")
    instruction = "Write a simple blog of exactly 10 sentences about the topic. Cover every strong point. Be clear, useful, and concrete. Return only the blog text."
    if state.evaluation and state.evaluation.feedback:
        instruction += f" Improve the previous draft using this feedback: {state.evaluation.feedback}"
    response = get_llm().invoke([
        SystemMessage(content=instruction),
        HumanMessage(content=f"Topic: {state.topic}\nStrong points:\n- " + "\n- ".join(state.strong_points)),
    ])
    return {"draft": response.content.strip()}


def evaluate_blog_node(state: BlogState, config: dict | None = None) -> dict:
    _emit(config, "Evaluating the draft and checking all five points...")
    evaluator = get_llm(model=settings.evaluator_model, reasoning=False).with_structured_output(BlogEvaluation)
    result: BlogEvaluation = evaluator.invoke([
        SystemMessage(content=(
            "Evaluate this simple 10-sentence blog for relevance, clarity, usefulness, coverage "
            "of all five strong points, and sentence count. Return score as a decimal from 0.0 to "
            "1.0, never as a percentage. Pass only if it is ready."
        )),
        HumanMessage(content=(
            f"Topic: {state.topic}\nStrong points:\n- " + "\n- ".join(state.strong_points)
            + f"\n\nDraft:\n{state.draft}"
        )),
    ])
    return {"evaluation": result}


def route_after_blog_evaluation(state: BlogState) -> str:
    if state.evaluation and (state.evaluation.passed or state.attempt >= 3):
        return "writer"
    return "retry"


def prepare_blog_retry_node(state: BlogState, config: dict | None = None) -> dict:
    _emit(config, "The draft needs improvement; sending evaluator feedback back to the generator...")
    return {"attempt": state.attempt + 1}

# ---------------------------------------------------------------------------
# Writer
# ---------------------------------------------------------------------------


def write_markdown_node(state: BlogState, config: dict | None = None) -> dict:
    now = dt.datetime.now(dt.timezone.utc)
    slug = slugify(state.blog_title or state.topic)[:60]
    filename = f"{slug}-{now.strftime('%Y%m%d%H%M%S')}.md"

    output_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", settings.output_dir))
    os.makedirs(output_dir, exist_ok=True)
    path = os.path.join(output_dir, filename)

    final_markdown = (state.final_markdown or state.draft).strip()
    if final_markdown.startswith("---"):
        _, _, final_markdown = final_markdown.partition("---")
        _, _, final_markdown = final_markdown.partition("---")
        final_markdown = final_markdown.strip()
    title = state.blog_title or state.topic
    heading = f"# {title}"
    if final_markdown.casefold().startswith(heading.casefold()):
        final_markdown = final_markdown[len(heading):].lstrip()
    full_doc = f"{heading}\n\n{final_markdown}\n"

    with open(path, "w", encoding="utf-8") as f:
        f.write(full_doc)

    _emit(config, "Saved the completed Markdown article.")
    return {"final_markdown": full_doc, "output_path": path}
