"""
app/main.py
-----------
FastAPI application factory.

Start with:
    uvicorn app.main:app --reload --port 8000
"""

from contextlib import asynccontextmanager
import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import admin, auth, chat, search, analytics, feedback
from app.core.config import settings
from app.core.logging import configure_logging


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown lifecycle events."""
    os.environ.setdefault("TOKENIZERS_PARALLELISM", settings.tokenizers_parallelism)
    configure_logging()

    # Pre-load expensive singletons at startup so first request is fast.
    from app.embeddings.registry import get_embedding_model
    from app.providers.registry import get_llm_provider
    get_embedding_model()  # loads model weights into memory
    get_llm_provider()     # creates API client

    yield
    # Shutdown: nothing to clean up currently.


app = FastAPI(
    title=settings.app_name,
    description="Internal RAG-based research literature assistant for the RLA Lab.",
    version="0.1.0",
    lifespan=lifespan,
    docs_url="/api/docs" if settings.app_env == "development" else None,
    redoc_url="/api/redoc" if settings.app_env == "development" else None,
)

# ── CORS ──────────────────────────────────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Routers ───────────────────────────────────────────────────────────────────
PREFIX = "/api/v1"

app.include_router(auth.router, prefix=PREFIX)
app.include_router(admin.router, prefix=PREFIX)
app.include_router(chat.router, prefix=PREFIX)
app.include_router(search.router, prefix=PREFIX)
app.include_router(analytics.router, prefix=PREFIX)
app.include_router(feedback.router, prefix=PREFIX)


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "app": settings.app_name}
