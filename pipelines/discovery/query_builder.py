"""Per-source query strings from a resolved seed.

Every source has its own query dialect and its own idea of how strict a match is,
which is the whole reason multi-source discovery recovers papers PubMed misses:

* **PubMed** — field-tagged, exact phrases, real boolean support.
* **Europe PMC** — `TITLE_ABS:"phrase"`, real boolean support, indexes preprints
  (`SRC:PPR`) and so reaches bioRxiv/medRxiv without a bioRxiv search endpoint.
* **Crossref** — no field-restricted phrase search at all. `query.bibliographic`
  is fuzzy and relevance-ranked, so it is issued **one term at a time** and the
  results are filtered locally. This is deliberate: Crossref's value here is
  coverage of the chemical-engineering journals PubMed does not index, and paying
  for that with noise the rule filter removes is the right trade.
* **OpenAlex** — `title_and_abstract.search:"phrase"` is phrase-aware, so terms
  can be OR-ed in one query.
* **bioRxiv** — has no term search; see `sources/biorxiv.py`.

A source that cannot express "organism AND product" gets the flattened term list,
and ``relevance.py`` re-applies the distinction locally. The alternative — dropping
the product terms — silently narrows recall in a way nobody would notice.
"""

from __future__ import annotations

from pipelines.discovery.sources.base import SourceQuery

# Sources that cannot phrase-search one field get one query per term.
PER_TERM_SOURCES = frozenset({"crossref"})


def _quote(term: str) -> str:
    return '"' + term.replace('"', " ").strip() + '"'


def pubmed_query(query: SourceQuery) -> str:
    """Field-tagged with a publication-date range.

    Organism and product groups are AND-ed when both are present, which is what
    makes an organism-plus-product seed narrower rather than merely longer.
    """
    query.require_terms()

    groups: list[str] = []
    for terms in (query.organism_terms, query.product_terms):
        if not terms:
            continue
        clause = " OR ".join(f"{_quote(term)}[Title/Abstract]" for term in terms)
        groups.append(f"({clause})")

    parts = [" AND ".join(groups)]
    if query.year_from or query.year_to:
        start = f"{query.year_from or 1500}/01/01"
        end = f"{query.year_to or 3000}/12/31"
        parts.append(f'("{start}"[Date - Publication] : "{end}"[Date - Publication])')
    return " AND ".join(parts)


def europepmc_query(query: SourceQuery, *, include_preprints: bool = True) -> str:
    """`TITLE_ABS` phrases plus a first-publication-date range.

    Preprints are included by default: Europe PMC indexes them as `SRC:PPR`, and
    they are how a bioRxiv paper is discovered by term at all. Excluding them
    would drop the preprint-only slice of the corpus.
    """
    query.require_terms()

    groups: list[str] = []
    for terms in (query.organism_terms, query.product_terms):
        if not terms:
            continue
        clause = " OR ".join(f"TITLE_ABS:{_quote(term)}" for term in terms)
        groups.append(f"({clause})")

    parts = [" AND ".join(groups)]
    if query.year_from or query.year_to:
        start = f"{query.year_from or 1500}-01-01"
        end = f"{query.year_to or 3000}-12-31"
        parts.append(f"(FIRST_PDATE:[{start} TO {end}])")
    if not include_preprints:
        parts.append("(SRC:MED OR SRC:PMC)")
    return " AND ".join(parts)


def openalex_filter(query: SourceQuery) -> str:
    """A single `filter=` value; phrase-aware, so terms OR into one request.

    OpenAlex ORs alternatives inside one filter with `|`, but AND-ing two
    *groups* needs two filter keys, which the API does not allow for the same key.
    Organism and product terms are therefore OR-ed together here and the
    conjunction is re-applied locally.
    """
    query.require_terms()

    phrases = "|".join(term.replace(",", " ").replace("|", " ") for term in query.all_terms)
    parts = [f"title_and_abstract.search:{phrases}"]
    if query.year_from:
        parts.append(f"from_publication_date:{query.year_from}-01-01")
    if query.year_to:
        parts.append(f"to_publication_date:{query.year_to}-12-31")
    return ",".join(parts)


def crossref_queries(query: SourceQuery) -> list[str]:
    """One fuzzy bibliographic query per term — Crossref cannot OR phrases."""
    query.require_terms()
    return [term for term in query.all_terms]


def crossref_filter(query: SourceQuery) -> str:
    parts: list[str] = []
    if query.year_from:
        parts.append(f"from-pub-date:{query.year_from}-01-01")
    if query.year_to:
        parts.append(f"until-pub-date:{query.year_to}-12-31")
    return ",".join(parts)


def build_all(query: SourceQuery) -> dict[str, object]:
    """Every source's query, for logging into the run manifest.

    Recorded per run so a recall number can always be traced back to the exact
    strings that produced it.
    """
    return {
        "pubmed": pubmed_query(query),
        "europepmc": europepmc_query(query),
        "openalex": openalex_filter(query),
        "crossref": {"queries": crossref_queries(query), "filter": crossref_filter(query)},
    }
