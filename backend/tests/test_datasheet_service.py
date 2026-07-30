"""Tests for datasheet template service behaviour that the route tests can't see.

These cover ORM-flush ordering, which is invisible to the mocked route tests and
only shows up against a real Postgres (the unique constraints are DB-level).
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest

from app.datasheet import admin_service
from app.datasheet.admin_service import DatasheetTemplateError, update_template


class RecordingColumns(list):
    """List that records `clear()` on a shared timeline."""

    def __init__(self, timeline: list[str], items: list) -> None:
        super().__init__(items)
        self._timeline = timeline

    def clear(self) -> None:
        self._timeline.append("clear")
        super().clear()


class FakeTemplate:
    """Minimal stand-in that records when `columns` is reassigned."""

    def __init__(self, timeline: list[str], columns: list) -> None:
        self._timeline = timeline
        self._columns = RecordingColumns(timeline, columns)
        self.id = uuid.uuid4()
        self.name = "rlalab-datasheet-v1"
        self.version = 1
        self.description = "Seeded"
        self.is_default = True

    @property
    def columns(self):
        return self._columns

    @columns.setter
    def columns(self, value) -> None:
        self._timeline.append("assign")
        self._columns = value


class FakeDB:
    def __init__(self, timeline: list[str]) -> None:
        self._timeline = timeline

    async def flush(self) -> None:
        self._timeline.append("flush")

    async def commit(self) -> None:
        self._timeline.append("commit")

    async def rollback(self) -> None:  # pragma: no cover - not exercised here
        self._timeline.append("rollback")

    async def execute(self, *_args, **_kwargs):
        self._timeline.append("execute")
        return None


def make_column(key: str = "carbon_source", order_index: int = 0):
    return SimpleNamespace(
        key=key,
        label=key.replace("_", " "),
        kind="free_text",
        order_index=order_index,
        vocabulary=None,
        extraction_hint=None,
        source_hint="any",
        required=False,
        enabled=True,
    )


def column_row(key: str = "carbon_source", order_index: int = 0) -> dict:
    return {
        "key": key,
        "label": key.replace("_", " "),
        "kind": "free_text",
        "order_index": order_index,
        "vocabulary": [],
        "extraction_hint": None,
        "source_hint": "any",
        "required": False,
        "enabled": True,
    }


@pytest.mark.asyncio
async def test_update_template_flushes_deletes_before_inserting_replacements(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Regression: replacing a column set must DELETE-then-flush before INSERT.

    `(template_id, key)` and `(template_id, order_index)` are unique, and a single
    flush does not order orphan deletes before the new inserts. Assigning the new
    list directly raises UniqueViolationError for every key present in both sets —
    i.e. nearly every key on a normal edit from the UI.
    """
    timeline: list[str] = []
    template = FakeTemplate(timeline, [make_column()])
    db = FakeDB(timeline)

    async def fake_get_template(_db, _name: str):
        return template

    monkeypatch.setattr(admin_service, "get_template", fake_get_template)

    await update_template(db, name="rlalab-datasheet-v1", columns=[column_row()])

    assert "clear" in timeline, timeline
    assert "flush" in timeline, timeline
    assert timeline.index("clear") < timeline.index("flush") < timeline.index("assign"), (
        f"expected clear -> flush -> assign, got {timeline}"
    )


