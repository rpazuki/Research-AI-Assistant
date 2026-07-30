"""Tests for the admin datasheet template endpoints."""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from types import SimpleNamespace

import httpx
import pytest

from app.api import deps
from app.db.models import User
from app.main import app

NOW = datetime(2026, 7, 29, 10, 0, tzinfo=timezone.utc)


class DummyDB:
    pass


def make_admin() -> User:
    return User(
        id=uuid.uuid4(),
        email="admin@example.com",
        hashed_password="hashed",
        full_name="Admin",
        role="admin",
        is_active=True,
        token_limit=1_000_000,
    )


def make_researcher() -> User:
    return User(
        id=uuid.uuid4(),
        email="researcher@example.com",
        hashed_password="hashed",
        full_name="Researcher",
        role="researcher",
        is_active=True,
        token_limit=1_000_000,
    )


def make_column(**overrides):
    data = {
        "id": uuid.uuid4(),
        "key": "carbon_source",
        "label": "carbon source",
        "kind": "free_text",
        "order_index": 0,
        "vocabulary": None,
        "extraction_hint": "Carbon substrate fed.",
        "source_hint": "fulltext",
        "required": False,
        "enabled": True,
    }
    data.update(overrides)
    return SimpleNamespace(**data)


def make_template(**overrides):
    data = {
        "id": uuid.uuid4(),
        "name": "rlalab-datasheet-v1",
        "version": 1,
        "description": "Seeded template",
        "is_default": True,
        "created_at": NOW,
        "updated_at": NOW,
        "columns": [
            make_column(),
            make_column(
                key="standard_product_class",
                label="Standard Product Class",
                kind="controlled",
                order_index=1,
                vocabulary=["Organic Acids", "Polyketides"],
                source_hint="any",
            ),
        ],
    }
    data.update(overrides)
    return SimpleNamespace(**data)


def column_payload(**overrides) -> dict:
    data = {
        "key": "carbon_source",
        "label": "carbon source",
        "kind": "free_text",
        "order_index": 0,
        "vocabulary": [],
        "extraction_hint": "Carbon substrate fed.",
        "source_hint": "fulltext",
        "required": False,
        "enabled": True,
    }
    data.update(overrides)
    return data


@asynccontextmanager
async def make_client(user: User):
    async def override_current_user():
        return user

    async def override_db():
        yield DummyDB()

    app.dependency_overrides[deps.get_current_user] = override_current_user
    app.dependency_overrides[deps.get_db] = override_db
    transport = httpx.ASGITransport(app=app)
    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            yield client
    finally:
        app.dependency_overrides.clear()


# ── Admin gate ────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_templates_require_admin() -> None:
    async with make_client(make_researcher()) as client:
        response = await client.get("/api/v1/admin/datasheets/templates")
    assert response.status_code == 403


# ── List ──────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_list_templates_returns_summaries(monkeypatch: pytest.MonkeyPatch) -> None:
    template = make_template()

    async def fake_list(_db):
        return [template]

    monkeypatch.setattr("app.api.routes.admin_datasheet.list_templates", fake_list)

    async with make_client(make_admin()) as client:
        response = await client.get("/api/v1/admin/datasheets/templates")

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["name"] == "rlalab-datasheet-v1"
    assert body[0]["column_count"] == 2
    assert body[0]["enabled_column_count"] == 2


