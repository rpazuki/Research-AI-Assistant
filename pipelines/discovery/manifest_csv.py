"""The discovery manifest CSV — every candidate, and why it was kept or dropped.

The point of the file is auditability. A curator must be able to see that a paper
was found only by Crossref, judged `mentions` because the organism appears once
outside the title, and therefore excluded — and disagree. A filter whose decisions
are invisible is a filter nobody can trust, and this corpus's whole problem is
silent omission.

`Not reported` for empty cells, matching the curators' own convention in the Excel.
"""

from __future__ import annotations

import csv
import io
from collections.abc import Iterable

from pipelines.discovery.canonicalize import Candidate

NOT_REPORTED = "Not reported"

COLUMNS: tuple[str, ...] = (
    "doi",
    "pmid",
    "pmc_id",
    "title",
    "journal",
    "publisher",
    "year",
    "found_in",
    "included",
    "relevance",
    "relevance_reason",
    "doc_type",
    "is_review",
    "is_retracted",
    "retraction_note",
    "is_preprint",
    "preprint_doi",
    "version_of_record_doi",
    "oa_status",
    "license",
    "dedupe_group",
    "merged_identifiers",
    "possible_duplicate_of",
    "duplicate_evidence",
    "url",
)


def _cell(value: object) -> str:
    if value is None or value == "" or value == ():
        return NOT_REPORTED
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, (list, tuple)):
        return "; ".join(str(item) for item in value) or NOT_REPORTED
    return str(value)


def candidate_row(candidate: Candidate, *, included: bool) -> dict[str, str]:
    row = {
        "doi": candidate.doi,
        "pmid": candidate.pmid,
        "pmc_id": candidate.pmc_id,
        "title": candidate.title,
        "journal": candidate.journal,
        "publisher": candidate.publisher,
        "year": candidate.year,
        "found_in": candidate.found_in,
        "included": included,
        "relevance": candidate.relevance,
        "relevance_reason": candidate.relevance_reason,
        "doc_type": candidate.doc_type,
        "is_review": candidate.is_review,
        "is_retracted": candidate.is_retracted,
        "retraction_note": candidate.retraction_note,
        "is_preprint": candidate.is_preprint,
        "preprint_doi": candidate.preprint_doi,
        "version_of_record_doi": candidate.version_of_record_doi,
        "oa_status": candidate.oa_status,
        "license": candidate.license,
        "dedupe_group": candidate.dedupe_group,
        "merged_identifiers": candidate.merged_identifiers,
        "possible_duplicate_of": candidate.possible_duplicate_of,
        "duplicate_evidence": candidate.duplicate_evidence,
        "url": candidate.url,
    }
    return {key: _cell(value) for key, value in row.items()}


def write_manifest_csv(
    candidates: Iterable[Candidate], *, included_dois: set[str] | None = None
) -> str:
    """Render the manifest. `included_dois` marks which rows proceed to acquisition."""
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=list(COLUMNS), extrasaction="raise")
    writer.writeheader()

    for candidate in candidates:
        included = True if included_dois is None else (candidate.doi or "") in included_dois
        writer.writerow(candidate_row(candidate, included=included))

    return buffer.getvalue()
