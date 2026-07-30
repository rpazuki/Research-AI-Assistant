"""
app/datasheet/admin_service.py
------------------------------
Datasheet template CRUD and the template -> extraction-schema bridge.

The column set is data (see docs/DATASHEET_FEATURE_PLAN.md §4.1), so this module
owns the DB half of that: reading and writing `datasheet_templates` /
`datasheet_template_columns`, and snapshotting a template onto a run. The pure
translation to a JSON schema lives in `pipelines.extraction.template` and is
imported here — pipelines never imports backend code, only the reverse.
"""

from __future__ import annotations

import sys
import uuid
from pathlib import Path
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models import DatasheetTemplate, DatasheetTemplateColumn

_BACKEND_DIR = Path(__file__).resolve().parents[2]
# In the Docker image `pipelines` is copied inside backend/; locally it is a sibling.
_REPO_ROOT = _BACKEND_DIR if (_BACKEND_DIR / "pipelines").exists() else _BACKEND_DIR.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from pipelines.extraction.default_template import (  # noqa: E402
    DEFAULT_TEMPLATE_DESCRIPTION,
    DEFAULT_TEMPLATE_NAME,
    default_column_rows,
)
from pipelines.extraction.template import (  # noqa: E402
    build_extraction_schema,
    column_specs_from_rows,
    enabled_columns,
)


class DatasheetTemplateError(Exception):
    """Raised for caller-fixable template problems (duplicate name, bad columns)."""


# ── Reads ─────────────────────────────────────────────────────────────────────

async def list_templates(db: AsyncSession) -> list[DatasheetTemplate]:
    result = await db.execute(
        select(DatasheetTemplate)
        .options(selectinload(DatasheetTemplate.columns))
        .order_by(DatasheetTemplate.is_default.desc(), DatasheetTemplate.name)
    )
    return list(result.scalars().all())


async def get_template(db: AsyncSession, name: str) -> DatasheetTemplate | None:
    result = await db.execute(
        select(DatasheetTemplate)
        .options(selectinload(DatasheetTemplate.columns))
        .where(DatasheetTemplate.name == name)
    )
    return result.scalar_one_or_none()


async def get_default_template(db: AsyncSession) -> DatasheetTemplate | None:
    """The default template, falling back to the seeded one by name so a database
    where no row is flagged still resolves."""
    result = await db.execute(
        select(DatasheetTemplate)
        .options(selectinload(DatasheetTemplate.columns))
        .where(DatasheetTemplate.is_default.is_(True))
        .order_by(DatasheetTemplate.updated_at.desc())
        .limit(1)
    )
    template = result.scalar_one_or_none()
    if template is not None:
        return template
    return await get_template(db, DEFAULT_TEMPLATE_NAME)


# ── Writes ────────────────────────────────────────────────────────────────────

async def create_template(
    db: AsyncSession,
    *,
    name: str,
    description: str | None,
    is_default: bool,
    columns: list[dict[str, Any]],
    created_by_user_id: uuid.UUID | None = None,
) -> DatasheetTemplate:
    if await get_template(db, name) is not None:
        raise DatasheetTemplateError(f"A template named '{name}' already exists")

    _validate_columns(columns)

    template = DatasheetTemplate(
        # Assigned client-side rather than left to the column default so the id
        # exists before any flush. `_clear_other_defaults` needs a real id: with a
        # None id, `id != NULL` compiles to `IS NOT NULL` and clears every row,
        # including the one being created.
        id=uuid.uuid4(),
        name=name,
        version=1,
        description=description,
        is_default=is_default,
        created_by_user_id=created_by_user_id,
    )
    template.columns = [DatasheetTemplateColumn(**_column_kwargs(column)) for column in columns]
    db.add(template)

    if is_default:
        await _clear_other_defaults(db, keep_id=template.id)

    try:
        await db.commit()
    except IntegrityError as exc:  # pragma: no cover - guarded above, kept for safety
        await db.rollback()
        raise DatasheetTemplateError(str(exc.orig)) from exc

    refreshed = await get_template(db, name)
    assert refreshed is not None
    return refreshed


