"""Настройки приложения: читаются из переменных окружения и файла .env."""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    """Параметры подключения к LLM и рабочие каталоги."""

    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    llm_base_url: str = "https://api.groq.com/openai/v1"
    llm_api_key: str = ""
    llm_model: str = "openai/gpt-oss-120b"
    llm_reasoning_effort: str = ""
    llm_json_mode: bool = True
    llm_temperature: float = 0.4
    llm_max_tokens: int = 4000
    llm_timeout: float = 90.0
    llm_max_retries: int = 3
    repair_attempts: int = 1
    max_product_chars: int = 20000
    web_host: str = "127.0.0.1"
    web_port: int = 8000
    web_max_upload_mb: int = 50
    web_max_products: int = 10
    web_rate_limit_per_minute: int = 20
    output_dir: Path = PROJECT_ROOT / "output"
    log_dir: Path = PROJECT_ROOT / "logs"
    schemas_dir: Path = PROJECT_ROOT / "schemas"


@lru_cache
def get_settings() -> Settings:
    """Загружает настройки один раз и переиспользует их.

    Returns:
        Объект настроек приложения.
    """
    return Settings()
