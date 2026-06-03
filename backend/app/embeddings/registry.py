"""
app/embeddings/registry.py
---------------------------
Embedding model factory. Extend EMBEDDING_MAP to add new models.
Active model is selected by settings.embedding_model.
"""

from functools import lru_cache
from importlib import import_module

from app.core.config import settings
from app.embeddings.base import EmbeddingModel

EMBEDDING_MAP = {
    "pubmedbert": "app.embeddings.pubmedbert:PubMedBERTEmbedding",
    "minilm": "app.embeddings.minilm:MiniLMEmbedding",
    # "e5large": E5LargeEmbedding,  # add here when needed
}


def _load_embedding_class(path: str) -> type[EmbeddingModel]:
    module_name, class_name = path.split(":", maxsplit=1)
    module = import_module(module_name)
    return getattr(module, class_name)


@lru_cache(maxsize=1)
def get_embedding_model() -> EmbeddingModel:
    """Return a cached embedding model instance. Use as a FastAPI dependency."""
    class_path = EMBEDDING_MAP.get(settings.embedding_model)
    if class_path is None:
        raise ValueError(
            f"Unknown embedding model '{settings.embedding_model}'. "
            f"Available: {list(EMBEDDING_MAP.keys())}"
        )
    cls = _load_embedding_class(class_path)
    return cls()
