"""S4: measure what a paper costs and what extraction loses, before round 2 buys it.

Round 2's cost estimate (§7.1) is an estimate. This script replaces it with a
measurement over ~20 real papers, and answers the one question that is awkward to
change later: **which acquisition route should the assisted queue ask humans for?**

Recoverability is not the concern — `assets/` keeps the original bytes, so a bad
parse is fixable by re-parsing. Route *preference* is: once a person has downloaded
a PDF, asking them to go back for the publisher's XML is a second request of their
time, and there may be hundreds of them.

Three things are measured per document:

* **Character fidelity.** Does `Po1g-Δku70` survive? A route that renders Δ as `D`
  produces a different strain name and nothing downstream can tell.
* **Section structure.** Extraction is restricted to Methods and Results; a route
  that yields no section headings cannot support that restriction, and sending the
  whole paper instead both costs more and attributes other groups' numbers to
  these authors.
* **Token count.** Measured with the provider's own tokeniser when a key is
  available, so the round-2 projection is arithmetic rather than a guess.

Writes `reports/extraction_spike.json` under the run cache. Costs a few cents at
most: token counting is free, and only the escalation check calls the model.

    python -m pipelines.acquisition.extraction_spike \\
        --cache data/corpora/datasheets/<run> --limit 20
"""

from __future__ import annotations

import argparse
import json
import logging
import statistics
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

from pipelines.acquisition import extract_text

logger = logging.getLogger("extraction_spike")

# §7.1's assumption, restated here so the measurement can contradict it.
ESTIMATED_TOKENS_PER_PAPER = 24_000
# Rough character-per-token ratio for English scientific prose, used only when no
# provider tokeniser is available. Flagged in the output as an estimate.
CHARS_PER_TOKEN_FALLBACK = 3.8

SELECTED_SECTIONS = (
    extract_text.SECTION_TITLE,
    extract_text.SECTION_ABSTRACT,
    extract_text.SECTION_METHODS,
    extract_text.SECTION_RESULTS,
    extract_text.SECTION_SUPPLEMENTARY,
)


@dataclass
class DocumentMeasurement:
    identifier: str
    source_format: str
    bytes_on_disk: int
    total_chars: int
    selected_chars: int
    section_labels: list[str]
    has_methods: bool
    has_results: bool
    tokens_total: int | None
    tokens_selected: int | None
    token_method: str
    delta_count: int
    mu_count: int
    critical_characters: int
    replacement_characters: int
    suspicious_strain_names: list[str]
    looks_corrupted: bool
    warnings: list[str] = field(default_factory=list)


def _count_tokens(text: str, counter) -> tuple[int | None, str]:
    if not text:
        return (0, "empty")
    if counter is not None:
        try:
            return (counter(text), "provider")
        except Exception as exc:  # noqa: BLE001 - fall back rather than fail the spike
            logger.warning("token counting failed, falling back to an estimate: %s", exc)
    return (int(len(text) / CHARS_PER_TOKEN_FALLBACK), "estimated_from_chars")


def measure_document(path: Path, *, counter=None) -> DocumentMeasurement:
    """Extract one cached asset and measure it."""
    content = path.read_bytes()
    content_format = "xml" if path.suffix == ".xml" else "pdf"
    document = extract_text.extract(content, content_format)

    full = document.full_text
    selected = "\n\n".join(
        part
        for part in (document.title or "", document.section_text(*SELECTED_SECTIONS))
        if part
    )
    fidelity = extract_text.character_fidelity(document.all_text)
    tokens_total, method = _count_tokens(full, counter)
    tokens_selected, _ = _count_tokens(selected, counter)

    return DocumentMeasurement(
        identifier=path.stem,
        source_format=content_format,
        bytes_on_disk=len(content),
        total_chars=len(full),
        selected_chars=len(selected),
        section_labels=document.labels(),
        has_methods=extract_text.SECTION_METHODS in document.labels(),
        has_results=extract_text.SECTION_RESULTS in document.labels(),
        tokens_total=tokens_total,
        tokens_selected=tokens_selected,
        token_method=method,
        delta_count=fidelity.delta_count,
        mu_count=fidelity.mu_count,
        critical_characters=fidelity.critical_characters,
        replacement_characters=fidelity.replacement_characters,
        suspicious_strain_names=fidelity.suspicious_strain_names,
        looks_corrupted=fidelity.looks_corrupted,
        warnings=document.warnings,
    )


def _summarise(rows: list[DocumentMeasurement], key) -> dict:
    values = [key(row) for row in rows if key(row) is not None]
    if not values:
        return {"n": 0}
    return {
        "n": len(values),
        "min": min(values),
        "median": int(statistics.median(values)),
        "mean": int(statistics.mean(values)),
        "max": max(values),
    }


