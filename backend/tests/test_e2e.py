"""
End-to-end tests exercising the full HTTP stack (FastAPI via ASGI transport).

All external dependencies (DB, LLM, embeddings) are replaced with lightweight
in-process fakes so no live services are required.

Coverage:
  - Auth: login success/failure, inactive user, missing user, /me
  - Chat sessions: create, list, get, delete, update title
  - Feedback: submit valid, rating out of range
  - Search: basic retrieval, with filters
  - Deps: admin-only gate rejects researcher
"""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from types import SimpleNamespace

import httpx
import pytest

from app.api import deps
from app.core.security import hash_password
from app.db.models import User
from app.main import app


# ── Shared helpers ────────────────────────────────────────────────────────────

def make_user(role: str = "researcher", is_active: bool = True) -> User:
    return User(
        id=uuid.uuid4(),
        email="lab@example.com",
        hashed_password=hash_password("correct"),
        full_name="Lab User",
        role=role,
        is_active=is_active,
    )


def _now() -> datetime:
    return datetime.now(timezone.utc)


class _FakeDB:
    def __init__(self):
        self._added: list = []
        self._deleted: list = []

    async def delete(self, obj) -> None:
        self._deleted.append(obj)

    def add(self, obj) -> None:
        self._added.append(obj)

    async def flush(self) -> None:
        pass


class _FakeEmbedder:
    async def async_embed_query(self, _text: str):
        return [0.1] * 3


class _FakeLLM:
    model = "claude-sonnet-4-6"

    async def complete(self, *_a, **_kw):
        return "ok", SimpleNamespace(prompt_tokens=1, completion_tokens=1, model=self.model)

    async def stream(self, *_a, **_kw):
        yield "token"


@asynccontextmanager
async def _make_client(user: User):
    """Async context manager: sets up dependency overrides and yields (client, user, db)."""
    db = _FakeDB()

    async def _user():
        return user

    async def _db():
        yield db

    def _embedder():
        return _FakeEmbedder()

    def _llm():
        return _FakeLLM()

    app.dependency_overrides[deps.get_current_user] = _user
    app.dependency_overrides[deps.get_db] = _db
    app.dependency_overrides[deps.get_embedding_model] = _embedder
    app.dependency_overrides[deps.get_llm_provider] = _llm

    transport = httpx.ASGITransport(app=app)
    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as c:
            yield c, user, db
    finally:
        app.dependency_overrides.clear()


# ── Auth ──────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_login_success_returns_bearer_token(monkeypatch: pytest.MonkeyPatch) -> None:
    user = make_user()

    async def fake_db():
        yield _FakeDB()

    async def fake_get_user(_db, _email):
        return user

    app.dependency_overrides[deps.get_db] = fake_db
    monkeypatch.setattr("app.api.routes.auth.get_user_by_email", fake_get_user)
    monkeypatch.setattr("app.api.routes.auth.verify_password", lambda _p, _h: True)

    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as c:
            resp = await c.post("/api/v1/auth/login", json={"email": user.email, "password": "correct"})
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 200
    body = resp.json()
    assert body["token_type"] == "bearer"
    assert "access_token" in body
    assert isinstance(body["expires_in"], int)


