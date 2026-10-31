from app.config import settings
from app.logging_config import log_event


def search_topic(topic: str) -> str:
    """Return compact web research for a topic, or an empty string when unavailable."""
    if not settings.tavily_api_key.strip():
        log_event(20, "web_search_skipped", reason="missing_api_key")
        return ""

    try:
        log_event(20, "web_search_started", topic_length=len(topic), search_depth=settings.tavily_search_depth, max_results=settings.tavily_max_results)
        from tavily import TavilyClient

        response = TavilyClient(api_key=settings.tavily_api_key).search(
            query=topic,
            search_depth=settings.tavily_search_depth,
            max_results=settings.tavily_max_results,
            include_answer="advanced",
            include_raw_content=False,
        )
    except Exception:  # noqa: BLE001 - search failures must not block local generation
        log_event(40, "web_search_failed", exc_info=True)
        return ""

    sections: list[str] = []
    answer = response.get("answer")
    if answer:
        sections.append(f"Search summary:\n{answer}")

    for result in response.get("results", []):
        title = result.get("title", "Untitled source")
        content = result.get("content", "").strip()
        url = result.get("url", "")
        if content:
            sections.append(f"Source: {title}\n{content[:1600]}\nURL: {url}")

    context = "\n\n".join(sections)
    log_event(20, "web_search_completed", source_count=len(response.get("results", [])), response_length=len(context))
    return context