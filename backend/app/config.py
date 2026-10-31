from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"), env_prefix="COMEBLOG_", extra="ignore"
    )

    # --- Local models (Ollama) ---
    ollama_host: str = "http://localhost:11434"
    ollama_model: str = "qwen2.5:3b"
    evaluator_model: str = "qwen3:4b"
    ollama_temperature: float = Field(0.4, ge=0.0, le=2.0)
    ollama_timeout_s: float = Field(240.0, gt=0)

    # --- Research ---
    tavily_api_key: str = ""
    tavily_search_depth: Literal["basic", "advanced"] = "advanced"
    tavily_max_results: int = Field(5, ge=1, le=10)
    wikipedia_enabled: bool = True
    max_sources: int = Field(6, ge=1, le=12)
    research_cache_ttl_s: int = Field(900, ge=0)
    http_timeout_s: float = Field(10.0, gt=0)
    # Wikimedia's robot policy requires a descriptive agent WITH contact info,
    # e.g. "Come-Blog/1.0 (https://your.site; you@example.com)". Set COMEBLOG_CONTACT.
    contact: str = ""

    @property
    def user_agent(self) -> str:
        suffix = f" ({self.contact})" if self.contact.strip() else ""
        return f"Come-Blog/1.0{suffix} httpx"
    download_images: bool = True
    max_image_bytes: int = Field(2_000_000, ge=10_000)

    # --- Generation quality ---
    pass_threshold: float = Field(0.7, ge=0.0, le=1.0)
    max_attempts: int = Field(2, ge=1, le=5)
    llm_review: bool = True
    # When true, a reviewer score below pass_threshold blocks publishing. Off by default: the 3-4B
    # reviewer was measured to be too inconsistent to gate on (docs/production/06-reviewer-reliability.md).
    llm_gate: bool = False

    # --- Site / storage ---
    output_dir: str = "../output"
    site_title: str = "Come-Blog"
    site_tagline: str = "Researched, written and illustrated locally."
    author_name: str = "Come-Blog"
    base_url: str = "http://localhost:8000"

    # --- Server / operations ---
    api_key: str = ""
    cors_origins: str = "http://localhost:8501,http://localhost:8000"
    rate_limit_per_minute: int = Field(30, ge=1)
    max_concurrent_jobs: int = Field(1, ge=1, le=8)
    max_queued_jobs: int = Field(10, ge=1)
    trust_proxy_headers: bool = False

    @property
    def output_path(self) -> Path:
        path = Path(self.output_dir)
        return path if path.is_absolute() else (BACKEND_DIR / path).resolve()

    @property
    def site_path(self) -> Path:
        return self.output_path / "site"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


settings = Settings()
