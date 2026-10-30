from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    # values come from environment variables first, then the .env file
    model_config = SettingsConfigDict(env_file=ROOT / ".env", extra="ignore")

    openai_api_key: str

    embed_model: str = "text-embedding-3-small"
    embed_dimension: int = 1536

    qdrant_url: str = ""  # empty means in-memory Qdrant (dev and tests); compose sets http://qdrant:6333
    collection: str = "niural_guide"
    db_path: Path = ROOT / "audit.db"

    guide_path: Path = ROOT / "docs" / "PRODUCT_GUIDE.md"
    chunk_size: int = 300
    chunks_to_fetch: int = 5
    sections_to_return: int = 3
    max_section_chars: int = 3000

    llm_retries: int = 3


@lru_cache
def get_settings() -> Settings:
    return Settings()