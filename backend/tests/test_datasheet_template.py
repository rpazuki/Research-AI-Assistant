"""Tests for the pure datasheet template -> extraction schema translation."""

from __future__ import annotations

import pytest

from pipelines.extraction.default_template import (
    DEFAULT_COLUMNS,
    DEFAULT_TEMPLATE_NAME,
    STANDARD_PRODUCT_CLASSES,
    default_column_rows,
)
from pipelines.extraction.template import (
    NOT_REPORTED,
    ColumnSpec,
    build_extraction_schema,
    column_labels,
    column_specs_from_rows,
    enabled_columns,
)


def make_spec(**overrides) -> ColumnSpec:
    data = {
        "key": "carbon_source",
        "label": "carbon source",
        "kind": "free_text",
        "order_index": 0,
    }
    data.update(overrides)
    return ColumnSpec(**data)


# ── ColumnSpec validation ─────────────────────────────────────────────────────

def test_column_spec_rejects_unknown_kind() -> None:
    with pytest.raises(ValueError, match="Unknown column kind"):
        make_spec(kind="magic")


def test_column_spec_rejects_unknown_source_hint() -> None:
    with pytest.raises(ValueError, match="Unknown source_hint"):
        make_spec(source_hint="telepathy")


def test_column_spec_rejects_controlled_without_vocabulary() -> None:
    with pytest.raises(ValueError, match="empty vocabulary"):
        make_spec(kind="controlled")


def test_column_spec_rejects_empty_label() -> None:
    with pytest.raises(ValueError, match="label must not be empty"):
        make_spec(label="")


def test_column_specs_from_rows_rejects_duplicate_keys() -> None:
    rows = [
        {"key": "a", "label": "A", "kind": "free_text", "order_index": 0},
        {"key": "a", "label": "A again", "kind": "free_text", "order_index": 1},
    ]
    with pytest.raises(ValueError, match="Duplicate column key"):
        column_specs_from_rows(rows)


def test_column_specs_from_rows_rejects_duplicate_order_index() -> None:
    rows = [
        {"key": "a", "label": "A", "kind": "free_text", "order_index": 0},
        {"key": "b", "label": "B", "kind": "free_text", "order_index": 0},
    ]
    with pytest.raises(ValueError, match="Duplicate order_index"):
        column_specs_from_rows(rows)


def test_column_specs_from_rows_sorts_by_order_index() -> None:
    rows = [
        {"key": "second", "label": "Second", "kind": "free_text", "order_index": 5},
        {"key": "first", "label": "First", "kind": "free_text", "order_index": 1},
    ]
    specs = column_specs_from_rows(rows)
    assert [spec.key for spec in specs] == ["first", "second"]


# ── enabled_columns / column_labels ───────────────────────────────────────────

def test_disabled_columns_are_excluded_from_labels_and_schema() -> None:
    specs = [
        make_spec(key="kept", label="Kept", order_index=0),
        make_spec(key="dropped", label="Dropped", order_index=1, enabled=False),
    ]
    assert column_labels(specs) == ["Kept"]
    assert enabled_columns(specs) == [specs[0]]
    schema = build_extraction_schema(specs)
    assert set(schema["properties"]) == {"kept"}


def test_build_extraction_schema_rejects_all_disabled() -> None:
    specs = [make_spec(enabled=False)]
    with pytest.raises(ValueError, match="no enabled columns"):
        build_extraction_schema(specs)


# ── Schema shape ──────────────────────────────────────────────────────────────

def test_schema_is_strict_and_requires_every_enabled_column() -> None:
    specs = [
        make_spec(key="a", label="A", order_index=0),
        make_spec(key="b", label="B", order_index=1),
    ]
    schema = build_extraction_schema(specs)
    assert schema["additionalProperties"] is False
    assert sorted(schema["required"]) == ["a", "b"]
    for cell in schema["properties"].values():
        assert cell["additionalProperties"] is False
        assert sorted(cell["required"]) == [
            "confidence",
            "evidence_quote",
            "evidence_section",
            "value",
        ]


def test_controlled_column_emits_enum_including_not_reported() -> None:
    specs = [
        make_spec(
            key="standard_product_class",
            label="Standard Product Class",
            kind="controlled",
            vocabulary=["Organic Acids", "Polyketides"],
        )
    ]
    value_schema = build_extraction_schema(specs)["properties"]["standard_product_class"][
        "properties"
    ]["value"]
    assert value_schema["enum"] == ["Organic Acids", "Polyketides", NOT_REPORTED]


