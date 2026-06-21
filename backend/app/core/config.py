"""
app/core/config.py
------------------
Backend settings loaded from environment variables.

Docker Compose is the source of runtime configuration for the backend. Compose
loads values from the root `.env` file and injects them into the backend
container environment. Do not add another backend runtime config file.
"""

from functools import lru_cache

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        case_sensitive=False,
        extra="ignore",
    )

    # ── App ───────────────────────────────────────────────────────────────
    app_name: str = "RLALab AI Research Assistant"
    app_env: str = "development"  # 'development' | 'production'
    log_level: str = "INFO"
    cors_origins: list[str] = ["http://localhost:3000"]
    app_public_url: str = "http://localhost:3000"

    # ── Database ──────────────────────────────────────────────────────────
    database_url: str = "postgresql+asyncpg://postgres:postgres@db:5432/rlalab_ai"

    # ── Auth ──────────────────────────────────────────────────────────────
    secret_key: str = "CHANGE_ME_IN_PRODUCTION"
    access_token_expire_minutes: int = 480
    invitation_token_expire_hours: int = 168

    # ── Email / SendGrid ─────────────────────────────────────────────────
    sendgrid_api_key: str = ""
    sendgrid_from_email: str = ""
    sendgrid_from_name: str = "RLALab AI Assistant"
    sendgrid_api_url: str = "https://api.sendgrid.com/v3/mail/send"
    sendgrid_timeout_s: int = 30

    # ── LLM Provider ──────────────────────────────────────────────────────
    llm_provider: str = "anthropic"
    llm_model: str = "claude-sonnet-4-6"
    anthropic_api_key: str = Field(
        default="",
        validation_alias=AliasChoices("anthropic_api_key", "ANTHROPIC_API_KEY", "LLM_API_KEY"),
    )
    llm_max_tokens: int = 2048
    llm_temperature: float = 0.1
    llm_stream_timeout_s: int = 120
    llm_first_token_timeout_s: int = 10

    # ── Embeddings ────────────────────────────────────────────────────────
    embedding_model: str = "pubmedbert"
    embedding_batch_size: int = 32
    embedding_cache_dir: str = "./model_cache"
    tokenizers_parallelism: str = "false"

    # ── NCBI / PubMed ─────────────────────────────────────────────────────
    ncbi_email: str = ""
    ncbi_api_key: str = ""
    ncbi_sleep_between_batches_s: float = 0.15

    # ── RAG / Retrieval ───────────────────────────────────────────────────
    retrieval_vector_top_k: int = 10
    retrieval_lexical_top_k: int = 10
    retrieval_final_top_k: int = 5
    reranker_enabled: bool = False
    reranker_model: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"


@lru_cache
def get_settings() -> Settings:
    """Return a cached Settings instance. Use as a FastAPI dependency."""
    return Settings()


settings = get_settings()
