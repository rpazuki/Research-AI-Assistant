"""Measure discovery recall against the curated Yarrowia set.

This is the S2 acceptance instrument. The curated Excel is 723 rows over **706
unique DOIs**, of which **199 are absent from PubMed** — the 28% discovery hole
that multi-source search exists to close. This script runs discovery for a seed
and reports how much of that set it recovers, and from which source.

It is a script, not a test: one run costs a few hundred upstream requests and
several minutes. Run it deliberately, and record the numbers.

    python -m pipelines.discovery.measure_recall \\
        --gold "/path/to/output/record_report.csv" \\
        --organism "Yarrowia lipolytica" --year-from 2016 --year-to 2026

The gold CSV is the analysis project's `record_report.csv` (columns `doi`,
`in_pubmed`). Recall is reported three ways, because one number hides the finding:

* **overall** — of all 706 gold DOIs, how many did discovery surface;
* **PubMed-missing** — of the 199 PubMed cannot see, how many did the other
  sources reach. This is the number the 27% claim rests on;
* **per source** — which source uniquely contributed each recovered DOI, so the
  cost of dropping a source is visible rather than assumed.
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from pipelines.discovery.discover import (
    ALL_SOURCES,
    DiscoveryCredentials,
    discover,
    included_candidates,
)
from pipelines.discovery.manifest_csv import write_manifest_csv
from pipelines.discovery.sources.base import SourceQuery, normalise_doi
from pipelines.discovery.taxonomy import resolve_organism

logger = logging.getLogger("measure_recall")


@dataclass
class GoldSet:
    dois: set[str]
    pubmed_missing: set[str]
    duplicate_rows: int
    rows: int

    @property
    def in_pubmed(self) -> set[str]:
        return self.dois - self.pubmed_missing


def load_gold(path: Path) -> GoldSet:
    """Read the curated record report. Tolerates the BOM the Excel export leaves."""
    with path.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))

    seen: Counter[str] = Counter()
    in_pubmed: set[str] = set()
    for row in rows:
        doi = normalise_doi(row.get("doi"))
        if not doi:
            continue
        seen[doi] += 1
        if str(row.get("in_pubmed") or "").strip() in {"1", "true", "True"}:
            in_pubmed.add(doi)

    dois = set(seen)
    return GoldSet(
        dois=dois,
        pubmed_missing=dois - in_pubmed,
        duplicate_rows=sum(count - 1 for count in seen.values() if count > 1),
        rows=len(rows),
    )


def measure(
    *,
    gold: GoldSet,
    organism: str,
    product: str | None,
    year_from: int,
    year_to: int,
    sources: tuple[str, ...],
    max_records_per_source: int,
    credentials: DiscoveryCredentials,
    include_mentions: bool,
) -> dict:
    seed = resolve_organism(
        organism, email=credentials.ncbi_email, api_key=credentials.ncbi_api_key
    )
    if seed is None:
        raise SystemExit(f"could not resolve organism {organism!r}")

    logger.info("seed: taxid %s, terms %s", seed.taxid, list(seed.search_terms))

    query = SourceQuery(
        organism_terms=seed.search_terms,
        product_terms=(product,) if product else (),
        year_from=year_from,
        year_to=year_to,
        max_records_per_source=max_records_per_source,
    )

    result = discover(
        query,
        sources=sources,
        credentials=credentials,
        progress=lambda message, payload: logger.info("%s %s", message, payload or ""),
    )

    all_found = {candidate.doi for candidate in result.candidates if candidate.doi}
    included = included_candidates(result, include_mentions=include_mentions)
    included_dois = {candidate.doi for candidate in included if candidate.doi}

    # Per-source attribution uses `found_in`, so "only Crossref had it" is a
    # measured statement rather than an assumption about coverage.
    per_source_unique: Counter[str] = Counter()
    for candidate in result.candidates:
        if candidate.doi in gold.dois and len(candidate.found_in) == 1:
            per_source_unique[candidate.found_in[0]] += 1

    def recall(subset: set[str], found: set[str]) -> dict:
        hit = subset & found
        return {
            "gold": len(subset),
            "found": len(hit),
            "recall_pct": round(100 * len(hit) / len(subset), 1) if subset else None,
            "missing": len(subset - found),
        }

    return {
        "seed": {
            "organism": seed.scientific_name,
            "taxid": seed.taxid,
            "search_terms": list(seed.search_terms),
            "product": product,
            "years": [year_from, year_to],
        },
        "gold": {
            "rows": gold.rows,
            "unique_dois": len(gold.dois),
            "duplicate_rows_collapsed_by_gold_itself": gold.duplicate_rows,
            "pubmed_missing": len(gold.pubmed_missing),
        },
        "discovery": result.summary(),
        "recall_all_candidates": {
            "overall": recall(gold.dois, all_found),
            "pubmed_missing": recall(gold.pubmed_missing, all_found),
            "in_pubmed": recall(gold.in_pubmed, all_found),
        },
        "recall_after_filters": {
            "overall": recall(gold.dois, included_dois),
            "pubmed_missing": recall(gold.pubmed_missing, included_dois),
        },
        "gold_dois_uniquely_from_one_source": dict(per_source_unique),
        "candidate_totals": {
            "all": len(result.candidates),
            "included": len(included),
            "at_least_gold_size": len(all_found) >= len(gold.dois),
        },
        "_candidates": result.candidates,
        "_included_dois": included_dois,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gold", required=True, type=Path, help="record_report.csv")
    parser.add_argument("--organism", default="Yarrowia lipolytica")
    parser.add_argument("--product", default=None)
    parser.add_argument("--year-from", type=int, default=2016)
    parser.add_argument("--year-to", type=int, default=2026)
    parser.add_argument("--sources", default=",".join(ALL_SOURCES))
    parser.add_argument("--max-per-source", type=int, default=6000)
    parser.add_argument("--include-mentions", action="store_true")
    parser.add_argument("--ncbi-email", default=None)
    parser.add_argument("--ncbi-api-key", default=None)
    parser.add_argument("--mailto", default=None, help="Crossref/OpenAlex polite-pool contact")
    parser.add_argument("--out", type=Path, default=None, help="write the report JSON here")
    parser.add_argument("--manifest", type=Path, default=None, help="write the manifest CSV here")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    report = measure(
        gold=load_gold(args.gold),
        organism=args.organism,
        product=args.product,
        year_from=args.year_from,
        year_to=args.year_to,
        sources=tuple(name.strip() for name in args.sources.split(",") if name.strip()),
        max_records_per_source=args.max_per_source,
        credentials=DiscoveryCredentials(
            ncbi_email=args.ncbi_email,
            ncbi_api_key=args.ncbi_api_key,
            crossref_mailto=args.mailto,
            openalex_mailto=args.mailto,
        ),
        include_mentions=args.include_mentions,
    )

    candidates = report.pop("_candidates")
    included_dois = report.pop("_included_dois")

    if args.manifest:
        args.manifest.write_text(
            write_manifest_csv(candidates, included_dois=included_dois), encoding="utf-8"
        )
        logger.info("manifest written to %s", args.manifest)

    text = json.dumps(report, indent=2)
    if args.out:
        args.out.write_text(text, encoding="utf-8")
        logger.info("report written to %s", args.out)
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
