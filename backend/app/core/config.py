"""
app/core/config.py
------------------
Backend settings loaded from environment variables.

The backend is deliberately env-var-only — it has no YAML config file of its own,
unlike the frontend, pipelines and evaluation components. Do not add one.

One variable names the scenario:

    RLALAB_ENV = local | compose | server

    local    host processes, Postgres reached on the published port  (the DEFAULT)
    compose  containers on a dev machine, Postgres reached as `db`
    server   containers on the deployment VM, production behaviour

**Defaults serve `local`.** Compose always injects addresses explicitly (see
`.env.compose` / `.env.server`), so it never needs a default. A bare shell has no
injection mechanism at all, so it must be the case the defaults cover. Addresses
therefore never belong in `.env` — see docs in run_and_deploy.md §2.
"""

from functools import lru_cache
from typing import Literal

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

RlalabEnv = Literal["local", "compose", "server"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        case_sensitive=False,
        extra="ignore",
    )

    # ── App ───────────────────────────────────────────────────────────────
    app_name: str = "RLALab AI Research Assistant"
    rlalab_env: RlalabEnv = "local"
    log_level: str = "INFO"
    cors_origins: list[str] = ["http://localhost:3000"]
    app_public_url: str = "http://localhost:3000"

    # ── Database ──────────────────────────────────────────────────────────
    # Host-correct default: the Compose `db` service, published on 5433.
    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5433/rlalab_ai"

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

    # ── Acquisition (datasheet S3) ────────────────────────────────────────
    # Contact addresses, not secrets: they put requests in each API's polite pool
    # and are how an upstream reaches us before blocking us. Unpaywall *requires*
    # one. All fall back to `ncbi_email` at the call site.
    unpaywall_email: str = ""
    crossref_mailto: str = ""
    openalex_mailto: str = ""
    # LibKey/EZproxy pattern containing {doi}, used to build assisted-acquisition
    # links. Empty means links fall back to plain doi.org — one extra click, never
    # a blocked run. Never used for a scripted login.
    libkey_resolver_template: str = ""
    ezproxy_url_template: str = ""
    # Publisher TDM. The route is implemented but inert without a key.
    elsevier_tdm_key: str = ""

    # ── RAG / Retrieval ───────────────────────────────────────────────────
    retrieval_vector_top_k: int = 10
    retrieval_lexical_top_k: int = 10
    retrieval_final_top_k: int = 5
    reranker_enabled: bool = False
    reranker_model: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"

    # ── Derived ───────────────────────────────────────────────────────────
    # Call sites ask these instead of string-comparing the selector, so adding a
    # scenario later does not mean auditing every `== "..."` in the codebase.

    @property
    def is_production(self) -> bool:
        """True only on the deployment VM."""
        return self.rlalab_env == "server"

    @property
    def is_containerised(self) -> bool:
        """True when this process runs inside Compose (dev machine or server)."""
        return self.rlalab_env in ("compose", "server")

    @property
    def alembic_database_url(self) -> str:
        """URL for migrations. `ALEMBIC_DATABASE_URL` wins when set, so a one-off
        migration can target another database without touching anything else."""
        import os

        return os.environ.get("ALEMBIC_DATABASE_URL") or self.database_url


@lru_cache
def get_settings() -> Settings:
    """Return a cached Settings instance. Use as a FastAPI dependency."""
    return Settings()


settings = get_settings()