def test_controlled_column_does_not_duplicate_not_reported() -> None:
    specs = [
        make_spec(kind="controlled", vocabulary=["Organic Acids", NOT_REPORTED]),
    ]
    value_schema = build_extraction_schema(specs)["properties"]["carbon_source"][
        "properties"
    ]["value"]
    assert value_schema["enum"].count(NOT_REPORTED) == 1


def test_free_text_column_has_no_enum() -> None:
    schema = build_extraction_schema([make_spec()])
    assert "enum" not in schema["properties"]["carbon_source"]["properties"]["value"]


def test_cell_description_carries_hint_and_not_reported_instruction() -> None:
    specs = [make_spec(extraction_hint="Carbon substrate fed.", source_hint="fulltext")]
    description = build_extraction_schema(specs)["properties"]["carbon_source"][
        "properties"
    ]["value"]["description"]
    assert "Carbon substrate fed." in description
    assert NOT_REPORTED in description
    # fulltext columns warn the model not to expect the value in the abstract.
    assert "Methods or Results" in description


# ── The seeded default template ───────────────────────────────────────────────

EXCEL_HEADERS = [
    "Date",
    "Family of Compounds",
    "Standard Product Class",
    "Compounds",
    "Concentration/Yield",
    "Extra conditions or comparison for this concentration/Yield",
    "Article",
    "Authors",
    "Corresponding Authors",
    "Acknowledgement",
    "strain used/RLA collection strain",
    "genetic engineering strategy used",
    "carbon source",
    "cultivation mode",
    "Comments",
    "Application",
    "Link",
]


def test_default_template_matches_the_excel_headers_in_order() -> None:
    """The export must drop into the curators' existing spreadsheet workflow, so
    labels and their order are transcribed from the source file, not restyled."""
    specs = column_specs_from_rows(default_column_rows())
    assert column_labels(specs) == EXCEL_HEADERS


def test_default_template_has_seventeen_columns() -> None:
    assert len(DEFAULT_COLUMNS) == 17


def test_default_template_product_class_vocabulary_is_the_observed_seventeen() -> None:
    assert len(STANDARD_PRODUCT_CLASSES) == 17
    assert len(set(STANDARD_PRODUCT_CLASSES)) == 17
    assert "Lipids & Fatty Acids" in STANDARD_PRODUCT_CLASSES
    assert "Vitamins & Cofactors" in STANDARD_PRODUCT_CLASSES


def test_default_template_builds_a_valid_extraction_schema() -> None:
    specs = column_specs_from_rows(default_column_rows())
    schema = build_extraction_schema(specs)
    assert len(schema["properties"]) == 17
    assert len(schema["required"]) == 17
    enum = schema["properties"]["standard_product_class"]["properties"]["value"]["enum"]
    assert len(enum) == 18  # 17 classes + NOT_REPORTED


def test_default_template_keys_are_machine_safe() -> None:
    for column in DEFAULT_COLUMNS:
        key = column["key"]
        assert key.islower()
        assert key.replace("_", "").isalnum(), key


def test_methods_section_columns_are_marked_fulltext() -> None:
    """docs/investigation_summary.md §3 measures these at ~10% from abstracts and
    ~90% with full text, so the extractor is told not to expect them earlier."""
    hints = {column["key"]: column["source_hint"] for column in DEFAULT_COLUMNS}
    for key in (
        "strain_used",
        "genetic_engineering_strategy",
        "carbon_source",
        "cultivation_mode",
        "concentration_yield",
    ):
        assert hints[key] == "fulltext", key


def test_strain_column_hint_forbids_transliterating_delta() -> None:
    """PDF extraction mangling Δ into 'D' is the corpus-specific failure called out
    in docs/INGESTION_PLAN.md §3; the hint has to name it."""
    strain = next(c for c in DEFAULT_COLUMNS if c["key"] == "strain_used")
    assert "Δ" in strain["extraction_hint"]


def test_default_column_rows_returns_independent_vocabulary_lists() -> None:
    first = default_column_rows()
    first[2]["vocabulary"].append("Injected")
    assert "Injected" not in STANDARD_PRODUCT_CLASSES
    assert "Injected" not in default_column_rows()[2]["vocabulary"]


def test_default_template_name_is_stable() -> None:
    assert DEFAULT_TEMPLATE_NAME == "rlalab-datasheet-v1"
