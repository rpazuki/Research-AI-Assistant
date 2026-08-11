"""
pipelines/extraction/csv_writer.py
----------------------------------
Render extracted rows as the datasheet CSV.

The header is the curators' own 17 columns, in their original spreadsheet order,
followed by a provenance block. That ordering is not cosmetic: this file is meant
to open next to the existing Excel and be comparable column-by-column, so a
reordered or renamed header makes the comparison manual work.

`Not reported` for empty cells, matching the curators' convention and the
extraction schema — so an empty cell and a cell the model declined to fill are the
same string, and gold comparison is like-for-like.

Provenance columns are appended rather than interleaved because they answer a
different question: not "what does the paper say" but "how much of the paper did
we read, and how did we get it". A curator scanning for values should not have to
skip past them.
"""

from __future__ import annotations

import csv
import io
from collections.abc import Iterable
from typing import Any

from pipelines.extraction.default_template import PROVENANCE_COLUMNS
from pipelines.extraction.template import NOT_REPORTED, ColumnSpec, enabled_columns


def provenance_labels() -> list[str]:
    return [column["label"] for column in PROVENANCE_COLUMNS]


def header(specs: list[ColumnSpec]) -> list[str]:
    """Curated column labels in template order, then the provenance block."""
    return [spec.label for spec in enabled_columns(specs)] + provenance_labels()


def _cell_value(cells: dict[str, Any], key: str) -> str:
    """The value of one extracted cell, or the curators' empty marker.

    Cells arrive as `{value, confidence, evidence_quote, evidence_section}`. Only
    the value goes in the CSV — evidence lives in the database, where a reviewer
    can see it beside the row without widening the spreadsheet to 60 columns.
    """
    cell = cells.get(key)
    if cell is None:
        return NOT_REPORTED
    if isinstance(cell, dict):
        value = cell.get("value")
    else:
        value = cell
    text = "" if value is None else str(value).strip()
    return text or NOT_REPORTED


def _provenance_value(row: dict[str, Any], key: str) -> str:
    value = row.get(key)
    if value is None or value == "":
        return NOT_REPORTED
    if isinstance(value, bool):
        return "yes" if value else "no"
    return str(value)


def row_values(row: dict[str, Any], specs: list[ColumnSpec]) -> list[str]:
    """One CSV line for one paper.

    `row` carries `cells` plus the provenance fields (`doi`, `pmid`, `journal`,
    `publisher`, `year`, `oa_status`, `doc_type`, `is_review`, `is_retracted`,
    `source_tier`, `acquisition_route`, `acquisition_status`).
    """
    cells = row.get("cells") or {}
    values = [_cell_value(cells, spec.key) for spec in enabled_columns(specs)]
    values += [_provenance_value(row, column["key"]) for column in PROVENANCE_COLUMNS]
    return values


def write_datasheet_csv(rows: Iterable[dict[str, Any]], specs: list[ColumnSpec]) -> str:
    """Render the datasheet. Returns the CSV text.

    Written to a string rather than a file so the same function serves the HTTP
    download and the on-disk export without one of them reimplementing quoting.
    """
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(header(specs))
    for row in rows:
        writer.writerow(row_values(row, specs))
    return buffer.getvalue()
