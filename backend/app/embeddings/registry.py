"""
app/embeddings/registry.py
---------------------------
Embedding model factory. Extend EMBEDDING_MAP to add new models.
Active model is selected by settings.embedding_model.
"""

from functools import lru_cache

from app.core.config import settings
from app.embeddings.base import EmbeddingModel
from app.embeddings.pubmedbert import PubMedBERTEmbedding
from app.embeddings.minilm import MiniLMEmbedding

EMBEDDING_MAP = {
    "pubmedbert": PubMedBERTEmbedding,
    "minilm": MiniLMEmbedding,
    # "e5large": E5LargeEmbedding,  # add here when needed
}


@lru_cache(maxsize=1)
def get_embedding_model() -> EmbeddingModel:
    """Return a cached embedding model instance. Use as a FastAPI dependency."""
    cls = EMBEDDING_MAP.get(settings.embedding_model)
    if cls is None:
        raise ValueError(
            f"Unknown embedding model '{settings.embedding_model}'. "
            f"Available: {list(EMBEDDING_MAP.keys())}"
        )
    return cls()