@pytest.mark.asyncio
async def test_list_templates_seeds_default_when_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A fresh database should be usable without a separate provisioning step."""
    seeded: list[str] = []
    template = make_template()

    async def fake_list(_db):
        return [template] if seeded else []

    async def fake_seed(_db):
        seeded.append("called")
        return template, True

    monkeypatch.setattr("app.api.routes.admin_datasheet.list_templates", fake_list)
    monkeypatch.setattr("app.api.routes.admin_datasheet.seed_default_template", fake_seed)

    async with make_client(make_admin()) as client:
        response = await client.get("/api/v1/admin/datasheets/templates")

    assert response.status_code == 200
    assert seeded == ["called"]
    assert len(response.json()) == 1


# ── Get ───────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_template_returns_columns_in_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    template = make_template(
        columns=[
            make_column(key="second", label="Second", order_index=5),
            make_column(key="first", label="First", order_index=1),
        ]
    )

    async def fake_get(_db, name: str):
        assert name == "rlalab-datasheet-v1"
        return template

    monkeypatch.setattr("app.api.routes.admin_datasheet.get_template", fake_get)

    async with make_client(make_admin()) as client:
        response = await client.get(
            "/api/v1/admin/datasheets/templates/rlalab-datasheet-v1"
        )

    assert response.status_code == 200
    assert [column["key"] for column in response.json()["columns"]] == ["first", "second"]


@pytest.mark.asyncio
async def test_get_unknown_template_returns_404(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_get(_db, _name: str):
        return None

    monkeypatch.setattr("app.api.routes.admin_datasheet.get_template", fake_get)

    async with make_client(make_admin()) as client:
        response = await client.get("/api/v1/admin/datasheets/templates/nope")

    assert response.status_code == 404


# ── Create ────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_create_template_passes_columns_through(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict = {}
    template = make_template(name="custom-v1")

    async def fake_create(_db, **kwargs):
        captured.update(kwargs)
        return template

    monkeypatch.setattr("app.api.routes.admin_datasheet.create_template", fake_create)

    async with make_client(make_admin()) as client:
        response = await client.post(
            "/api/v1/admin/datasheets/templates",
            json={
                "name": "custom-v1",
                "description": "Custom",
                "is_default": False,
                "columns": [column_payload(), column_payload(key="yield", label="Yield", order_index=1)],
            },
        )

    assert response.status_code == 201
    assert captured["name"] == "custom-v1"
    assert [column["key"] for column in captured["columns"]] == ["carbon_source", "yield"]


@pytest.mark.asyncio
async def test_create_duplicate_template_name_returns_400(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.datasheet.admin_service import DatasheetTemplateError

    async def fake_create(_db, **_kwargs):
        raise DatasheetTemplateError("A template named 'custom-v1' already exists")

    monkeypatch.setattr("app.api.routes.admin_datasheet.create_template", fake_create)

    async with make_client(make_admin()) as client:
        response = await client.post(
            "/api/v1/admin/datasheets/templates",
            json={"name": "custom-v1", "columns": [column_payload()]},
        )

    assert response.status_code == 400
    assert "already exists" in response.json()["detail"]


@pytest.mark.asyncio
async def test_create_rejects_controlled_column_without_vocabulary() -> None:
    async with make_client(make_admin()) as client:
        response = await client.post(
            "/api/v1/admin/datasheets/templates",
            json={
                "name": "custom-v1",
                "columns": [column_payload(kind="controlled", vocabulary=[])],
            },
        )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_create_rejects_duplicate_column_keys() -> None:
    async with make_client(make_admin()) as client:
        response = await client.post(
            "/api/v1/admin/datasheets/templates",
            json={
                "name": "custom-v1",
                "columns": [column_payload(), column_payload(order_index=1)],
            },
        )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_create_rejects_duplicate_order_index() -> None:
    async with make_client(make_admin()) as client:
        response = await client.post(
            "/api/v1/admin/datasheets/templates",
            json={
                "name": "custom-v1",
                "columns": [column_payload(), column_payload(key="other", label="Other")],
            },
        )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_create_rejects_all_columns_disabled() -> None:
    async with make_client(make_admin()) as client:
        response = await client.post(
            "/api/v1/admin/datasheets/templates",
            json={"name": "custom-v1", "columns": [column_payload(enabled=False)]},
        )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_create_rejects_non_snake_case_key() -> None:
    async with make_client(make_admin()) as client:
        response = await client.post(
            "/api/v1/admin/datasheets/templates",
            json={"name": "custom-v1", "columns": [column_payload(key="Carbon Source")]},
        )
    assert response.status_code == 422


# ── Update ────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_update_template_forwards_column_replacement(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict = {}
    template = make_template(version=2)

    async def fake_update(_db, **kwargs):
        captured.update(kwargs)
        return template

    monkeypatch.setattr("app.api.routes.admin_datasheet.update_template", fake_update)

    async with make_client(make_admin()) as client:
        response = await client.put(
            "/api/v1/admin/datasheets/templates/rlalab-datasheet-v1",
            json={"columns": [column_payload()]},
        )

    assert response.status_code == 200
    assert captured["name"] == "rlalab-datasheet-v1"
    assert len(captured["columns"]) == 1
    assert response.json()["version"] == 2


@pytest.mark.asyncio
async def test_update_description_only_leaves_columns_untouched(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict = {}

    async def fake_update(_db, **kwargs):
        captured.update(kwargs)
        return make_template(description="Revised")

    monkeypatch.setattr("app.api.routes.admin_datasheet.update_template", fake_update)

    async with make_client(make_admin()) as client:
        response = await client.put(
            "/api/v1/admin/datasheets/templates/rlalab-datasheet-v1",
            json={"description": "Revised"},
        )

    assert response.status_code == 200
    assert captured["columns"] is None


@pytest.mark.asyncio
async def test_update_unknown_template_returns_404(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.datasheet.admin_service import DatasheetTemplateError

    async def fake_update(_db, **_kwargs):
        raise DatasheetTemplateError("Template 'nope' not found")

    monkeypatch.setattr("app.api.routes.admin_datasheet.update_template", fake_update)

    async with make_client(make_admin()) as client:
        response = await client.put(
            "/api/v1/admin/datasheets/templates/nope",
            json={"columns": [column_payload()]},
        )

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_update_rejects_empty_column_list() -> None:
    async with make_client(make_admin()) as client:
        response = await client.put(
            "/api/v1/admin/datasheets/templates/rlalab-datasheet-v1",
            json={"columns": []},
        )
    assert response.status_code == 422


# ── Extraction schema ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_extraction_schema_endpoint_reflects_the_template(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The admin editing a column needs to see the effect on the extraction schema."""
    template = make_template()

    async def fake_get(_db, _name: str):
        return template

    monkeypatch.setattr("app.api.routes.admin_datasheet.get_template", fake_get)

    async with make_client(make_admin()) as client:
        response = await client.get(
            "/api/v1/admin/datasheets/templates/rlalab-datasheet-v1/extraction-schema"
        )

    assert response.status_code == 200
    body = response.json()
    assert body["enabled_columns"] == ["carbon_source", "standard_product_class"]
    schema = body["json_schema"]
    assert schema["additionalProperties"] is False
    enum = schema["properties"]["standard_product_class"]["properties"]["value"]["enum"]
    assert enum == ["Organic Acids", "Polyketides", "Not reported"]


