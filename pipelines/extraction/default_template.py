"""
pipelines/extraction/default_template.py
----------------------------------------
The default datasheet template: the 17 columns of
`docs/Yarrowia lipolytica Datasheet(2016-2026).xlsx`, in their original order.

Everything here is transcribed from the curated spreadsheet, not invented:

    - `label` values are the exact Excel headers, so an exported CSV drops into the
      curators' existing workflow unchanged.
    - `STANDARD_PRODUCT_CLASSES` is the full observed vocabulary of the
      `Standard Product Class` column — 17 distinct values across 723 rows, i.e.
      genuinely controlled. `Family of Compounds`, by contrast, has 581 distinct
      values over the same rows and is therefore left free text.
    - `source_hint` follows the measured tiers in `docs/investigation_summary.md` §3:
      columns whose abstract-only coverage is ~10% and full-text coverage ~90% are
      marked 'fulltext'.
"""

from __future__ import annotations

from typing import Any

DEFAULT_TEMPLATE_NAME = "rlalab-datasheet-v1"
DEFAULT_TEMPLATE_DESCRIPTION = (
    "The 17 curated columns of the RLA Lab Yarrowia lipolytica datasheet "
    "(2016-2026), in their original spreadsheet order."
)

# Observed vocabulary of the 'Standard Product Class' column, most frequent first.
STANDARD_PRODUCT_CLASSES: list[str] = [
    "Lipids & Fatty Acids",
    "Terpenoids & Sterols",
    "Organic Acids",
    "Enzymes & Recombinant Proteins",
    "Carotenoids & Apocarotenoids",
    "Sugar Alcohols (Polyols)",
    "Phenolic & Aromatic / Flavor Compounds",
    "Flavonoids & Polyphenols",
    "Biomass, Biofuels & Hydrocarbons",
    "Amino Acids & Derivatives",
    "Sugars & Oligosaccharides",
    "Polyketides",
    "Biopolymers & Biosurfactants",
    "Process / Strain Engineering (Non-compound)",
    "Pigments (Non-carotenoid)",
    "Nucleosides & Secondary Metabolites",
    "Vitamins & Cofactors",
]