def build_report(measurements: list[DocumentMeasurement]) -> dict:
    """Turn per-document numbers into the two decisions this spike exists to inform."""
    by_format: dict[str, list[DocumentMeasurement]] = {}
    for row in measurements:
        by_format.setdefault(row.source_format, []).append(row)

    format_findings = {}
    for source_format, rows in by_format.items():
        with_critical = [row for row in rows if row.critical_characters > 0]
        format_findings[source_format] = {
            "documents": len(rows),
            "with_methods_section": sum(1 for row in rows if row.has_methods),
            "with_results_section": sum(1 for row in rows if row.has_results),
            "section_structure_rate": round(
                sum(1 for row in rows if row.has_methods and row.has_results) / len(rows), 2
            ),
            "documents_with_greek": len(with_critical),
            "documents_flagged_corrupted": sum(1 for row in rows if row.looks_corrupted),
            "delta_characters_total": sum(row.delta_count for row in rows),
            "suspicious_strain_names": sorted(
                {name for row in rows for name in row.suspicious_strain_names}
            ),
            "tokens_selected": _summarise(rows, lambda row: row.tokens_selected),
            "tokens_total": _summarise(rows, lambda row: row.tokens_total),
        }

    selected = _summarise(measurements, lambda row: row.tokens_selected)
    xml = format_findings.get("xml")
    pdf = format_findings.get("pdf")

    # The route-preference decision, stated from the numbers rather than asserted.
    if xml and pdf:
        recommendation = (
            "prefer XML"
            if (
                xml["section_structure_rate"] >= pdf["section_structure_rate"]
                and xml["documents_flagged_corrupted"] <= pdf["documents_flagged_corrupted"]
            )
            else "inconclusive — inspect the per-document rows"
        )
    elif xml and not pdf:
        recommendation = "only XML measured; ask for XML where a route offers it"
    elif pdf and not xml:
        recommendation = "only PDF measured; no XML comparison available"
    else:
        recommendation = "no documents measured"

    return {
        "documents_measured": len(measurements),
        "by_format": format_findings,
        "tokens_per_paper_selected_sections": selected,
        "plan_estimate_tokens_per_paper": ESTIMATED_TOKENS_PER_PAPER,
        "measured_vs_estimate": (
            round(selected.get("median", 0) / ESTIMATED_TOKENS_PER_PAPER, 2)
            if selected.get("median")
            else None
        ),
        "route_preference": recommendation,
        "documents": [asdict(row) for row in measurements],
    }


def collect_assets(cache_root: Path, limit: int) -> list[Path]:
    assets = sorted(
        [path for path in (cache_root / "assets").glob("*") if path.suffix in {".xml", ".pdf"}]
    )
    # Interleave formats so a 20-document sample is not all XML by accident of
    # alphabetical order — the comparison is the point.
    xml = [path for path in assets if path.suffix == ".xml"]
    pdf = [path for path in assets if path.suffix == ".pdf"]
    mixed: list[Path] = []
    while (xml or pdf) and len(mixed) < limit:
        if xml:
            mixed.append(xml.pop(0))
        if pdf and len(mixed) < limit:
            mixed.append(pdf.pop(0))
    return mixed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache", required=True, type=Path, help="run cache root")
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument(
        "--no-provider-tokens",
        action="store_true",
        help="skip the provider tokeniser and estimate from characters",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    counter = None
    if not args.no_provider_tokens:
        counter = _load_provider_counter()

    assets = collect_assets(args.cache, args.limit)
    if not assets:
        logger.error("no assets under %s/assets — run acquisition first", args.cache)
        return 1

    logger.info("measuring %d documents", len(assets))
    measurements = [measure_document(path, counter=counter) for path in assets]
    report = build_report(measurements)

    output = args.cache / "reports" / "extraction_spike.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    logger.info("report written to %s", output)

    summary = {key: value for key, value in report.items() if key != "documents"}
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0


def _load_provider_counter():
    """The provider's own tokeniser, so the round-2 projection is arithmetic.

    Optional: without a key the spike still runs and says its token numbers are
    estimated, which is honest and still useful for the route decision.
    """
    try:
        import os

        import anthropic
    except ImportError:
        logger.info("anthropic SDK unavailable; estimating tokens from characters")
        return None

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        logger.info("ANTHROPIC_API_KEY not set; estimating tokens from characters")
        return None

    client = anthropic.Anthropic(api_key=api_key)
    model = os.environ.get("LLM_MODEL", "claude-sonnet-4-6")

    def count(text: str) -> int:
        response = client.messages.count_tokens(
            model=model, messages=[{"role": "user", "content": text}]
        )
        return int(response.input_tokens)

    return count


if __name__ == "__main__":
    sys.exit(main())
