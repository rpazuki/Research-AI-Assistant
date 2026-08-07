"""app/schemas/datasheet.py — Datasheet template request/response schemas."""

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

ColumnKind = Literal["bibliographic", "free_text", "controlled", "numeric"]
SourceHint = Literal["metadata", "abstract", "fulltext", "any"]

# snake_case, starts with a letter — keys become JSON schema property names and
# CSV/DB identifiers, so they must be stable and machine-safe.
COLUMN_KEY_PATTERN = r"^[a-z][a-z0-9_]*$"


class DatasheetTemplateColumnPayload(BaseModel):
    """One column as submitted by the admin UI."""

    key: str = Field(min_length=1, max_length=64, pattern=COLUMN_KEY_PATTERN)
    label: str = Field(min_length=1, max_length=200)
    kind: ColumnKind
    order_index: int = Field(ge=0)
    vocabulary: list[str] = Field(default_factory=list, max_length=200)
    extraction_hint: str | None = Field(default=None, max_length=2000)
    source_hint: SourceHint = "any"
    required: bool = False
    enabled: bool = True

    @field_validator("vocabulary")
    @classmethod
    def _strip_vocabulary(cls, value: list[str]) -> list[str]:
        return [item.strip() for item in value if item.strip()]

    @model_validator(mode="after")
    def _controlled_needs_vocabulary(self) -> "DatasheetTemplateColumnPayload":
        if self.kind == "controlled" and not self.vocabulary:
            raise ValueError(
                f"Column '{self.key}' is controlled and needs a non-empty vocabulary"
            )
        return self


class DatasheetTemplateColumnResponse(DatasheetTemplateColumnPayload):
    id: uuid.UUID


class DatasheetTemplateCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=2000)
    is_default: bool = False
    columns: list[DatasheetTemplateColumnPayload] = Field(min_length=1, max_length=200)

    @model_validator(mode="after")
    def _unique_keys_and_order(self) -> "DatasheetTemplateCreate":
        _assert_columns_consistent(self.columns)
        return self


class DatasheetTemplateUpdate(BaseModel):
    """Full replacement of the column set. Partial column edits are not supported:
    reordering is inherently a whole-set operation, and a partial update would let
    the UI create duplicate order_index values."""

    description: str | None = Field(default=None, max_length=2000)
    is_default: bool | None = None
    columns: list[DatasheetTemplateColumnPayload] | None = Field(default=None, max_length=200)

    @model_validator(mode="after")
    def _unique_keys_and_order(self) -> "DatasheetTemplateUpdate":
        if self.columns is not None:
            if not self.columns:
                raise ValueError("A template must keep at least one column")
            _assert_columns_consistent(self.columns)
        return self


class DatasheetTemplateSummary(BaseModel):
    id: uuid.UUID
    name: str
    version: int
    description: str | None = None
    is_default: bool
    column_count: int
    enabled_column_count: int
    created_at: datetime
    updated_at: datetime


class DatasheetTemplateDetail(DatasheetTemplateSummary):
    columns: list[DatasheetTemplateColumnResponse]


class DatasheetExtractionSchemaResponse(BaseModel):
    """The JSON schema the extraction pass would send for this template. Exposed so
    an admin editing columns can see the effect immediately."""

    template_name: str
    template_version: int
    enabled_columns: list[str]
    json_schema: dict[str, Any]


# ── Seed lookup (S1) ──────────────────────────────────────────────────────────


class OrganismSuggestionResponse(BaseModel):
    taxid: int
    scientific_name: str
    rank: str | None = None
    common_name: str | None = None


class OrganismSeedResponse(BaseModel):
    """A resolved organism. `search_terms` is the accepted name plus every synonym,
    and is what discovery queries with — the whole reason the seed exists."""

    taxid: int
    scientific_name: str
    rank: str | None = None
    synonyms: list[str]
    common_names: list[str]
    lineage: list[str]
    search_terms: list[str]


class OrganismLookupResponse(BaseModel):
    query: str
    suggestions: list[OrganismSuggestionResponse]
    seed: OrganismSeedResponse | None = None


class ProductSuggestionResponse(BaseModel):
    name: str
    cid: int | None = None


class ProductSeedResponse(BaseModel):
    """A resolved compound. `product_class` is null when no rule matched — the
    wizard asks the admin to pick rather than showing a guessed class."""

    cid: int
    preferred_name: str
    synonyms: list[str]
    chebi_id: str | None = None
    inchikey: str | None = None
    molecular_formula: str | None = None
    molecular_weight: str | None = None
    iupac_name: str | None = None
    chebi_label: str | None = None
    chebi_definition: str | None = None
    product_class: str | None = None
    product_class_evidence: str | None = None
    search_terms: list[str]


