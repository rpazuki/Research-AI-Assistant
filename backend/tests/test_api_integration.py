from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace

import httpx
import pytest

from app.api import deps
from app.core.security import create_access_token
from app.db.models import User
from app.main import app


class DummyDB:
    async def delete(self, _obj) -> None:
        return None


def make_user() -> User:
    return User(
        id=uuid.uuid4(),
        email="researcher@example.com",
        hashed_password="hashed",
        full_name="Researcher",
        role="researcher",
        is_active=True,
    )


@pytest.fixture
async def api_client():
    user = make_user()
    db = DummyDB()

    class DummyEmbedder:
        async def async_embed_query(self, _text: str):
            return [0.1, 0.2, 0.3]

    class DummyLLM:
        model = "claude-sonnet-4-6"

        async def complete(self, *_args, **_kwargs):
            return "ok", SimpleNamespace(prompt_tokens=1, completion_tokens=1, model=self.model)

        async def stream(self, *_args, **_kwargs):
            yield "ok"

    async def override_current_user():
        return user

    async def override_db():
        yield db

    def override_embedder():
        return DummyEmbedder()

    def override_llm():
        return DummyLLM()

    app.dependency_overrides[deps.get_current_user] = override_current_user
    app.dependency_overrides[deps.get_db] = override_db
    app.dependency_overrides[deps.get_embedding_model] = override_embedder
    app.dependency_overrides[deps.get_llm_provider] = override_llm

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client, user, db

    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_auth_login_logout_and_me(api_client, monkeypatch: pytest.MonkeyPatch) -> None:
    client, user, _db = api_client

    async def fake_get_user_by_email(_db_obj, email: str):
        assert email == user.email
        return user

    monkeypatch.setattr("app.api.routes.auth.get_user_by_email", fake_get_user_by_email)
    monkeypatch.setattr("app.api.routes.auth.verify_password", lambda plain, hashed: True)

    response = await client.post(
        "/api/v1/auth/login",
        json={"email": user.email, "password": "secret"},
    )
    assert response.status_code == 200
    assert response.json()["token_type"] == "bearer"

    me_response = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {create_access_token(str(user.id))}"})
    assert me_response.status_code == 200
    assert me_response.json()["email"] == user.email

    logout_response = await client.post("/api/v1/auth/logout")
    assert logout_response.status_code == 204


@pytest.mark.asyncio
async def test_search_endpoint_returns_retrieved_chunks(api_client, monkeypatch: pytest.MonkeyPatch) -> None:
    client, _user, _db = api_client

    fake_chunk = SimpleNamespace(
        chunk_id=uuid.uuid4(),
        document_id="pmid:1234",
        pmid="1234",
        doi=None,
        title="Lipid engineering",
        journal="Metabolic Engineering",
        year=2025,
        url="https://pubmed.ncbi.nlm.nih.gov/1234/",
        content="Evidence snippet",
        score=0.9,
        chunk_type="abstract",
    )

    async def fake_retrieve(**_kwargs):
        return [fake_chunk]

    monkeypatch.setattr("app.api.routes.search.retrieve", fake_retrieve)

    response = await client.post("/api/v1/search", json={"query": "lipid accumulation", "top_k": 5})
    assert response.status_code == 200
    body = response.json()
    assert body[0]["pmid"] == "1234"
    assert body[0]["title"] == "Lipid engineering"


