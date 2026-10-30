from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    # values come from environment variables first, then the .env file
    model_config = SettingsConfigDict(env_file=ROOT / ".env", extra="ignore")

    openai_api_key: str

    llm_model: str = "gpt-5-nano"  # cheapest OpenAI model for now; swap for something stronger later
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

    today: str = "2026-09-28"  # the dataset is built as though this is today; "overdue" depends on it
    max_tool_rounds: int = 6  # the dynamic agent stops asking for tools after this many rounds

    llm_retries: int = 3
    # the router makes the decision everything else depends on, so it gets a stronger model than the agents.
    # gpt-5-nano was inconsistent on "unsupported" (3 of 6 for the wallet question); gpt-5-mini was 5 of 5 even at minimal
    router_model: str = "gpt-5-mini"
    router_reasoning_first: str = "minimal"
    router_reasoning_retry: str = "low"

    # the auditor judges whole conversations after they end, so it can afford a stronger model and more thought
    auditor_model: str = "gpt-5-mini"
    auditor_reasoning_first: str = "low"
    auditor_reasoning_retry: str = "medium"

    llm_reasoning_first: str = "low"  # first attempt: light reasoning ("minimal" gave empty answers)
    llm_reasoning_retry: str = "medium"  # retries: reasoning on


@lru_cache
def get_settings() -> Settings:
    return Settings()