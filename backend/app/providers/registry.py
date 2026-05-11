"""
app/providers/registry.py
--------------------------
Provider factory. Extend PROVIDER_MAP to add new LLM backends.
"""

from functools import lru_cache

from app.core.config import settings
from app.providers.anthropic_provider import AnthropicProvider
from app.providers.base import LLMProvider

PROVIDER_MAP = {
    "anthropic": AnthropicProvider,
    # "openai": OpenAIProvider,   # add here when needed
}


@lru_cache(maxsize=1)
def get_llm_provider() -> LLMProvider:
    """Return a cached LLM provider instance. Use as a FastAPI dependency."""
    cls = PROVIDER_MAP.get(settings.llm_provider)
    if cls is None:
        raise ValueError(
            f"Unknown LLM provider '{settings.llm_provider}'. "
            f"Available: {list(PROVIDER_MAP.keys())}"
        )
    return cls(model=settings.llm_model, api_key=settings.anthropic_api_key)