@pytest.mark.asyncio
async def test_extraction_schema_excludes_disabled_columns(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    template = make_template(
        columns=[
            make_column(key="kept", label="Kept", order_index=0),
            make_column(key="dropped", label="Dropped", order_index=1, enabled=False),
        ]
    )

    async def fake_get(_db, _name: str):
        return template

    monkeypatch.setattr("app.api.routes.admin_datasheet.get_template", fake_get)

    async with make_client(make_admin()) as client:
        response = await client.get(
            "/api/v1/admin/datasheets/templates/rlalab-datasheet-v1/extraction-schema"
        )

    body = response.json()
    assert body["enabled_columns"] == ["kept"]
    assert set(body["json_schema"]["properties"]) == {"kept"}


@pytest.mark.asyncio
async def test_seed_default_endpoint_is_idempotent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    template = make_template()
    calls: list[bool] = []

    async def fake_seed(_db):
        calls.append(True)
        return template, False

    monkeypatch.setattr("app.api.routes.admin_datasheet.seed_default_template", fake_seed)

    async with make_client(make_admin()) as client:
        first = await client.post("/api/v1/admin/datasheets/templates/seed-default")
        second = await client.post("/api/v1/admin/datasheets/templates/seed-default")

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["name"] == second.json()["name"]
    assert len(calls) == 2


# ── Seed lookup (S1) ──────────────────────────────────────────────────────────


def make_organism_seed():
    from pipelines.discovery.taxonomy import OrganismSeed

    return OrganismSeed(
        taxid=4952,
        scientific_name="Yarrowia lipolytica",
        rank="species",
        synonyms=("Candida lipolytica", "Endomycopsis lipolytica", "Mycotorula lipolytica"),
        lineage=("Fungi", "Ascomycota", "Yarrowia"),
    )


def make_product_seed():
    from pipelines.discovery.product import ProductSeed

    return ProductSeed(
        cid=72281,
        preferred_name="hesperetin",
        synonyms=("Hesperitin", "3',5,7-Trihydroxy-4'-methoxyflavanone"),
        chebi_id="CHEBI:28230",
        molecular_formula="C16H14O6",
        product_class="Flavonoids & Polyphenols",
        product_class_evidence="flavanone",
    )


@pytest.mark.asyncio
async def test_seed_lookup_requires_admin() -> None:
    async with make_client(make_researcher()) as client:
        response = await client.get("/api/v1/admin/datasheets/lookup/organism?q=yarrowia")
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_organism_lookup_returns_suggestions_without_resolving(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The typeahead path must stay cheap: one upstream search, no efetch."""
    from pipelines.discovery.taxonomy import OrganismSuggestion

    resolved: list[str] = []

    async def fake_suggest(query, *, limit=10):
        return [OrganismSuggestion(taxid=4952, scientific_name="Yarrowia lipolytica", rank="species")]

    async def fake_resolve(**kwargs):
        resolved.append("called")
        return None

    monkeypatch.setattr("app.api.routes.admin_datasheet.suggest_organisms", fake_suggest)
    monkeypatch.setattr("app.api.routes.admin_datasheet.resolve_organism_seed", fake_resolve)

    async with make_client(make_admin()) as client:
        response = await client.get("/api/v1/admin/datasheets/lookup/organism?q=Yarrowia+lipo")

    assert response.status_code == 200
    body = response.json()
    assert body["suggestions"][0]["taxid"] == 4952
    assert body["seed"] is None
    assert resolved == []


@pytest.mark.asyncio
async def test_organism_lookup_by_taxid_returns_the_synonym_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The S1 acceptance shape: taxid 4952 plus the three historical synonyms, and
    the search-term list discovery will actually query with."""

    async def fake_resolve(*, query=None, taxid=None, extra_synonyms=()):
        assert taxid == 4952
        return make_organism_seed()

    monkeypatch.setattr("app.api.routes.admin_datasheet.resolve_organism_seed", fake_resolve)

    async with make_client(make_admin()) as client:
        response = await client.get("/api/v1/admin/datasheets/lookup/organism?taxid=4952")

    assert response.status_code == 200
    seed = response.json()["seed"]
    assert seed["taxid"] == 4952
    assert seed["synonyms"] == [
        "Candida lipolytica",
        "Endomycopsis lipolytica",
        "Mycotorula lipolytica",
    ]
    assert seed["search_terms"][0] == "Yarrowia lipolytica"
    assert len(seed["search_terms"]) == 4


@pytest.mark.asyncio
async def test_organism_lookup_needs_a_query_or_a_taxid() -> None:
    async with make_client(make_admin()) as client:
        response = await client.get("/api/v1/admin/datasheets/lookup/organism?q=+")
    assert response.status_code == 400
    assert "q or taxid" in response.json()["detail"]


@pytest.mark.asyncio
async def test_product_lookup_returns_the_seed_and_the_controlled_vocabulary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The vocabulary ships with the response so the wizard can offer it when no
    rule matched, without a second request."""

    async def fake_resolve(*, query=None, cid=None):
        return make_product_seed()

    monkeypatch.setattr("app.api.routes.admin_datasheet.resolve_product_seed", fake_resolve)

    async with make_client(make_admin()) as client:
        response = await client.get("/api/v1/admin/datasheets/lookup/product?cid=72281")

    assert response.status_code == 200
    body = response.json()
    assert body["seed"]["cid"] == 72281
    assert body["seed"]["product_class"] == "Flavonoids & Polyphenols"
    assert body["seed"]["product_class_evidence"] == "flavanone"
    assert body["seed"]["chebi_id"] == "CHEBI:28230"
    assert "Flavonoids & Polyphenols" in body["product_classes"]
    assert len(body["product_classes"]) == 17


@pytest.mark.asyncio
async def test_product_lookup_needs_a_query_or_a_cid() -> None:
    async with make_client(make_admin()) as client:
        response = await client.get("/api/v1/admin/datasheets/lookup/product")
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_an_unknown_seed_is_a_null_seed_not_an_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_suggest(query, *, limit=10):
        return []

    async def fake_resolve(**kwargs):
        return None

    monkeypatch.setattr("app.api.routes.admin_datasheet.suggest_products", fake_suggest)
    monkeypatch.setattr("app.api.routes.admin_datasheet.resolve_product_seed", fake_resolve)

    async with make_client(make_admin()) as client:
        response = await client.get(
            "/api/v1/admin/datasheets/lookup/product?q=zorblaxine&resolve=true"
        )

    assert response.status_code == 200
    assert response.json() == {
        "query": "zorblaxine",
        "suggestions": [],
        "seed": None,
        "product_classes": response.json()["product_classes"],
    }