@pytest.mark.asyncio
async def test_analytics_endpoints_return_expected_shapes(api_client, monkeypatch: pytest.MonkeyPatch) -> None:
    client, _user, _db = api_client

    async def fake_count_documents_by_year(_db_obj):
        return [{"year": 2024, "count": 7}]

    async def fake_top_journals(_db_obj, limit: int = 20):
        assert limit == 20
        return [{"journal": "Nature Biotechnology", "count": 4}]

    class Result:
        def __init__(self, rows=None, scalar=None, one=None, maybe_one=None):
            self._rows = rows or []
            self._scalar = scalar
            self._one = one
            self._maybe_one = maybe_one

        def __iter__(self):
            return iter(self._rows)

        def scalar_one(self):
            return self._scalar

        def one(self):
            return self._one

        def one_or_none(self):
            return self._maybe_one

    class AnalyticsDB:
        async def execute(self, _query, _params=None):
            query_text = str(_query)
            if "unnest(mesh_terms)" in query_text:
                return Result(rows=[SimpleNamespace(term="oleaginous yeast", count=3)])
            if "count(documents.id)" in query_text:
                return Result(scalar=11)
            if "count(document_chunks.id)" in query_text:
                return Result(scalar=31)
            if "min(documents.year)" in query_text:
                return Result(one=(2020, 2025))
            if "ingestion_manifests.created_at" in query_text:
                return Result(maybe_one=SimpleNamespace(created_at=datetime(2026, 5, 12, tzinfo=timezone.utc), name="rlalab-v1"))
            return Result(rows=[SimpleNamespace(topic="lipid metabolism", count=5)])

    async def override_db():
        yield AnalyticsDB()

    app.dependency_overrides[deps.get_db] = override_db
    monkeypatch.setattr("app.db.crud.count_documents_by_year", fake_count_documents_by_year)
    monkeypatch.setattr("app.db.crud.top_journals", fake_top_journals)

    temporal = await client.get("/api/v1/analytics/temporal")
    journals = await client.get("/api/v1/analytics/journals")
    mesh_terms = await client.get("/api/v1/analytics/mesh_terms")
    corpus_stats = await client.get("/api/v1/analytics/corpus_stats")
    topics = await client.get("/api/v1/analytics/topics")

    assert temporal.status_code == 200
    assert journals.status_code == 200
    assert mesh_terms.json()[0]["term"] == "oleaginous yeast"
    assert corpus_stats.json()["chunk_count"] == 31
    assert topics.json()[0]["topic"] == "lipid metabolism"


@pytest.mark.asyncio
async def test_chat_streaming_endpoint_emits_sse_and_persists_messages(api_client, monkeypatch: pytest.MonkeyPatch) -> None:
    client, user, _db = api_client
    session = SimpleNamespace(id=uuid.uuid4(), user_id=user.id, mode="researcher")
    created_messages: list[dict] = []

    async def fake_get_session(_db_obj, session_id):
        assert session_id == session.id
        return session

    async def fake_create_chat_message(_db_obj, **kwargs):
        created_messages.append(kwargs)
        return SimpleNamespace(id=uuid.uuid4())

    async def fake_get_message_count_for_session(_db_obj, _session_id):
        return 2

    async def fake_run_rag_stream(**_kwargs):
        yield ("token", "Hello", None)
        yield (
            "sources",
            None,
            [SimpleNamespace(model_dump=lambda: {"pmid": "1234", "title": "Paper", "snippet": "Evidence"})],
        )
        yield (
            "done",
            {"retrieved_chunk_ids": [str(uuid.uuid4())], "llm_model": "claude-sonnet-4-6", "latency_ms": 9},
            None,
        )

    monkeypatch.setattr("app.db.crud.get_session", fake_get_session)
    monkeypatch.setattr("app.db.crud.create_chat_message", fake_create_chat_message)
    monkeypatch.setattr("app.db.crud.get_message_count_for_session", fake_get_message_count_for_session)
    monkeypatch.setattr("app.api.routes.chat.run_rag_stream", fake_run_rag_stream)

    response = await client.post(
        f"/api/v1/chat/sessions/{session.id}/messages",
        json={"query": "What is known?", "mode": "researcher"},
    )
    assert response.status_code == 200
    text = response.text
    assert '"type": "token"' in text
    assert '"type": "sources"' in text
    assert '"type": "done"' in text
    assert created_messages[0]["role"] == "user"
    assert created_messages[1]["llm_model"] == "claude-sonnet-4-6"


