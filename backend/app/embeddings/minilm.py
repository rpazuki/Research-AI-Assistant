"""
app/embeddings/minilm.py
-------------------------
MiniLM-L6-v2 embedding model.

Model: sentence-transformers/all-MiniLM-L6-v2
Dimensions: 384
Why: Fast CPU inference. Used as baseline in evaluation and as a quick
     prototype-mode fallback.

Note: If using MiniLM alongside PubMedBERT, a separate vector column
(vector(384)) is needed in document_chunks. See CLAUDE.md §17.
"""

import asyncio

from sentence_transformers import SentenceTransformer

from app.core.config import settings
from app.embeddings.base import EmbeddingModel


class MiniLMEmbedding(EmbeddingModel):
    model_name = "sentence-transformers/all-MiniLM-L6-v2"
    dimensions = 384

    def __init__(self) -> None:
        self._model = SentenceTransformer(
            self.model_name,
            cache_folder=settings.embedding_cache_dir,
        )

    def embed_query(self, text: str) -> list[float]:
        vec = self._model.encode(text, normalize_embeddings=True)
        return vec.tolist()

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        vecs = self._model.encode(
            texts,
            batch_size=settings.embedding_batch_size,
            normalize_embeddings=True,
            show_progress_bar=True,
        )
        return [v.tolist() for v in vecs]

    async def async_embed_query(self, text: str) -> list[float]:
        return await asyncio.to_thread(self.embed_query, text)

    async def async_embed_documents(self, texts: list[str]) -> list[list[float]]:
        return await asyncio.to_thread(self.embed_documents, texts)