@pytest.mark.asyncio
async def test_update_template_bumps_version_on_column_replacement(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    timeline: list[str] = []
    template = FakeTemplate(timeline, [make_column()])

    async def fake_get_template(_db, _name: str):
        return template

    monkeypatch.setattr(admin_service, "get_template", fake_get_template)

    await update_template(
        FakeDB(timeline), name="rlalab-datasheet-v1", columns=[column_row()]
    )
    assert template.version == 2


@pytest.mark.asyncio
async def test_update_template_description_only_does_not_touch_columns(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A description edit must not clear the columns or bump the version."""
    timeline: list[str] = []
    template = FakeTemplate(timeline, [make_column()])

    async def fake_get_template(_db, _name: str):
        return template

    monkeypatch.setattr(admin_service, "get_template", fake_get_template)

    await update_template(FakeDB(timeline), name="rlalab-datasheet-v1", description="New")

    assert template.description == "New"
    assert template.version == 1
    assert "clear" not in timeline
    assert "assign" not in timeline


@pytest.mark.asyncio
async def test_update_unknown_template_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_get_template(_db, _name: str):
        return None

    monkeypatch.setattr(admin_service, "get_template", fake_get_template)

    with pytest.raises(DatasheetTemplateError, match="not found"):
        await update_template(FakeDB([]), name="nope", columns=[column_row()])


@pytest.mark.asyncio
async def test_update_template_rejects_invalid_column_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Set-level validation runs before any mutation, so a bad payload from a
    non-HTTP caller cannot half-apply."""
    timeline: list[str] = []
    template = FakeTemplate(timeline, [make_column()])

    async def fake_get_template(_db, _name: str):
        return template

    monkeypatch.setattr(admin_service, "get_template", fake_get_template)

    duplicate = [column_row(), column_row(order_index=1)]  # same key twice
    with pytest.raises(DatasheetTemplateError, match="Duplicate column key"):
        await update_template(FakeDB(timeline), name="rlalab-datasheet-v1", columns=duplicate)

    assert "clear" not in timeline
    assert template.version == 1


# ── create_template default-flag handling ─────────────────────────────────────

class FakeCreateDB(FakeDB):
    """Records the statements create_template issues, so ordering is assertable."""

    def __init__(self, timeline: list[str]) -> None:
        super().__init__(timeline)
        self.statements: list[str] = []

    def add(self, _obj) -> None:
        self._timeline.append("add")

    async def execute(self, statement, *_args, **_kwargs):
        self._timeline.append("execute")
        self.statements.append(str(statement))
        return None


@pytest.mark.asyncio
async def test_create_default_template_flushes_before_clearing_other_defaults(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Regression: promoting a new template must not clear its own default flag.

    An unscoped `UPDATE ... SET is_default = false` also hits the row being created,
    because `db.execute()` autoflushes the pending INSERT first — the seeded default
    template silently came back with is_default = false. A None id is equally bad:
    `id != NULL` compiles to `IS NOT NULL`, matching everything.
    """
    timeline: list[str] = []
    db = FakeCreateDB(timeline)
    created = FakeTemplate(timeline, [make_column()])

    async def fake_get_template(_db, _name: str):
        # None on the pre-flight duplicate check, then the created row on refresh.
        return None if "commit" not in timeline else created

    monkeypatch.setattr(admin_service, "get_template", fake_get_template)

    await admin_service.create_template(
        db,
        name="rlalab-datasheet-v1",
        description="Seeded",
        is_default=True,
        columns=[column_row()],
    )

    # The UPDATE must be scoped to a concrete id, never a blanket clear and never
    # `id IS NOT NULL` (which is what `id != NULL` compiles to).
    assert len(db.statements) == 1
    statement = db.statements[0]
    assert "WHERE datasheet_templates.id != " in statement, statement
    assert "IS NOT NULL" not in statement, statement


@pytest.mark.asyncio
async def test_create_non_default_template_does_not_touch_other_defaults(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    timeline: list[str] = []
    db = FakeCreateDB(timeline)
    created = FakeTemplate(timeline, [make_column()])

    async def fake_get_template(_db, _name: str):
        return None if "commit" not in timeline else created

    monkeypatch.setattr(admin_service, "get_template", fake_get_template)

    await admin_service.create_template(
        db, name="custom-v1", description=None, is_default=False, columns=[column_row()]
    )

    assert db.statements == []


@pytest.mark.asyncio
async def test_clear_other_defaults_rejects_a_null_keep_id() -> None:
    """Guard the footgun directly: `id != NULL` is `IS NOT NULL`, i.e. every row."""
    with pytest.raises(ValueError, match="requires a concrete keep_id"):
        await admin_service._clear_other_defaults(FakeDB([]), keep_id=None)
