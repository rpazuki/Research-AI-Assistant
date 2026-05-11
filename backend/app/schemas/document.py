"""app/schemas/document.py — Document and search result schemas."""

import uuid
from datetime import date, datetime
from pydantic import BaseModel


class SearchRequest(BaseModel):
    query: str
    top_k: int = 5
    filters: dict | None = None  # e.g. {"year_from": 2020, "year_to": 2025, "source": "pubmed"}


class SearchResultItem(BaseModel):
    chunk_id: uuid.UUID
    document_id: str
    pmid: str | None = None
    doi: str | None = None
    title: str | None = None
    journal: str | None = None
    year: int | None = None
    url: str | None = None
    content: str
    score: float
    chunk_type: str
