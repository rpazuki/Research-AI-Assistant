"""
app/embeddings/base.py
-----------------------
Abstract interface for embedding models.
All implementations must be registered in embeddings/registry.py.
"""

import asyncio

from abc import ABC, abstractmethod


class EmbeddingModel(ABC):
    model_name: str
    dimensions: int

    @abstractmethod
    def embed_query(self, text: str) -> list[float]:
        """Embed a single query string. Used at query time."""
        ...

    @abstractmethod
    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """Embed a batch of documents. Used at indexing time."""
        ...

    async def async_embed_query(self, text: str) -> list[float]:
        """Async wrapper used by request-time retrieval code."""
        return await asyncio.to_thread(self.embed_query, text)

    async def async_embed_documents(self, texts: list[str]) -> list[list[float]]:
        """Async wrapper used by indexing code."""
        return await asyncio.to_thread(self.embed_documents, texts)
