from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_prefix="COMEBLOG_", extra="ignore"
    )

    ollama_host: str = "http://localhost:11434"
    ollama_model: str = "qwen2.5:3b"
    evaluator_model: str = "qwen3:4b"
    ollama_temperature: float = 0.4

    output_dir: str = "../output"


settings = Settings()
