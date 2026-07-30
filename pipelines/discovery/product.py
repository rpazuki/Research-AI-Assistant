"""Bioproduct seed resolution against PubChem, with optional ChEBI enrichment.

The mirror of ``taxonomy.py`` for the other kind of seed. A product query has the
same recall problem as an organism one — papers say `hesperetin`,
`3',5,7-trihydroxy-4'-methoxyflavanone` and `(-)-(S)-hesperetin` for the same
molecule — so the seed carries the synonym set, not just the typed name.

PubChem is the primary source: one CID lookup yields properties, a full synonym
list, and (because PubChem lists cross-references among its synonyms) the ChEBI id
for free. ChEBI/OLS4 is queried only when resolving a single pick, to add an
ontology definition — extra class evidence for borderline compounds, and never on
the typeahead path where it would double the latency per keystroke.

Endpoints (public, no key):
  PUG-REST  /compound/name/{name}/cids/JSON
  PUG-REST  /compound/cid/{cid}/property/.../JSON
  PUG-REST  /compound/cid/{cid}/synonyms/JSON
  autocomplete /compound/{prefix}/json
  OLS4      /api/search?ontology=chebi
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import quote

import httpx

from pipelines.discovery.http import HttpSettings, get_json
from pipelines.discovery.product_classes import ProductClassMatch, classify_terms

PUBCHEM_BASE = "https://pubchem.ncbi.nlm.nih.gov/rest"
OLS4_SEARCH_URL = "https://www.ebi.ac.uk/ols4/api/search"
UPSTREAM_PUBCHEM = "PubChem"
UPSTREAM_CHEBI = "ChEBI"

_PROPERTIES = "MolecularFormula,MolecularWeight,IUPACName,InChIKey,CanonicalSMILES"
_CID_PATTERN = re.compile(r"^\d+$")
_CHEBI_SYNONYM_PATTERN = re.compile(r"^CHEBI:(\d+)$", re.IGNORECASE)
# PubChem synonym lists are long (142 for hesperetin) and mostly registry codes.
# Keep a bounded, useful slice: registry identifiers are filtered out below.
_MAX_SYNONYMS = 40
_REGISTRY_PATTERNS = (
    re.compile(r"^\d{2,7}-\d{2}-\d$"),            # CAS
    re.compile(r"^(cid|sid)\s*\d+$", re.I),
    re.compile(r"^(dtxsid|dtxcid|chembl|chebi|unii|hms|mfcd|nsc|akos|schembl)", re.I),
    re.compile(r"^[a-z]{1,4}[-_ ]?\d{4,}$", re.I),  # generic vendor catalogue codes
    re.compile(r"^[0-9A-Z]{10}$"),                  # UNII-style opaque codes
)


@dataclass(frozen=True)
class ProductSuggestion:
    """One typeahead row. PubChem autocomplete returns names only, hence no CID."""

    name: str
    cid: int | None = None


@dataclass(frozen=True)
class ProductSeed:
    """A resolved compound, with everything discovery and extraction need."""

    cid: int
    preferred_name: str
    synonyms: tuple[str, ...] = ()
    chebi_id: str | None = None
    inchikey: str | None = None
    molecular_formula: str | None = None
    molecular_weight: str | None = None
    iupac_name: str | None = None
    chebi_label: str | None = None
    chebi_definition: str | None = None
    product_class: str | None = None
    product_class_evidence: str | None = None

    @property
    def search_terms(self) -> tuple[str, ...]:
        return product_search_terms(self)


def _looks_like_registry_code(value: str) -> bool:
    return any(pattern.match(value) for pattern in _REGISTRY_PATTERNS)


def _clean_synonyms(raw: list[str], *, preferred_name: str) -> tuple[str, ...]:
    """Drop registry codes and duplicates; keep spelled-out chemical names.

    The chemical-class tokens the classifier needs live in the spelled-out names
    (`...methoxyflavanone`), so filtering registry noise makes classification more
    reliable, not just the payload smaller.
    """
    seen = {preferred_name.casefold()}
    kept: list[str] = []
    for value in raw:
        cleaned = " ".join(value.split())
        if not cleaned or len(cleaned) > 120:
            continue
        key = cleaned.casefold()
        if key in seen or _looks_like_registry_code(cleaned):
            continue
        seen.add(key)
        kept.append(cleaned)
        if len(kept) >= _MAX_SYNONYMS:
            break
    return tuple(kept)


def product_search_terms(seed: ProductSeed) -> tuple[str, ...]:
    """Preferred name first, then the ChEBI label, then synonyms."""
    terms: list[str] = [seed.preferred_name]
    if seed.chebi_label:
        terms.append(seed.chebi_label)
    terms.extend(seed.synonyms)

    seen: set[str] = set()
    unique: list[str] = []
    for term in terms:
        key = term.casefold()
        if not term or key in seen:
            continue
        seen.add(key)
        unique.append(term)
    return tuple(unique)


def search_products(
    query: str,
    *,
    limit: int = 10,
    client: httpx.Client | None = None,
    settings: HttpSettings | None = None,
) -> list[ProductSuggestion]:
    """Typeahead over PubChem compound names."""
    cleaned = query.strip()
    if not cleaned:
        return []

    payload = get_json(
        f"{PUBCHEM_BASE}/autocomplete/compound/{quote(cleaned, safe='')}/json",
        upstream=UPSTREAM_PUBCHEM,
        params={"limit": limit},
        client=client,
        settings=settings,
        allow_404=True,
    )
    terms = ((payload or {}).get("dictionary_terms") or {}).get("compound") or []
    return [ProductSuggestion(name=str(term)) for term in terms[:limit] if str(term).strip()]


def _cids_for_name(
    name: str,
    *,
    client: httpx.Client | None,
    settings: HttpSettings | None,
) -> list[int]:
    payload = get_json(
        # The name is a path segment: a slash or space in a compound name must be
        # percent-encoded, not allowed to open a new segment.
        f"{PUBCHEM_BASE}/pug/compound/name/{quote(name, safe='')}/cids/JSON",
        upstream=UPSTREAM_PUBCHEM,
        params=None,
        client=client,
        settings=settings,
        allow_404=True,  # PubChem answers an unknown name with 404
    )
    cids = ((payload or {}).get("IdentifierList") or {}).get("CID") or []
    return [int(cid) for cid in cids if _CID_PATTERN.match(str(cid))]


def lookup_chebi(
    name: str,
    *,
    client: httpx.Client | None = None,
    settings: HttpSettings | None = None,
) -> tuple[str | None, str | None, str | None]:
    """Return ``(chebi_id, label, definition)`` for the best ChEBI match.

    Enrichment only: a ChEBI outage must not stop a product resolving, so failures
    here degrade to ``(None, None, None)`` rather than propagating.
    """
    cleaned = name.strip()
    if not cleaned:
        return (None, None, None)

    try:
        payload = get_json(
            OLS4_SEARCH_URL,
            upstream=UPSTREAM_CHEBI,
            params={
                "q": cleaned,
                "ontology": "chebi",
                "rows": 1,
                "exact": "true",
                "fieldList": "obo_id,label,description",
            },
            client=client,
            settings=settings,
            allow_404=True,
        )
    except Exception:  # noqa: BLE001 - enrichment must never fail a lookup
        return (None, None, None)

    docs = ((payload or {}).get("response") or {}).get("docs") or []
    if not docs:
        return (None, None, None)

    doc = docs[0]
    description = doc.get("description")
    if isinstance(description, list):
        description = description[0] if description else None
    return (
        (doc.get("obo_id") or None),
        (doc.get("label") or None),
        (re.sub(r"<[^>]+>", "", description) if isinstance(description, str) else None),
    )


def fetch_product(
    cid: int,
    *,
    preferred_name: str | None = None,
    enrich_with_chebi: bool = True,
    client: httpx.Client | None = None,
    settings: HttpSettings | None = None,
) -> ProductSeed | None:
    """Resolve a known CID to a full seed."""
    properties_payload = get_json(
        f"{PUBCHEM_BASE}/pug/compound/cid/{cid}/property/{_PROPERTIES}/JSON",
        upstream=UPSTREAM_PUBCHEM,
        client=client,
        settings=settings,
        allow_404=True,
    )
    records = ((properties_payload or {}).get("PropertyTable") or {}).get("Properties") or []
    if not records:
        return None
    properties = records[0]

    synonyms_payload = get_json(
        f"{PUBCHEM_BASE}/pug/compound/cid/{cid}/synonyms/JSON",
        upstream=UPSTREAM_PUBCHEM,
        client=client,
        settings=settings,
        allow_404=True,
    )
    information = ((synonyms_payload or {}).get("InformationList") or {}).get("Information") or []
    raw_synonyms = [str(value) for value in (information[0].get("Synonym") if information else []) or []]

    # PubChem's first synonym is its preferred name; the caller's typed name wins
    # only if PubChem has nothing.
    resolved_name = (raw_synonyms[0] if raw_synonyms else None) or preferred_name or f"CID {cid}"

    chebi_id: str | None = None
    for value in raw_synonyms:
        match = _CHEBI_SYNONYM_PATTERN.match(value.strip())
        if match:
            chebi_id = f"CHEBI:{match.group(1)}"
            break

    synonyms = _clean_synonyms(raw_synonyms, preferred_name=resolved_name)

    chebi_label: str | None = None
    chebi_definition: str | None = None
    if enrich_with_chebi:
        found_id, chebi_label, chebi_definition = lookup_chebi(
            resolved_name, client=client, settings=settings
        )
        chebi_id = chebi_id or found_id

    iupac_name = properties.get("IUPACName")
    match = classify_terms(
        [
            resolved_name,
            *synonyms,
            iupac_name or "",
            chebi_label or "",
            chebi_definition or "",
        ]
    )

    return ProductSeed(
        cid=cid,
        preferred_name=resolved_name,
        synonyms=synonyms,
        chebi_id=chebi_id,
        inchikey=properties.get("InChIKey"),
        molecular_formula=properties.get("MolecularFormula"),
        molecular_weight=(
            str(properties["MolecularWeight"]) if properties.get("MolecularWeight") is not None else None
        ),
        iupac_name=iupac_name,
        chebi_label=chebi_label,
        chebi_definition=chebi_definition,
        product_class=match.product_class if match else None,
        product_class_evidence=match.matched_token if match else None,
    )


def resolve_product(
    query: str,
    *,
    enrich_with_chebi: bool = True,
    client: httpx.Client | None = None,
    settings: HttpSettings | None = None,
) -> ProductSeed | None:
    """Resolve a name, synonym or CID to a full seed."""
    cleaned = query.strip()
    if not cleaned:
        return None

    if _CID_PATTERN.match(cleaned):
        return fetch_product(
            int(cleaned),
            enrich_with_chebi=enrich_with_chebi,
            client=client,
            settings=settings,
        )

    cids = _cids_for_name(cleaned, client=client, settings=settings)
    if not cids:
        return None

    return fetch_product(
        cids[0],
        preferred_name=cleaned,
        enrich_with_chebi=enrich_with_chebi,
        client=client,
        settings=settings,
    )


def classify_product_terms(terms: list[str] | tuple[str, ...]) -> ProductClassMatch | None:
    """Re-exported so callers classify a curator-typed product without a lookup."""
    return classify_terms(terms)
