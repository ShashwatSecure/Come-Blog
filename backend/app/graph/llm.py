"""Single place that constructs the Ollama chat model.

Kept as a function (not inlined at call sites) so tests can monkeypatch it
to return a fake/stub model instead of hitting a real Ollama server.

Clients are cached per temperature and reused across calls. Worker/evaluator
branches for different sections run concurrently (LangGraph thread pool);
constructing a fresh ChatOllama -> httpx.Client -> ssl.create_default_context()
on every call is not thread-safe on this stack (observed: concurrent
create_default_context() calls raising FileNotFoundError on Windows/Python
3.14) and is wasteful besides. A small cache keyed by temperature sidesteps
both problems since all workers share the same handful of temperature values.
"""

import threading

from langchain_ollama import ChatOllama

from app.config import settings
from app.logging_config import log_event

_cache: dict[tuple[str, float, bool | None], ChatOllama] = {}
_lock = threading.Lock()


def get_llm(
    temperature: float | None = None,
    model: str | None = None,
    reasoning: bool | None = None,
) -> ChatOllama:
    temp = settings.ollama_temperature if temperature is None else temperature
    selected_model = settings.ollama_model if model is None else model
    cache_key = (selected_model, temp, reasoning)
    if cache_key not in _cache:
        with _lock:
            if cache_key not in _cache:  # re-check after waiting for another thread
                _cache[cache_key] = ChatOllama(
                    base_url=settings.ollama_host,
                    model=selected_model,
                    temperature=temp,
                    reasoning=reasoning,
                    client_kwargs={"timeout": settings.ollama_timeout_s},
                )
                log_event(20, "llm_client_created", model=selected_model, temperature=temp, reasoning=reasoning)
    else:
        log_event(10, "llm_client_reused", model=selected_model, temperature=temp, reasoning=reasoning)
    return _cache[cache_key]
