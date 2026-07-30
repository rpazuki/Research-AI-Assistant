"""
pipelines/extraction/template.py
--------------------------------
Pure helpers that turn a datasheet column template into an extraction JSON schema.

The column set is data, not code: admins edit `datasheet_template_columns` and the
extraction schema follows automatically. This module holds the pure half of that
translation so it can be tested without a database or an LLM provider.

Design notes:
    - Every cell is an object, not a bare string: the extractor must return the
      value together with its confidence and the quote it came from. Provenance is
      what makes a cell auditable against the gold set.
    - Controlled columns carry an `enum`. NOT_REPORTED is always a legal member so
      the model never has to invent a class to satisfy the schema.
    - Schemas are emitted strict (`additionalProperties: false`, every property
      required) so the provider can validate them server-side.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# Curators write this string rather than leaving a cell empty; the extractor
# follows the same convention so gold comparison is like-for-like.
NOT_REPORTED = "Not reported"

COLUMN_KINDS = {
    "bibliographic",  # recoverable from structured metadata (title, authors, DOI)
    "free_text",      # prose value, no fixed vocabulary
    "controlled",     # value must come from `vocabulary`
    "numeric",        # prose value that a later pass parses into numbers
}

SOURCE_HINTS = {"metadata", "abstract", "fulltext", "any"}

EVIDENCE_SECTIONS = [
    "title",
    "abstract",
    "introduction",
    "methods",
    "results",
    "discussion",
    "supplementary",
    "metadata",
    "not_found",
]


@dataclass(frozen=True)
class ColumnSpec:
    """One datasheet column. Mirrors a `datasheet_template_columns` row."""

    key: str
    label: str
    kind: str
    order_index: int
    extraction_hint: str | None = None
    vocabulary: list[str] = field(default_factory=list)
    source_hint: str = "any"
    required: bool = False
    enabled: bool = True

    def __post_init__(self) -> None:
        if not self.key:
            raise ValueError("ColumnSpec.key must not be empty")
        if not self.label:
            raise ValueError(f"ColumnSpec.label must not be empty (key={self.key!r})")
        if self.kind not in COLUMN_KINDS:
            raise ValueError(
                f"Unknown column kind {self.kind!r} for {self.key!r}. "
                f"Expected one of {sorted(COLUMN_KINDS)}"
            )
        if self.source_hint not in SOURCE_HINTS:
            raise ValueError(
                f"Unknown source_hint {self.source_hint!r} for {self.key!r}. "
                f"Expected one of {sorted(SOURCE_HINTS)}"
            )
        if self.kind == "controlled" and not self.vocabulary:
            raise ValueError(
                f"Column {self.key!r} is controlled but has an empty vocabulary"
            )


def column_specs_from_rows(rows: list[dict[str, Any]]) -> list[ColumnSpec]:
    """Build ordered ColumnSpecs from ORM rows or a template snapshot."""
    specs = [
        ColumnSpec(
            key=row["key"],
            label=row["label"],
            kind=row["kind"],
            order_index=int(row["order_index"]),
            extraction_hint=row.get("extraction_hint"),
            vocabulary=list(row.get("vocabulary") or []),
            source_hint=row.get("source_hint") or "any",
            required=bool(row.get("required", False)),
            enabled=bool(row.get("enabled", True)),
        )
        for row in rows
    ]
    _assert_unique(specs)
    return sorted(specs, key=lambda spec: spec.order_index)


def _assert_unique(specs: list[ColumnSpec]) -> None:
    seen_keys: set[str] = set()
    seen_order: set[int] = set()
    for spec in specs:
        if spec.key in seen_keys:
            raise ValueError(f"Duplicate column key {spec.key!r}")
        if spec.order_index in seen_order:
            raise ValueError(
                f"Duplicate order_index {spec.order_index} at column {spec.key!r}"
            )
        seen_keys.add(spec.key)
        seen_order.add(spec.order_index)


def enabled_columns(specs: list[ColumnSpec]) -> list[ColumnSpec]:
    """Ordered enabled columns. Disabled columns stay in the template but are
    neither extracted nor exported."""
    return [spec for spec in sorted(specs, key=lambda s: s.order_index) if spec.enabled]


def column_labels(specs: list[ColumnSpec]) -> list[str]:
    """Export header labels, in template order. Enabled columns only."""
    return [spec.label for spec in enabled_columns(specs)]


def _cell_description(spec: ColumnSpec) -> str:
    parts = [f"Datasheet column '{spec.label}'."]
    if spec.extraction_hint:
        parts.append(spec.extraction_hint)
    if spec.source_hint == "fulltext":
        parts.append(
            "This is usually a Methods or Results fact and is rarely stated in the abstract."
        )
    elif spec.source_hint == "metadata":
        parts.append("This is normally available from the article's bibliographic metadata.")
    parts.append(f"If the provided text does not state it, return '{NOT_REPORTED}'.")
    return " ".join(parts)


def _cell_schema(spec: ColumnSpec) -> dict[str, Any]:
    value_schema: dict[str, Any] = {
        "type": "string",
        "description": _cell_description(spec),
    }
    if spec.kind == "controlled":
        # NOT_REPORTED is always legal so an absent value never forces a guess.
        vocabulary = list(spec.vocabulary)
        if NOT_REPORTED not in vocabulary:
            vocabulary.append(NOT_REPORTED)
        value_schema["enum"] = vocabulary

    return {
        "type": "object",
        "description": f"Extracted value and provenance for '{spec.label}'.",
        "properties": {
            "value": value_schema,
            "confidence": {
                "type": "number",
                "description": (
                    "0.0-1.0 confidence that this value is correct and belongs to "
                    "the paper being read (not to work it cites)."
                ),
            },
            "evidence_quote": {
                "type": "string",
                "description": (
                    "Verbatim span from the supplied text supporting the value. "
                    f"Empty string when the value is '{NOT_REPORTED}'."
                ),
            },
            "evidence_section": {
                "type": "string",
                "enum": EVIDENCE_SECTIONS,
                "description": "Section the evidence came from.",
            },
        },
        "required": ["value", "confidence", "evidence_quote", "evidence_section"],
        "additionalProperties": False,
    }


def build_extraction_schema(specs: list[ColumnSpec]) -> dict[str, Any]:
    """Build a strict JSON schema for one paper's extraction pass.

    One property per enabled column; each is a cell object carrying the value plus
    its provenance. Strict (`additionalProperties: false` and every property
    required) so the provider can enforce it rather than us parsing loosely.
    """
    columns = enabled_columns(specs)
    if not columns:
        raise ValueError("Cannot build an extraction schema with no enabled columns")

    properties = {spec.key: _cell_schema(spec) for spec in columns}
    return {
        "type": "object",
        "properties": properties,
        "required": [spec.key for spec in columns],
        "additionalProperties": False,
    }