@pytest.mark.asyncio
async def test_login_wrong_password_returns_401(monkeypatch: pytest.MonkeyPatch) -> None:
    user = make_user()

    async def fake_db():
        yield _FakeDB()

    async def fake_get_user(_db, _email):
        return user

    app.dependency_overrides[deps.get_db] = fake_db
    monkeypatch.setattr("app.api.routes.auth.get_user_by_email", fake_get_user)
    monkeypatch.setattr("app.api.routes.auth.verify_password", lambda _p, _h: False)

    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as c:
            resp = await c.post("/api/v1/auth/login", json={"email": user.email, "password": "wrong"})
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_login_unknown_user_returns_401(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_db():
        yield _FakeDB()

    async def fake_get_user(_db, _email):
        return None

    app.dependency_overrides[deps.get_db] = fake_db
    monkeypatch.setattr("app.api.routes.auth.get_user_by_email", fake_get_user)

    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as c:
            resp = await c.post("/api/v1/auth/login", json={"email": "nobody@x.com", "password": "pw"})
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_login_inactive_user_returns_403(monkeypatch: pytest.MonkeyPatch) -> None:
    user = make_user(is_active=False)

    async def fake_db():
        yield _FakeDB()

    async def fake_get_user(_db, _email):
        return user

    app.dependency_overrides[deps.get_db] = fake_db
    monkeypatch.setattr("app.api.routes.auth.get_user_by_email", fake_get_user)
    monkeypatch.setattr("app.api.routes.auth.verify_password", lambda _p, _h: True)

    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as c:
            resp = await c.post("/api/v1/auth/login", json={"email": user.email, "password": "correct"})
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 403
    assert "inactive" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_me_returns_current_user_profile() -> None:
    user = make_user()
    async with _make_client(user) as (c, _u, _db):
        resp = await c.get("/api/v1/auth/me")
    assert resp.status_code == 200
    body = resp.json()
    assert body["email"] == user.email
    assert body["role"] == "researcher"


# ── Chat sessions CRUD ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_create_session_returns_201_with_session_data(monkeypatch: pytest.MonkeyPatch) -> None:
    user = make_user()
    session_id = uuid.uuid4()

    async def fake_create_chat_session(_db, user_id, mode, title):
        return SimpleNamespace(
            id=session_id, user_id=user_id, mode=mode, title=title,
            created_at=_now(), updated_at=_now(),
        )

    monkeypatch.setattr("app.api.routes.chat.crud.create_chat_session", fake_create_chat_session)

    async with _make_client(user) as (c, _u, _db):
        resp = await c.post("/api/v1/chat/sessions", json={"mode": "researcher"})

    assert resp.status_code == 201
    body = resp.json()
    assert body["id"] == str(session_id)
    assert body["mode"] == "researcher"


@pytest.mark.asyncio
async def test_list_sessions_returns_user_sessions(monkeypatch: pytest.MonkeyPatch) -> None:
    user = make_user()
    sessions = [
        SimpleNamespace(
            id=uuid.uuid4(), user_id=user.id, mode="researcher",
            title=f"Chat {i}", created_at=_now(), updated_at=_now(),
        )
        for i in range(3)
    ]

    async def fake_get_sessions_for_user(_db, user_id):
        assert user_id == user.id
        return sessions

    monkeypatch.setattr("app.api.routes.chat.crud.get_sessions_for_user", fake_get_sessions_for_user)

    async with _make_client(user) as (c, _u, _db):
        resp = await c.get("/api/v1/chat/sessions")

    assert resp.status_code == 200
    assert len(resp.json()) == 3


@pytest.mark.asyncio
async def test_delete_session_returns_204(monkeypatch: pytest.MonkeyPatch) -> None:
    user = make_user()
    session_id = uuid.uuid4()
    session = SimpleNamespace(
        id=session_id, user_id=user.id, mode="researcher",
        title=None, created_at=_now(), updated_at=_now(),
    )

    async def fake_get_session(_db, sid):
        assert sid == session_id
        return session

    monkeypatch.setattr("app.db.crud.get_session", fake_get_session)

    async with _make_client(user) as (c, _u, _db):
        resp = await c.delete(f"/api/v1/chat/sessions/{session_id}")

    assert resp.status_code == 204


@pytest.mark.asyncio
async def test_get_session_owned_by_other_user_returns_403(monkeypatch: pytest.MonkeyPatch) -> None:
    user = make_user()
    other_user_id = uuid.uuid4()
    session_id = uuid.uuid4()
    session = SimpleNamespace(
        id=session_id, user_id=other_user_id, mode="researcher",
        title=None, created_at=_now(), updated_at=_now(),
    )

    async def fake_get_session(_db, sid):
        return session

    monkeypatch.setattr("app.db.crud.get_session", fake_get_session)

    async with _make_client(user) as (c, _u, _db):
        resp = await c.get(f"/api/v1/chat/sessions/{session_id}")

    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_get_nonexistent_session_returns_404(monkeypatch: pytest.MonkeyPatch) -> None:
    user = make_user()

    async def fake_get_session(_db, sid):
        return None

    monkeypatch.setattr("app.db.crud.get_session", fake_get_session)

    async with _make_client(user) as (c, _u, _db):
        resp = await c.get(f"/api/v1/chat/sessions/{uuid.uuid4()}")

    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_update_session_title_empty_string_returns_422(monkeypatch: pytest.MonkeyPatch) -> None:
    user = make_user()
    session_id = uuid.uuid4()
    session = SimpleNamespace(
        id=session_id, user_id=user.id, mode="researcher",
        title="Old", created_at=_now(), updated_at=_now(),
    )

    async def fake_get_session(_db, sid):
        return session

    monkeypatch.setattr("app.db.crud.get_session", fake_get_session)

    async with _make_client(user) as (c, _u, _db):
        resp = await c.patch(f"/api/v1/chat/sessions/{session_id}", json={"title": "   "})

    assert resp.status_code == 422


# ── Admin gate ────────────────────────────────────────────────────────────────

def test_admin_only_endpoint_rejects_researcher() -> None:
    from fastapi import HTTPException
    from app.api.deps import get_admin_user

    researcher = make_user(role="researcher")
    with pytest.raises(HTTPException) as exc_info:
        get_admin_user(researcher)
    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_admin_user_management_endpoints(monkeypatch: pytest.MonkeyPatch) -> None:
    admin = make_user(role="admin")
    researcher = make_user()
    researcher.id = uuid.uuid4()
    researcher.email = "researcher@example.com"
    researcher.full_name = "Researcher"

    async def fake_list_users(_db):
        return [admin, researcher]

    async def fake_get_user_by_id(_db, user_id):
        if user_id == researcher.id:
            return researcher
        if user_id == admin.id:
            return admin
        return None

    async def fake_update_user_active(_db, user, is_active):
        user.is_active = is_active
        return user

    monkeypatch.setattr("app.api.routes.admin.crud.list_users", fake_list_users)
    monkeypatch.setattr("app.api.routes.admin.crud.get_user_by_id", fake_get_user_by_id)
    monkeypatch.setattr("app.api.routes.admin.crud.update_user_active", fake_update_user_active)

    async with _make_client(admin) as (c, _u, _db):
        list_resp = await c.get("/api/v1/admin/users")
        detail_resp = await c.get(f"/api/v1/admin/users/{researcher.id}")
        update_resp = await c.patch(
            f"/api/v1/admin/users/{researcher.id}",
            json={"is_active": False},
        )

    assert list_resp.status_code == 200
    assert len(list_resp.json()) == 2
    assert detail_resp.status_code == 200
    assert detail_resp.json()["email"] == "researcher@example.com"
    assert update_resp.status_code == 200
    assert update_resp.json()["is_active"] is False


# ── Feedback ──────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_feedback_submit_returns_201_with_id(monkeypatch: pytest.MonkeyPatch) -> None:
    user = make_user()
    feedback_id = uuid.uuid4()
    message_id = uuid.uuid4()

    async def fake_create_feedback(_db, **_kwargs):
        return SimpleNamespace(id=feedback_id)

    monkeypatch.setattr("app.api.routes.feedback.create_feedback", fake_create_feedback)

    async with _make_client(user) as (c, _u, _db):
        resp = await c.post(
            "/api/v1/feedback",
            json={"message_id": str(message_id), "rating": 5, "comment": "Excellent"},
        )

    assert resp.status_code == 201
    assert resp.json()["id"] == str(feedback_id)


@pytest.mark.asyncio
async def test_feedback_rating_below_1_returns_422() -> None:
    user = make_user()
    async with _make_client(user) as (c, _u, _db):
        resp = await c.post(
            "/api/v1/feedback",
            json={"message_id": str(uuid.uuid4()), "rating": 0},
        )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_feedback_rating_above_5_returns_422() -> None:
    user = make_user()
    async with _make_client(user) as (c, _u, _db):
        resp = await c.post(
            "/api/v1/feedback",
            json={"message_id": str(uuid.uuid4()), "rating": 6},
        )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_feedback_comment_is_optional(monkeypatch: pytest.MonkeyPatch) -> None:
    user = make_user()

    async def fake_create_feedback(_db, **_kwargs):
        return SimpleNamespace(id=uuid.uuid4())

    monkeypatch.setattr("app.api.routes.feedback.create_feedback", fake_create_feedback)

    async with _make_client(user) as (c, _u, _db):
        resp = await c.post(
            "/api/v1/feedback",
            json={"message_id": str(uuid.uuid4()), "rating": 3},
        )
    assert resp.status_code == 201


# ── Search with filters ───────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_search_with_year_filter_passes_filter_to_retrieve(monkeypatch: pytest.MonkeyPatch) -> None:
    user = make_user()
    captured_filters: list[dict] = []

    async def fake_retrieve(*, filters, **_kwargs):
        captured_filters.append(filters)
        return []

    monkeypatch.setattr("app.api.routes.search.retrieve", fake_retrieve)

    async with _make_client(user) as (c, _u, _db):
        resp = await c.post(
            "/api/v1/search",
            json={"query": "Yarrowia", "top_k": 3, "filters": {"year_from": 2020, "year_to": 2024}},
        )

    assert resp.status_code == 200
    assert captured_filters[0]["year_from"] == 2020
    assert captured_filters[0]["year_to"] == 2024


@pytest.mark.asyncio
async def test_search_missing_query_returns_422() -> None:
    user = make_user()
    async with _make_client(user) as (c, _u, _db):
        resp = await c.post("/api/v1/search", json={"top_k": 5})
    assert resp.status_code == 422
