"""Unit tests for app/rag/pipeline.py."""

from __future__ import annotations

import uuid

import pytest

from app.providers.base import CompletionUsage, LLMStreamChunk
from app.rag.pipeline import _chunk_to_dict, _format_exception_message, run_rag_stream
from app.rag.retrieval import RetrievedChunk


# ── _format_exception_message ─────────────────────────────────────────────────

def test_format_exception_message_uses_str_when_present() -> None:
    exc = ValueError("something went wrong")
    assert _format_exception_message(exc) == "something went wrong"


def test_format_exception_message_uses_type_name_when_blank() -> None:
    class SilentError(Exception):
        def __str__(self) -> str:
            return ""

    result = _format_exception_message(SilentError())
    assert "SilentError" in result
    assert "raised without a message" in result


def test_format_exception_message_strips_whitespace() -> None:
    exc = RuntimeError("  spaced  ")
    assert _format_exception_message(exc) == "spaced"


# ── _chunk_to_dict ────────────────────────────────────────────────────────────

def make_chunk(**kwargs) -> RetrievedChunk:
    defaults = dict(
        chunk_id=uuid.uuid4(),
        document_id="pmid:1",
        pmid="1",
        doi=None,
        title="Title",
        journal="Journal",
        year=2024,
        url=None,
        content="Content text.",
        score=0.9,
        chunk_type="abstract",
    )
    defaults.update(kwargs)
    return RetrievedChunk(**defaults)


def test_chunk_to_dict_includes_required_fields() -> None:
    chunk = make_chunk(pmid="999", doi="10.1/x", title="T", journal="J", year=2025, content="C")
    d = _chunk_to_dict(chunk)
    assert d["pmid"] == "999"
    assert d["doi"] == "10.1/x"
    assert d["title"] == "T"
    assert d["journal"] == "J"
    assert d["year"] == 2025
    assert d["content"] == "C"


def test_chunk_to_dict_none_fields_preserved() -> None:
    chunk = make_chunk(pmid=None, doi=None, title=None, journal=None, year=None)
    d = _chunk_to_dict(chunk)
    assert d["pmid"] is None
    assert d["doi"] is None


# ── run_rag_stream ────────────────────────────────────────────────────────────

class FakeEmbedder:
    async def async_embed_query(self, _text: str) -> list[float]:
        return [0.1, 0.2, 0.3]


class FakeLLM:
    model = "claude-sonnet-4-6"

    async def stream(self, *_args, **_kwargs):
        for token in ["Hello", " world"]:
            yield token
        yield LLMStreamChunk(
            usage=CompletionUsage(
                prompt_tokens=101,
                completion_tokens=23,
                model=self.model,
            )
        )


class FakeDB:
    pass


@pytest.mark.asyncio
async def test_run_rag_stream_emits_token_sources_done_events(monkeypatch: pytest.MonkeyPatch) -> None:
    chunk = make_chunk()

    async def fake_retrieve(**_kwargs):
        return [chunk]

    monkeypatch.setattr("app.rag.pipeline.retrieve", fake_retrieve)

    events = []
    async for event_type, data, sources in run_rag_stream(
        query="test query",
        mode="researcher",
        db=FakeDB(),
        embedding_model=FakeEmbedder(),
        llm_provider=FakeLLM(),
    ):
        events.append((event_type, data, sources))

    types = [e[0] for e in events]
    assert "token" in types
    assert "sources" in types
    assert "done" in types


@pytest.mark.asyncio
async def test_run_rag_stream_assembles_tokens_correctly(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_retrieve(**_kwargs):
        return []

    monkeypatch.setattr("app.rag.pipeline.retrieve", fake_retrieve)

    tokens = []
    async for event_type, data, _ in run_rag_stream(
        query="q",
        mode="researcher",
        db=FakeDB(),
        embedding_model=FakeEmbedder(),
        llm_provider=FakeLLM(),
    ):
        if event_type == "token":
            tokens.append(data)

    assert "".join(tokens) == "Hello world"


@pytest.mark.asyncio
async def test_run_rag_stream_emits_error_on_retrieval_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_retrieve(**_kwargs):
        raise RuntimeError("DB exploded")

    monkeypatch.setattr("app.rag.pipeline.retrieve", fake_retrieve)

    events = []
    async for event_type, data, _ in run_rag_stream(
        query="q",
        mode="researcher",
        db=FakeDB(),
        embedding_model=FakeEmbedder(),
        llm_provider=FakeLLM(),
    ):
        events.append((event_type, data))

    assert events[0][0] == "error"
    assert "DB exploded" in events[0][1]


@pytest.mark.asyncio
async def test_run_rag_stream_done_event_contains_latency_and_model(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_retrieve(**_kwargs):
        return []

    monkeypatch.setattr("app.rag.pipeline.retrieve", fake_retrieve)

    done_data = None
    async for event_type, data, _ in run_rag_stream(
        query="q",
        mode="researcher",
        db=FakeDB(),
        embedding_model=FakeEmbedder(),
        llm_provider=FakeLLM(),
    ):
        if event_type == "done":
            done_data = data

    assert done_data is not None
    assert "latency_ms" in done_data
    assert done_data["llm_model"] == "claude-sonnet-4-6"
    assert isinstance(done_data["latency_ms"], int)
    assert done_data["prompt_tokens"] == 101
    assert done_data["completion_tokens"] == 23