# order_index, key, label, kind, source_hint, extraction_hint
DEFAULT_COLUMNS: list[dict[str, Any]] = [
    {
        "order_index": 0,
        "key": "date",
        "label": "Date",
        "kind": "bibliographic",
        "source_hint": "metadata",
        "extraction_hint": "Publication date of this article, as YYYY-MM-DD when the day is known.",
    },
    {
        "order_index": 1,
        "key": "family_of_compounds",
        "label": "Family of Compounds",
        "kind": "free_text",
        "source_hint": "any",
        "extraction_hint": (
            "Chemical family of the target product(s), in the authors' own terms "
            "(e.g. 'Flavonoids', 'Sugar alcohols / polyols', 'Microbial lipids / fatty acids')."
        ),
    },
    {
        "order_index": 2,
        "key": "standard_product_class",
        "label": "Standard Product Class",
        "kind": "controlled",
        "source_hint": "any",
        "extraction_hint": (
            "Assign exactly one class from the controlled list. Use "
            "'Process / Strain Engineering (Non-compound)' when the paper reports no product."
        ),
        "vocabulary": STANDARD_PRODUCT_CLASSES,
    },
    {
        "order_index": 3,
        "key": "compounds",
        "label": "Compounds",
        "kind": "free_text",
        "source_hint": "any",
        "extraction_hint": (
            "Specific target compound(s) produced or measured, semicolon-separated. "
            "Keep the authors' nomenclature including stereochemistry, e.g. '(2S)-Hesperetin'."
        ),
    },
    {
        "order_index": 4,
        "key": "concentration_yield",
        "label": "Concentration/Yield",
        "kind": "numeric",
        "source_hint": "fulltext",
        "extraction_hint": (
            "Reported titre, yield or productivity with its units exactly as written, "
            "including any per-substrate or per-biomass basis, e.g. "
            "'488.7 mg/L (13.4 mg/g WCO)'. Report the best result of THIS paper; never "
            "a figure the paper attributes to earlier work."
        ),
    },
    {
        "order_index": 5,
        "key": "extra_conditions",
        "label": "Extra conditions or comparison for this concentration/Yield",
        "kind": "free_text",
        "source_hint": "fulltext",
        "extraction_hint": (
            "The conditions the reported value was obtained under, and any comparison "
            "the authors draw (control strain, alternative substrate, scale)."
        ),
    },
    {
        "order_index": 6,
        "key": "article",
        "label": "Article",
        "kind": "bibliographic",
        "source_hint": "metadata",
        "extraction_hint": "Full article title.",
    },
    {
        "order_index": 7,
        "key": "authors",
        "label": "Authors",
        "kind": "bibliographic",
        "source_hint": "metadata",
        "extraction_hint": "All authors in order, semicolon-separated, as 'FirstName LastName'.",
    },
    {
        "order_index": 8,
        "key": "corresponding_authors",
        "label": "Corresponding Authors",
        "kind": "bibliographic",
        "source_hint": "any",
        "extraction_hint": "Corresponding author(s) only, semicolon-separated.",
    },
    {
        "order_index": 9,
        "key": "acknowledgement",
        "label": "Acknowledgement",
        "kind": "bibliographic",
        "source_hint": "fulltext",
        "extraction_hint": (
            "Funding bodies and grant numbers from the acknowledgements or funding statement."
        ),
    },
    {
        "order_index": 10,
        "key": "strain_used",
        "label": "strain used/RLA collection strain",
        "kind": "free_text",
        "source_hint": "fulltext",
        "extraction_hint": (
            "Host strain(s) and the final engineered strain designation, semicolon-separated. "
            "Copy the nomenclature character-for-character, including Greek letters and "
            "deletion deltas: 'Yarrowia lipolytica Po1g-Δku70; final production strain Y29'. "
            "Never transliterate Δ to 'D' or 'delta'."
        ),
    },
    {
        "order_index": 11,
        "key": "genetic_engineering_strategy",
        "label": "genetic engineering strategy used",
        "kind": "free_text",
        "source_hint": "fulltext",
        "extraction_hint": (
            "Genes overexpressed, knocked out or integrated, promoters, and pathway "
            "construction steps. State 'Wild type, no genetic engineering' when none was done."
        ),
    },
    {
        "order_index": 12,
        "key": "carbon_source",
        "label": "carbon source",
        "kind": "free_text",
        "source_hint": "fulltext",
        "extraction_hint": (
            "Carbon substrate(s) fed, with concentrations and medium composition where given. "
            "This is normally stated in Methods as part of the medium recipe rather than "
            "labelled 'carbon source'."
        ),
    },
    {
        "order_index": 13,
        "key": "cultivation_mode",
        "label": "cultivation mode",
        "kind": "free_text",
        "source_hint": "fulltext",
        "extraction_hint": (
            "Cultivation format and scale: shake flask, batch, fed-batch, continuous, "
            "bioreactor working volume, temperature, agitation, duration."
        ),
    },
    {
        "order_index": 14,
        "key": "comments",
        "label": "Comments",
        "kind": "free_text",
        "source_hint": "fulltext",
        "extraction_hint": (
            "Key quantitative findings and caveats beyond the headline value, in a few sentences."
        ),
    },
    {
        "order_index": 15,
        "key": "application",
        "label": "Application",
        "kind": "free_text",
        "source_hint": "any",
        "extraction_hint": (
            "Intended application or significance the authors claim "
            "(e.g. 'Bioenergy; waste valorization; circular bioeconomy')."
        ),
    },
    {
        "order_index": 16,
        "key": "link",
        "label": "Link",
        "kind": "bibliographic",
        "source_hint": "metadata",
        "extraction_hint": "Resolvable DOI URL, as https://doi.org/<doi>.",
    },
]

# Appended after the curated columns on export (§4.1 provenance block). Held here so
# the export header and the run detail table agree on one ordering.
PROVENANCE_COLUMNS: list[dict[str, str]] = [
    {"key": "doi", "label": "doi"},
    {"key": "pmid", "label": "pmid"},
    {"key": "journal", "label": "journal"},
    {"key": "publisher", "label": "publisher"},
    {"key": "year", "label": "year"},
    {"key": "oa_status", "label": "oa_status"},
    {"key": "doc_type", "label": "doc_type"},
    {"key": "is_review", "label": "is_review"},
    {"key": "is_retracted", "label": "is_retracted"},
    {"key": "source_tier", "label": "source_tier"},
    {"key": "acquisition_route", "label": "acquisition_route"},
    {"key": "acquisition_status", "label": "acquisition_status"},
]


def default_column_rows() -> list[dict[str, Any]]:
    """Deep-ish copy of DEFAULT_COLUMNS safe for callers to mutate."""
    return [
        {**column, "vocabulary": list(column.get("vocabulary") or [])}
        for column in DEFAULT_COLUMNS
    ]