async def update_template(
    db: AsyncSession,
    *,
    name: str,
    description: str | None = None,
    is_default: bool | None = None,
    columns: list[dict[str, Any]] | None = None,
) -> DatasheetTemplate:
    template = await get_template(db, name)
    if template is None:
        raise DatasheetTemplateError(f"Template '{name}' not found")

    if description is not None:
        template.description = description

    if columns is not None:
        _validate_columns(columns)
        # Replace the whole set. Rows already extracted under the old version keep
        # their own template_snapshot, so bumping the version here is safe.
        #
        # The clear-then-flush is load-bearing: `(template_id, key)` and
        # `(template_id, order_index)` are unique, and a single flush does not order
        # the orphan DELETEs before the new INSERTs. Assigning the new list directly
        # raises UniqueViolationError for every key that also exists in the old set —
        # which is nearly all of them on a normal edit. Flush the deletes first.
        template.columns.clear()
        await db.flush()
        template.columns = [
            DatasheetTemplateColumn(**_column_kwargs(column)) for column in columns
        ]
        template.version = int(template.version or 1) + 1

    if is_default is not None:
        template.is_default = is_default
        if is_default:
            await _clear_other_defaults(db, keep_id=template.id)

    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise DatasheetTemplateError(str(exc.orig)) from exc

    refreshed = await get_template(db, name)
    assert refreshed is not None
    return refreshed


async def _clear_other_defaults(db: AsyncSession, *, keep_id: uuid.UUID) -> None:
    """Unset is_default everywhere except `keep_id`.

    A real id is required. `db.execute()` autoflushes the caller's pending change
    first, so an unscoped UPDATE — including one scoped on a None id, which compiles
    to `IS NOT NULL` — clears the flag on the very row being promoted.
    """
    if keep_id is None:
        raise ValueError(
            "_clear_other_defaults requires a concrete keep_id; a NULL id widens the "
            "UPDATE to every row and unsets the default that was just set"
        )
    await db.execute(
        update(DatasheetTemplate)
        .where(DatasheetTemplate.id != keep_id)
        .values(is_default=False)
    )


# ── Seeding ───────────────────────────────────────────────────────────────────

async def seed_default_template(db: AsyncSession) -> tuple[DatasheetTemplate, bool]:
    """Create the 17-column default template if it is missing.

    Idempotent: an existing template is returned untouched, so an admin who has
    since edited the columns does not get them reset by a redeploy.
    Returns (template, created).
    """
    existing = await get_template(db, DEFAULT_TEMPLATE_NAME)
    if existing is not None:
        return existing, False

    template = await create_template(
        db,
        name=DEFAULT_TEMPLATE_NAME,
        description=DEFAULT_TEMPLATE_DESCRIPTION,
        is_default=True,
        columns=default_column_rows(),
    )
    return template, True


# ── Template -> extraction schema ─────────────────────────────────────────────

def template_column_rows(template: DatasheetTemplate) -> list[dict[str, Any]]:
    """Ordered plain-dict view of a template's columns.

    Also the shape stored in `datasheet_runs.template_snapshot`, so a run can be
    reproduced after the live template has moved on.
    """
    return [
        {
            "key": column.key,
            "label": column.label,
            "kind": column.kind,
            "order_index": column.order_index,
            "vocabulary": list(column.vocabulary or []),
            "extraction_hint": column.extraction_hint,
            "source_hint": column.source_hint,
            "required": bool(column.required),
            "enabled": bool(column.enabled),
        }
        for column in sorted(template.columns, key=lambda c: c.order_index)
    ]


def build_template_snapshot(template: DatasheetTemplate) -> dict[str, Any]:
    """Frozen record of the template a run executed against."""
    return {
        "name": template.name,
        "version": int(template.version or 1),
        "columns": template_column_rows(template),
    }


def extraction_schema_for_template(template: DatasheetTemplate) -> dict[str, Any]:
    specs = column_specs_from_rows(template_column_rows(template))
    return build_extraction_schema(specs)


def enabled_column_keys(template: DatasheetTemplate) -> list[str]:
    specs = column_specs_from_rows(template_column_rows(template))
    return [spec.key for spec in enabled_columns(specs)]


# ── Validation ────────────────────────────────────────────────────────────────

def _validate_columns(columns: list[dict[str, Any]]) -> None:
    """Reject a column set the extraction schema could not be built from.

    Pydantic already checks each column in isolation; this catches the set-level
    problems and anything arriving from a non-HTTP caller such as the seeder.
    """
    if not columns:
        raise DatasheetTemplateError("A template needs at least one column")
    try:
        specs = column_specs_from_rows(columns)
        build_extraction_schema(specs)
    except ValueError as exc:
        raise DatasheetTemplateError(str(exc)) from exc


def _column_kwargs(column: dict[str, Any]) -> dict[str, Any]:
    return {
        "key": column["key"],
        "label": column["label"],
        "kind": column["kind"],
        "order_index": int(column["order_index"]),
        "vocabulary": list(column.get("vocabulary") or []) or None,
        "extraction_hint": column.get("extraction_hint"),
        "source_hint": column.get("source_hint") or "any",
        "required": bool(column.get("required", False)),
        "enabled": bool(column.get("enabled", True)),
    }