class ProductLookupResponse(BaseModel):
    query: str
    suggestions: list[ProductSuggestionResponse]
    seed: ProductSeedResponse | None = None
    product_classes: list[str]


def _assert_columns_consistent(columns: list[DatasheetTemplateColumnPayload]) -> None:
    keys = [column.key for column in columns]
    duplicate_keys = {key for key in keys if keys.count(key) > 1}
    if duplicate_keys:
        raise ValueError(f"Duplicate column keys: {sorted(duplicate_keys)}")

    orders = [column.order_index for column in columns]
    duplicate_orders = {order for order in orders if orders.count(order) > 1}
    if duplicate_orders:
        raise ValueError(f"Duplicate order_index values: {sorted(duplicate_orders)}")

    if not any(column.enabled for column in columns):
        raise ValueError("At least one column must be enabled")


# ── Runs and candidates (S2) ──────────────────────────────────────────────────


class DatasheetRunCreate(BaseModel):
    """A run is created from an already-resolved seed.

    The synonym sets are sent explicitly rather than re-resolved server-side so the
    curator's reviewed term list is exactly what gets searched — including any
    literature synonym NCBI does not carry (e.g. `Saccharomycopsis lipolytica`).
    """

    name: str = Field(min_length=1, max_length=200)
    seed_kind: Literal["organism", "bioproduct", "organism_and_product"]
    organism_name: str | None = Field(default=None, max_length=300)
    organism_taxid: int | None = Field(default=None, ge=1)
    organism_synonyms: list[str] = Field(default_factory=list)
    product_term: str | None = Field(default=None, max_length=300)
    product_ids: dict[str, Any] | None = None
    product_synonyms: list[str] = Field(default_factory=list)
    product_classes: list[str] | None = None
    year_from: int | None = Field(default=None, ge=1500, le=2100)
    year_to: int | None = Field(default=None, ge=1500, le=2100)
    template_name: str = Field(default="rlalab-datasheet-v1", max_length=200)
    sources: list[str] = Field(default_factory=list)
    max_records_per_source: int = Field(default=6000, ge=1, le=20000)
    include_mentions: bool = False
    include_reviews: bool = False
    check_retraction_notices: bool = False

    @model_validator(mode="after")
    def _check_seed(self) -> "DatasheetRunCreate":
        if self.seed_kind in {"organism", "organism_and_product"} and not self.organism_synonyms:
            raise ValueError("organism_synonyms is required for an organism seed")
        if self.seed_kind in {"bioproduct", "organism_and_product"} and not self.product_synonyms:
            raise ValueError("product_synonyms is required for a bioproduct seed")
        if self.year_from and self.year_to and self.year_from > self.year_to:
            raise ValueError("year_from must not be after year_to")
        return self


class DatasheetRunSummary(BaseModel):
    id: uuid.UUID
    name: str
    status: str
    phase: str | None = None
    seed_kind: str
    organism_name: str | None = None
    organism_taxid: int | None = None
    product_term: str | None = None
    year_from: int | None = None
    year_to: int | None = None
    candidate_count: int | None = None
    progress_message: str | None = None
    error: str | None = None
    # Repo-relative (migration 0007). Surfaced so the ingestion config editor can
    # offer a finished run as a corpus source without anyone retyping a path
    # whose last segment is a UUID fragment.
    cache_path: str | None = None
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None


class DatasheetRunDetail(DatasheetRunSummary):
    organism_synonyms: list[str] = Field(default_factory=list)
    product_synonyms: list[str] = Field(default_factory=list)
    product_classes: list[str] = Field(default_factory=list)
    template_name: str | None = None
    template_version: int | None = None
    log_tail: str | None = None
    candidate_counts: dict[str, int] = Field(default_factory=dict)
    discovery_summary: dict[str, Any] | None = None
    acquisition_summary: dict[str, Any] | None = None
    acquired_count: int | None = None


class DatasheetCandidateResponse(BaseModel):
    id: uuid.UUID
    doi: str | None = None
    pmid: str | None = None
    pmc_id: str | None = None
    title: str | None = None
    journal: str | None = None
    publisher: str | None = None
    year: int | None = None
    found_in: list[str] = Field(default_factory=list)
    oa_status: str | None = None
    license: str | None = None
    is_preprint: bool = False
    preprint_doi: str | None = None
    version_of_record_doi: str | None = None
    doc_type: str | None = None
    is_review: bool = False
    is_retracted: bool = False
    relevance: str
    relevance_reason: str | None = None
    acquisition_status: str
    acquisition_route: str | None = None
    dedupe_group: str | None = None
    # Suspicion recorded during discovery, never acted on: these rows share a title
    # but were kept separate, because merging two distinct works is worse than
    # ingesting one work twice.
    possible_duplicate_of: list[str] = Field(default_factory=list)
    duplicate_evidence: str | None = None
    notes: str | None = None