@pytest.mark.asyncio
async def test_chat_streaming_endpoint_surfaces_blank_exceptions(api_client, monkeypatch: pytest.MonkeyPatch) -> None:
    client, user, _db = api_client
    session = SimpleNamespace(id=uuid.uuid4(), user_id=user.id, mode="researcher")

    class SilentError(Exception):
        def __str__(self) -> str:
            return ""

    async def fake_get_session(_db_obj, session_id):
        assert session_id == session.id
        return session

    async def fake_create_chat_message(_db_obj, **_kwargs):
        return SimpleNamespace(id=uuid.uuid4())

    async def fake_get_message_count_for_session(_db_obj, _session_id):
        return 2

    async def fake_run_rag_stream(**_kwargs):
        raise SilentError()
        yield

    monkeypatch.setattr("app.db.crud.get_session", fake_get_session)
    monkeypatch.setattr("app.db.crud.create_chat_message", fake_create_chat_message)
    monkeypatch.setattr("app.db.crud.get_message_count_for_session", fake_get_message_count_for_session)
    monkeypatch.setattr("app.api.routes.chat.run_rag_stream", fake_run_rag_stream)

    response = await client.post(
        f"/api/v1/chat/sessions/{session.id}/messages",
        json={"query": "What is known?", "mode": "researcher"},
    )
    assert response.status_code == 200
    assert '"type": "error"' in response.text
    assert "SilentError raised without a message" in response.text


