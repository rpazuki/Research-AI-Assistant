"""
app/embeddings/pubmedbert.py
-----------------------------
PubMedBERT embedding model.

Model: microsoft/BiomedNLP-PubMedBERT-base-uncased-abstract-fulltext
Dimensions: 768
Why: Pre-trained on PubMed abstracts + PMC full text. Strong biomedical
     vocabulary alignment. Recommended primary model for the RLA Lab domain.

Notes:
- Model weights ~440 MB. Cache to EMBEDDING_CACHE_DIR (persistent volume in prod).
- GPU strongly recommended for batch indexing. CPU is fine for single-query embedding.
- Uses mean pooling over token embeddings (standard for sentence-transformers).
"""

import asyncio

from sentence_transformers import SentenceTransformer

from app.core.config import settings
from app.embeddings.base import EmbeddingModel


PUBMEDBERT_MODEL_NAME = "microsoft/BiomedNLP-PubMedBERT-base-uncased-abstract-fulltext"


class PubMedBERTEmbedding(EmbeddingModel):
    model_name = PUBMEDBERT_MODEL_NAME
    dimensions = 768

    def __init__(self) -> None:
        self._model = SentenceTransformer(
            self.model_name,
            cache_folder=settings.embedding_cache_dir,
        )

    def embed_query(self, text: str) -> list[float]:
        """Embed a single query string (synchronous)."""
        vec = self._model.encode(text, normalize_embeddings=True)
        return vec.tolist()

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """Batch embed a list of texts (synchronous, use asyncio.to_thread for async callers)."""
        vecs = self._model.encode(
            texts,
            batch_size=settings.embedding_batch_size,
            normalize_embeddings=True,
            show_progress_bar=True,
        )
        return [v.tolist() for v in vecs]

    async def async_embed_query(self, text: str) -> list[float]:
        """Async wrapper for use in FastAPI route handlers."""
        return await asyncio.to_thread(self.embed_query, text)

    async def async_embed_documents(self, texts: list[str]) -> list[list[float]]:
        """Async wrapper for batch embedding."""
        return await asyncio.to_thread(self.embed_documents, texts)
