"""
app/datasheet/export_service.py
-------------------------------
Phase E: read extracted rows back out — as JSON for the run page, and as the
datasheet CSV.

The CSV is the deliverable this whole feature exists to produce, so it is built
from the persisted rows rather than from anything held in memory during a run: a
download a week later must produce the same file as one taken the moment the run
finished, and must not depend on the run process still existing.

Provenance comes from the candidate (`doi`, `journal`, `oa_status`,
`acquisition_route`, …) and from the row (`source_tier`), joined here rather than
duplicated onto the row at extraction time — the candidate is the record of how
the paper was found and fetched, and copying it would let the two drift.
"""

from __future__ import annotations

import sys
import uuid
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import DatasheetCandidate, DatasheetRow, DatasheetRun

_BACKEND_DIR = Path(__file__).resolve().parents[2]
_REPO_ROOT = _BACKEND_DIR if (_BACKEND_DIR / "pipelines").exists() else _BACKEND_DIR.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from pipelines.extraction.csv_writer import write_datasheet_csv  # noqa: E402
from pipelines.extraction.template import column_specs_from_rows  # noqa: E402


def _provenance(candidate: DatasheetCandidate | None, row: DatasheetRow) -> dict[str, Any]:
    if candidate is None:
        return {"source_tier": row.source_tier}
    return {
        "doi": candidate.doi,
        "pmid": candidate.pmid,
        "journal": candidate.journal,
        "publisher": candidate.publisher,
        "year": candidate.year,
        "oa_status": candidate.oa_status,
        "doc_type": candidate.doc_type,
        "is_review": bool(candidate.is_review),
        "is_retracted": bool(candidate.is_retracted),
        "source_tier": row.source_tier,
        "acquisition_route": candidate.acquisition_route,
        "acquisition_status": candidate.acquisition_status,
    }


async def list_rows(
    db: AsyncSession, run_id: uuid.UUID, *, limit: int = 500, offset: int = 0
) -> list[dict[str, Any]]:
    """Extracted rows with their provenance, newest paper first."""
    result = await db.execute(
        select(DatasheetRow, DatasheetCandidate)
        .join(DatasheetCandidate, DatasheetRow.candidate_id == DatasheetCandidate.id, isouter=True)
        .where(DatasheetRow.run_id == run_id)
        .order_by(DatasheetCandidate.year.desc().nullslast(), DatasheetRow.created_at.asc())
        .limit(limit)
        .offset(offset)
    )
    rows: list[dict[str, Any]] = []
    for row, candidate in result.all():
        rows.append(
            {
                "id": str(row.id),
                "candidate_id": str(row.candidate_id),
                "title": candidate.title if candidate else None,
                "cells": row.cells or {},
                "extraction_model": row.extraction_model,
                "template_version": row.template_version,
                "review_status": row.review_status,
                "prompt_tokens": row.prompt_tokens,
                "completion_tokens": row.completion_tokens,
                **_provenance(candidate, row),
            }
        )
    return rows


async def count_rows(db: AsyncSession, run_id: uuid.UUID) -> int:
    from sqlalchemy import func

    result = await db.execute(
        select(func.count(DatasheetRow.id)).where(DatasheetRow.run_id == run_id)
    )
    return int(result.scalar_one())


CSV_FILE_NAME = "datasheet.csv"


async def run_export_phase(
    db: AsyncSession,
    run: DatasheetRun,
    *,
    cache_root: Path,
    progress=None,
) -> dict[str, Any]:
    """Phase E: write the datasheet to the run's cache and record where it went.

    The HTTP download renders on demand from the same rows, so this file is not
    what a curator normally fetches. It exists because a run's output should be an
    artefact on disk next to the assets it was extracted from — recoverable when
    the database is restored to a different host, and reviewable without the app
    running at all. `csv_path` is stored repo-relative for the reason recorded in
    migration 0007: an absolute path means "wherever the writing process was".
    """
    rows = await count_rows(db, run.id)
    if not rows:
        # Nothing to export is not a failure: a dry run legitimately produces no
        # rows, and writing a header-only file would look like a real datasheet.
        return {"rows": 0, "csv_path": None}

    csv_text = await datasheet_csv_for_run(db, run)
    path = cache_root / CSV_FILE_NAME
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(csv_text, encoding="utf-8")

    from app.ingestion.admin_service import store_cache_path

    run.csv_path = store_cache_path(str(path))
    if progress is not None:
        outcome = progress(f"Wrote {rows} rows to {run.csv_path}", {"rows": rows})
        if hasattr(outcome, "__await__"):
            await outcome
    return {"rows": rows, "csv_path": run.csv_path, "bytes": len(csv_text.encode("utf-8"))}


async def datasheet_csv_for_run(db: AsyncSession, run: DatasheetRun) -> str:
    """Render the datasheet CSV from persisted rows.

    Columns come from the run's frozen `template_snapshot`, not the live template:
    a template edited after the run would otherwise silently re-label or re-order
    a file whose contents were produced under the old column set.
    """
    specs = column_specs_from_rows((run.template_snapshot or {}).get("columns") or [])
    rows = await list_rows(db, run.id, limit=100_000)
    return write_datasheet_csv(rows, specs)
