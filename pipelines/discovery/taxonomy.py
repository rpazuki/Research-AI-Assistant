"""Organism seed resolution against NCBI Taxonomy.

A datasheet run starts from an organism. What discovery actually needs is not the
name the user typed but the *set* of names the literature uses for that organism:
searching PubMed for `Yarrowia lipolytica` alone misses every paper published
under `Candida lipolytica`, which is a large slice of the pre-1990 and
food-microbiology literature.

NCBI Taxonomy is the authority for that set. taxid 4952 carries three synonyms
(`Candida`, `Endomycopsis`, `Mycotorula lipolytica`), and this module returns
them alongside the accepted name.

Note what NCBI does *not* have: `Saccharomycopsis lipolytica` appears in the
literature but resolves to no taxid, so it cannot be discovered here. That is why
``organism_search_terms`` accepts ``extra_synonyms`` — a curator can add a
literature name without editing code, and the provenance stays visible (NCBI
synonyms versus locally added ones are separate inputs).

Endpoints used (all public, no key required; a key raises the rate limit):
  esearch  db=taxonomy   name/synonym → taxid
  esummary db=taxonomy   taxid → scientific name, rank, common name
  efetch   db=taxonomy   taxid → full name block (XML; there is no JSON form)
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field

import httpx

from pipelines.discovery.http import DiscoveryLookupError, HttpSettings, get, get_json

EUTILS_BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
UPSTREAM = "NCBI Taxonomy"

# Name classes in the efetch `OtherNames` block that are usable as search terms.
# `authority` (the full citation), `type material` (strain deposit codes) and
# `misspelling` are deliberately excluded: they add noise to a literature query
# without adding recall.
_USABLE_NAME_TAGS = (
    "Synonym",
    "GenbankSynonym",
    "EquivalentName",
    "Anamorph",
    "Teleomorph",
    "Includes",
)
_COMMON_NAME_TAGS = ("CommonName", "GenbankCommonName")

_TAXID_PATTERN = re.compile(r"^\d+$")


@dataclass(frozen=True)
class OrganismSuggestion:
    """One typeahead row. Cheap: esearch + esummary, no efetch."""

    taxid: int
    scientific_name: str
    rank: str | None = None
    common_name: str | None = None


@dataclass(frozen=True)
class OrganismSeed:
    """A resolved organism, with everything discovery needs to build queries."""

    taxid: int
    scientific_name: str
    rank: str | None = None
    synonyms: tuple[str, ...] = ()
    common_names: tuple[str, ...] = ()
    lineage: tuple[str, ...] = ()
    extra_synonyms: tuple[str, ...] = field(default=())

    @property
    def search_terms(self) -> tuple[str, ...]:
        return organism_search_terms(self, extra_synonyms=self.extra_synonyms)


def _dedupe_preserving_order(values: list[str]) -> tuple[str, ...]:
    """Case-insensitive dedupe that keeps the first spelling seen."""
    seen: set[str] = set()
    unique: list[str] = []
    for value in values:
        cleaned = " ".join(value.split())
        if not cleaned:
            continue
        key = cleaned.casefold()
        if key in seen:
            continue
        seen.add(key)
        unique.append(cleaned)
    return tuple(unique)


def organism_search_terms(
    seed: OrganismSeed, *, extra_synonyms: tuple[str, ...] | list[str] = ()
) -> tuple[str, ...]:
    """Accepted name first, then NCBI synonyms, then curator-supplied names.

    Order matters downstream: the first term is what a run is labelled with, and
    per-source query builders quote these verbatim.
    """
    return _dedupe_preserving_order(
        [seed.scientific_name, *seed.synonyms, *extra_synonyms, *seed.common_names]
    )


def _esearch_taxids(
    term: str,
    *,
    limit: int,
    client: httpx.Client | None,
    settings: HttpSettings | None,
    email: str | None,
    api_key: str | None,
) -> list[int]:
    payload = get_json(
        f"{EUTILS_BASE}/esearch.fcgi",
        upstream=UPSTREAM,
        params={
            "db": "taxonomy",
            "term": term,
            "retmode": "json",
            "retmax": limit,
            "email": email,
            "api_key": api_key,
        },
        client=client,
        settings=settings,
    )
    result = (payload or {}).get("esearchresult") or {}
    return [int(value) for value in result.get("idlist", []) if _TAXID_PATTERN.match(str(value))]


def search_organisms(
    query: str,
    *,
    limit: int = 10,
    client: httpx.Client | None = None,
    settings: HttpSettings | None = None,
    email: str | None = None,
    api_key: str | None = None,
) -> list[OrganismSuggestion]:
    """Typeahead over NCBI Taxonomy names, synonyms included.

    NCBI matches whole names, so a partial query returns nothing on its own: the
    trailing `*` is what makes `Yarrowia lipo` resolve to 4952. A query that
    already carries a wildcard is passed through untouched.
    """
    cleaned = query.strip()
    if not cleaned:
        return []

    term = cleaned if "*" in cleaned else f"{cleaned}*"
    taxids = _esearch_taxids(
        term,
        limit=limit,
        client=client,
        settings=settings,
        email=email,
        api_key=api_key,
    )
    if not taxids:
        return []

    payload = get_json(
        f"{EUTILS_BASE}/esummary.fcgi",
        upstream=UPSTREAM,
        params={
            "db": "taxonomy",
            "id": ",".join(str(taxid) for taxid in taxids),
            "retmode": "json",
            "email": email,
            "api_key": api_key,
        },
        client=client,
        settings=settings,
    )
    result = (payload or {}).get("result") or {}

    suggestions: list[OrganismSuggestion] = []
    for taxid in taxids:  # esummary key order is not guaranteed; keep esearch ranking
        record = result.get(str(taxid))
        if not isinstance(record, dict):
            continue
        name = (record.get("scientificname") or "").strip()
        if not name:
            continue
        suggestions.append(
            OrganismSuggestion(
                taxid=taxid,
                scientific_name=name,
                rank=(record.get("rank") or "").strip() or None,
                common_name=(record.get("commonname") or "").strip() or None,
            )
        )
    return suggestions


def parse_taxon_xml(xml_text: str, *, extra_synonyms: tuple[str, ...] | list[str] = ()) -> OrganismSeed | None:
    """Parse one efetch `TaxaSet` payload into a seed.

    Returns ``None`` for an empty set — NCBI answers a bad taxid with a valid
    document rather than an error status.
    """
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        raise DiscoveryLookupError(UPSTREAM, f"efetch returned unparseable XML: {exc}") from exc

    taxon = root.find("Taxon")
    if taxon is None:
        return None

    raw_taxid = (taxon.findtext("TaxId") or "").strip()
    scientific_name = (taxon.findtext("ScientificName") or "").strip()
    if not _TAXID_PATTERN.match(raw_taxid) or not scientific_name:
        return None

    other_names = taxon.find("OtherNames")
    synonyms: list[str] = []
    common_names: list[str] = []
    if other_names is not None:
        for tag in _USABLE_NAME_TAGS:
            synonyms.extend((element.text or "").strip() for element in other_names.findall(tag))
        for tag in _COMMON_NAME_TAGS:
            common_names.extend((element.text or "").strip() for element in other_names.findall(tag))

    lineage = tuple(
        part.strip()
        for part in (taxon.findtext("Lineage") or "").split(";")
        if part.strip()
    )

    return OrganismSeed(
        taxid=int(raw_taxid),
        scientific_name=scientific_name,
        rank=(taxon.findtext("Rank") or "").strip() or None,
        synonyms=_dedupe_preserving_order([name for name in synonyms if name != scientific_name]),
        common_names=_dedupe_preserving_order(common_names),
        lineage=lineage,
        extra_synonyms=_dedupe_preserving_order(list(extra_synonyms)),
    )


def fetch_organism(
    taxid: int,
    *,
    extra_synonyms: tuple[str, ...] | list[str] = (),
    client: httpx.Client | None = None,
    settings: HttpSettings | None = None,
    email: str | None = None,
    api_key: str | None = None,
) -> OrganismSeed | None:
    """Resolve a known taxid to a full seed."""
    response = get(
        f"{EUTILS_BASE}/efetch.fcgi",
        upstream=UPSTREAM,
        params={
            "db": "taxonomy",
            "id": taxid,
            "retmode": "xml",
            "email": email,
            "api_key": api_key,
        },
        client=client,
        settings=settings,
    )
    if response is None:
        return None
    return parse_taxon_xml(response.text, extra_synonyms=extra_synonyms)


def resolve_organism(
    query: str,
    *,
    extra_synonyms: tuple[str, ...] | list[str] = (),
    client: httpx.Client | None = None,
    settings: HttpSettings | None = None,
    email: str | None = None,
    api_key: str | None = None,
) -> OrganismSeed | None:
    """Resolve a name, synonym or taxid to a full seed.

    A synonym resolves to its accepted taxon, so `candida lipolytica` and
    `Yarrowia lipolytica` produce the same seed — which is the point: a run keyed
    on the taxid cannot be split in two by which name the user happened to type.
    """
    cleaned = query.strip()
    if not cleaned:
        return None

    if _TAXID_PATTERN.match(cleaned):
        return fetch_organism(
            int(cleaned),
            extra_synonyms=extra_synonyms,
            client=client,
            settings=settings,
            email=email,
            api_key=api_key,
        )

    taxids = _esearch_taxids(
        cleaned,
        limit=1,
        client=client,
        settings=settings,
        email=email,
        api_key=api_key,
    )
    if not taxids:
        # Exact name unknown; fall back to the typeahead form before giving up.
        taxids = _esearch_taxids(
            f"{cleaned}*" if "*" not in cleaned else cleaned,
            limit=1,
            client=client,
            settings=settings,
            email=email,
            api_key=api_key,
        )
    if not taxids:
        return None

    return fetch_organism(
        taxids[0],
        extra_synonyms=extra_synonyms,
        client=client,
        settings=settings,
        email=email,
        api_key=api_key,
    )
