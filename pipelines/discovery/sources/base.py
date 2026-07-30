"""The common record every discovery source produces, and the query they take.

Kept deliberately flat and immutable: a ``SourceRecord`` is one source's *claim*
about one work, never a merged view. Merging happens in ``canonicalize.py``, which
needs to know which source said what — a Crossref publisher string and a PubMed
abstract for the same DOI are two claims, and the provenance (`found_in`) is part
of the output the curator sees.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# Source names, in the order their metadata is trusted when merging. PubMed and
# Europe PMC are human-curated; OpenAlex and Crossref are machine-aggregated and
# are better for coverage than for field accuracy.
SOURCE_PRIORITY: tuple[str, ...] = ("pubmed", "europepmc", "crossref", "openalex", "biorxiv")

_DOI_PREFIXES = (
    "https://doi.org/",
    "http://doi.org/",
    "https://dx.doi.org/",
    "http://dx.doi.org/",
    "doi:",
    "doi.org/",
)
_WHITESPACE = re.compile(r"\s+")
_TITLE_NOISE = re.compile(r"[^a-z0-9 ]+")


def normalise_doi(value: str | None) -> str | None:
    """Lowercase, strip resolver prefixes and trailing punctuation.

    DOIs are case-insensitive by spec, and every source formats them differently
    (OpenAlex returns a full URL, Crossref a bare DOI, PubMed sometimes with a
    trailing period from the XML). Without this, the same paper appears three
    times and the 27% discovery gap looks closed when it is not.
    """
    if not value:
        return None
    cleaned = _WHITESPACE.sub("", str(value)).strip()
    lowered = cleaned.lower()
    for prefix in _DOI_PREFIXES:
        if lowered.startswith(prefix):
            cleaned = cleaned[len(prefix) :]
            lowered = cleaned.lower()
    cleaned = cleaned.strip().rstrip(".,;")
    if not cleaned.lower().startswith("10."):
        return None
    return cleaned.lower()


def normalise_title(value: str | None) -> str | None:
    """A comparison key, not a display string: lowercase alphanumerics only.

    Used only as a last-resort dedupe key for records with neither DOI nor PMID.
    """
    if not value:
        return None
    text = _TITLE_NOISE.sub(" ", str(value).casefold())
    collapsed = _WHITESPACE.sub(" ", text).strip()
    return collapsed or None


def coerce_year(value: object) -> int | None:
    """Accept the several shapes sources use for a year; reject implausible ones."""
    if value is None:
        return None
    match = re.search(r"(1[5-9]\d{2}|20\d{2}|21\d{2})", str(value))
    if not match:
        return None
    return int(match.group(1))


@dataclass(frozen=True)
class SourceQuery:
    """What to look for. Built by ``query_builder`` from a resolved seed.

    `organism_terms` and `product_terms` are separate because their roles differ:
    a candidate must match the organism (it is what the datasheet is about), while
    a product term narrows an already-relevant set. Sources that cannot express
    that distinction get a flattened query and the distinction is re-applied
    locally in ``relevance.py``.
    """

    organism_terms: tuple[str, ...] = ()
    product_terms: tuple[str, ...] = ()
    year_from: int | None = None
    year_to: int | None = None
    max_records_per_source: int = 5000

    @property
    def all_terms(self) -> tuple[str, ...]:
        return tuple(self.organism_terms) + tuple(self.product_terms)

    def require_terms(self) -> None:
        if not self.all_terms:
            raise ValueError("a discovery query needs at least one search term")


@dataclass(frozen=True)
class SourceRecord:
    """One source's claim about one work."""

    source: str
    doi: str | None = None
    pmid: str | None = None
    pmc_id: str | None = None
    title: str | None = None
    abstract: str | None = None
    journal: str | None = None
    publisher: str | None = None
    year: int | None = None
    published_date: str | None = None
    types: tuple[str, ...] = ()
    is_preprint: bool = False
    version_of_record_doi: str | None = None
    preprint_doi: str | None = None
    oa_status: str | None = None
    license: str | None = None
    mesh_terms: tuple[str, ...] = ()
    keywords: tuple[str, ...] = ()
    is_retracted: bool = False
    retraction_note: str | None = None
    url: str | None = None
    extra: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        # Normalising at construction means no downstream code has to remember to.
        object.__setattr__(self, "doi", normalise_doi(self.doi))
        object.__setattr__(self, "version_of_record_doi", normalise_doi(self.version_of_record_doi))
        object.__setattr__(self, "preprint_doi", normalise_doi(self.preprint_doi))
        if self.pmid:
            digits = re.sub(r"\D", "", str(self.pmid))
            object.__setattr__(self, "pmid", digits or None)
        if self.pmc_id:
            pmc = str(self.pmc_id).strip().upper()
            object.__setattr__(self, "pmc_id", pmc if pmc.startswith("PMC") else f"PMC{pmc}")

    @property
    def identity_key(self) -> str | None:
        """The strongest identifier this record carries, or ``None`` if it has none.

        Registrar-assigned identifiers only. A title is deliberately not a fallback:
        matching on one merged distinct works (D13), so a record with no identifier
        stays its own candidate. Kept in step with `canonicalize._identity_keys`.
        """
        if self.doi:
            return f"doi:{self.doi}"
        if self.pmid:
            return f"pmid:{self.pmid}"
        if self.pmc_id:
            return f"pmcid:{self.pmc_id}"
        return None

    @property
    def searchable_text(self) -> str:
        return " ".join(part for part in (self.title, self.abstract) if part)