@pytest.mark.asyncio
async def test_get_session_returns_messages_without_lazy_loading_errors(
    api_client, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, user, _db = api_client
    session_id = uuid.uuid4()
    created_at = datetime.now(timezone.utc)
    session = SimpleNamespace(
        id=session_id,
        user_id=user.id,
        title="Untitled Chat",
        mode="researcher",
        created_at=created_at,
        updated_at=created_at,
    )
    message = SimpleNamespace(
        id=uuid.uuid4(),
        session_id=session_id,
        role="assistant",
        content="Grounded answer",
        sources=[{"pmid": "1234", "title": "Paper"}],
        llm_model="claude-sonnet-4-6",
        latency_ms=12,
        created_at=created_at,
    )

    async def fake_get_session(_db_obj, requested_session_id):
        assert requested_session_id == session_id
        return session

    async def fake_get_messages_for_session(_db_obj, session_id):
        assert session_id == session.id
        return [message]

    monkeypatch.setattr("app.db.crud.get_session", fake_get_session)
    monkeypatch.setattr("app.db.crud.get_messages_for_session", fake_get_messages_for_session)

    response = await client.get(f"/api/v1/chat/sessions/{session_id}")
    assert response.status_code == 200
    body = response.json()
    assert body["id"] == str(session_id)
    assert body["messages"][0]["content"] == "Grounded answer"
    assert body["messages"][0]["sources"][0]["pmid"] == "1234"


@pytest.mark.asyncio
async def test_update_session_title_endpoint(api_client, monkeypatch: pytest.MonkeyPatch) -> None:
    client, user, _db = api_client
    session_id = uuid.uuid4()
    created_at = datetime.now(timezone.utc)
    session = SimpleNamespace(
        id=session_id,
        user_id=user.id,
        title="Untitled Chat",
        mode="researcher",
        created_at=created_at,
        updated_at=created_at,
    )
    saved_titles: list[str] = []

    async def fake_get_session(_db_obj, requested_session_id):
        assert requested_session_id == session_id
        return session

    async def fake_update_chat_session_title(_db_obj, session, title: str):
        saved_titles.append(title)
        session.title = title
        return session

    monkeypatch.setattr("app.db.crud.get_session", fake_get_session)
    monkeypatch.setattr("app.db.crud.update_chat_session_title", fake_update_chat_session_title)

    response = await client.patch(
        f"/api/v1/chat/sessions/{session_id}",
        json={"title": "  Updated title  "},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["id"] == str(session_id)
    assert body["title"] == "Updated title"
    assert saved_titles == ["Updated title"]


@pytest.mark.asyncio
async def test_chat_streaming_auto_titles_first_exchange(api_client, monkeypatch: pytest.MonkeyPatch) -> None:
    client, user, _db = api_client
    session = SimpleNamespace(
        id=uuid.uuid4(),
        user_id=user.id,
        mode="researcher",
        title="",
    )
    updated_titles: list[str] = []

    async def fake_get_session(_db_obj, session_id):
        assert session_id == session.id
        return session

    async def fake_create_chat_message(_db_obj, **_kwargs):
        return SimpleNamespace(id=uuid.uuid4())

    async def fake_run_rag_stream(**_kwargs):
        yield ("token", "First answer sentence.", None)
        yield (
            "done",
            {"retrieved_chunk_ids": [str(uuid.uuid4())], "llm_model": "claude-sonnet-4-6", "latency_ms": 12},
            None,
        )

    async def fake_get_message_count_for_session(_db_obj, session_id):
        assert session_id == session.id
        return 0

    async def fake_generate_session_title(**kwargs):
        assert kwargs["user_query"] == "What is known?"
        assert "First answer sentence." in kwargs["assistant_response"]
        return "Auto title"

    async def fake_update_chat_session_title(_db_obj, session, title: str):
        updated_titles.append(title)
        return session

    monkeypatch.setattr("app.db.crud.get_session", fake_get_session)
    monkeypatch.setattr("app.db.crud.create_chat_message", fake_create_chat_message)
    monkeypatch.setattr("app.db.crud.get_message_count_for_session", fake_get_message_count_for_session)
    monkeypatch.setattr("app.db.crud.update_chat_session_title", fake_update_chat_session_title)
    monkeypatch.setattr("app.api.routes.chat._generate_session_title", fake_generate_session_title)
    monkeypatch.setattr("app.api.routes.chat.run_rag_stream", fake_run_rag_stream)

    response = await client.post(
        f"/api/v1/chat/sessions/{session.id}/messages",
        json={"query": "What is known?", "mode": "researcher"},
    )
    assert response.status_code == 200
    assert '"type": "done"' in response.text
    assert updated_titles == ["Auto title"]


@pytest.mark.asyncio
async def test_chat_streaming_continues_when_auto_title_generation_fails(
    api_client, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, user, _db = api_client
    session = SimpleNamespace(
        id=uuid.uuid4(),
        user_id=user.id,
        mode="researcher",
        title=None,
    )
    updated_titles: list[str] = []

    async def fake_get_session(_db_obj, session_id):
        assert session_id == session.id
        return session

    async def fake_create_chat_message(_db_obj, **_kwargs):
        return SimpleNamespace(id=uuid.uuid4())

    async def fake_run_rag_stream(**_kwargs):
        yield ("token", "A response.", None)
        yield ("done", {"retrieved_chunk_ids": [], "llm_model": "claude-sonnet-4-6", "latency_ms": 7}, None)

    async def fake_get_message_count_for_session(_db_obj, session_id):
        assert session_id == session.id
        return 0

    async def fake_generate_session_title(**_kwargs):
        return None

    async def fake_update_chat_session_title(_db_obj, session, title: str):
        updated_titles.append(title)
        return session

    monkeypatch.setattr("app.db.crud.get_session", fake_get_session)
    monkeypatch.setattr("app.db.crud.create_chat_message", fake_create_chat_message)
    monkeypatch.setattr("app.db.crud.get_message_count_for_session", fake_get_message_count_for_session)
    monkeypatch.setattr("app.db.crud.update_chat_session_title", fake_update_chat_session_title)
    monkeypatch.setattr("app.api.routes.chat._generate_session_title", fake_generate_session_title)
    monkeypatch.setattr("app.api.routes.chat.run_rag_stream", fake_run_rag_stream)

    response = await client.post(
        f"/api/v1/chat/sessions/{session.id}/messages",
        json={"query": "What is known?", "mode": "researcher"},
    )
    assert response.status_code == 200
    assert '"type": "done"' in response.text
    assert updated_titles == []
