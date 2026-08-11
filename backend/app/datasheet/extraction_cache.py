"""
app/datasheet/extraction_cache.py
---------------------------------
Extraction results, reusable across runs (plan §7.2, lever 3).

The key is `(content_sha256, template_version, model)` where the hash is of the
**exact prompt text that was sent** — not of the document. That distinction is the
whole safety property: change section selection or the token budget and the prompt
changes, so the cache misses and the paper is re-extracted, rather than a stored
result standing in for one the current code would not have produced.

Not scoped to a run. Re-running one run is the cheap case; the case that saves real
money is a *second* run whose seed overlaps the first, which a per-run artefact
cannot serve.

Recorded trade-off: the key carries the bulk model only, so changing
`DATASHEET_ESCALATION_MODEL` alone does not invalidate an entry. `escalated_cells`
is stored so that stays visible; if it ever matters, the escalation model joins the
key.
"""

from __future__ import annotations

import logging
import sys
import uuid
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import DatasheetExtractionCache

_BACKEND_DIR = Path(__file__).resolve().parents[2]
_REPO_ROOT = _BACKEND_DIR if (_BACKEND_DIR / "pipelines").exists() else _BACKEND_DIR.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from pipelines.corpus_cache import sha256_bytes  # noqa: E402

logger = logging.getLogger(__name__)


def content_hash(text: str) -> str:
    """Hash of the prompt text as sent. One definition, shared with the corpus cache."""
    return sha256_bytes(text.encode("utf-8"))


async def lookup(
    db: AsyncSession, *, hashes: list[str], template_version: int, model: str
) -> dict[str, dict[str, Any]]:
    """Entries for the hashes that are already extracted, keyed by hash.

    One query for the whole run rather than one per paper: several hundred
    round-trips to decide what to skip would cost more than it saves.
    """
    if not hashes:
        return {}
    result = await db.execute(
        select(DatasheetExtractionCache)
        .where(DatasheetExtractionCache.content_sha256.in_(list(set(hashes))))
        .where(DatasheetExtractionCache.template_version == template_version)
        .where(DatasheetExtractionCache.model == model)
    )
    entries: dict[str, dict[str, Any]] = {}
    for entry in result.scalars():
        entries[entry.content_sha256] = {
            "cells": entry.cells,
            "prompt_tokens": entry.prompt_tokens,
            "completion_tokens": entry.completion_tokens,
            "escalated_cells": entry.escalated_cells,
        }
    return entries


async def store(
    db: AsyncSession,
    *,
    content_sha256: str,
    template_version: int,
    model: str,
    cells: dict[str, Any],
    prompt_tokens: int | None = None,
    completion_tokens: int | None = None,
    escalated_cells: int = 0,
) -> None:
    """Upsert one entry. Called after escalation, so a re-run inherits the escalated
    values too rather than re-paying Opus for the same cells."""
    statement = pg_insert(DatasheetExtractionCache.__table__).values(
        id=uuid.uuid4(),
        content_sha256=content_sha256,
        template_version=template_version,
        model=model,
        cells=cells,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        escalated_cells=escalated_cells,
    )
    await db.execute(
        statement.on_conflict_do_update(
            constraint="uq_datasheet_extraction_cache_key",
            set_={
                "cells": statement.excluded.cells,
                "prompt_tokens": statement.excluded.prompt_tokens,
                "completion_tokens": statement.excluded.completion_tokens,
                "escalated_cells": statement.excluded.escalated_cells,
            },
        )
    )


def escalated_cell_count(cells: dict[str, Any]) -> int:
    return sum(
        1 for cell in cells.values() if isinstance(cell, dict) and cell.get("escalated")
    )
