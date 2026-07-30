# Yarrowia lipolytica datasheet — PubMed / bioRxiv availability report

*Generated 2026-07-14T13:06:45 · 723 records (713 unique papers) · run time 8.6s*

## 1. Are the papers online?

| | records | % of datasheet |
|---|---:|---:|
| **In PubMed** | 515 | 71.2% |
| ” with an abstract in PubMed | 515 | — |
| ” with a PMC record | 241 | — |
| **PubMed full text (PMC open access)** | 227 | 31.4% |
| **On bioRxiv** | 13 | 1.8% |
| **bioRxiv full text (JATS)** | 13 | 1.8% |
| On another preprint server | 10 | — |
| **Found in neither** | 205 | 28.4% |

- In both PubMed and bioRxiv: **10**
- PubMed only: **505** · bioRxiv only: **3**
- **Any full text retrievable: 234 (32.4%)** — the remaining 489 records are abstract/metadata-only or absent.
- Records with no DOI in the datasheet: 7

PubMed matches: 514 by DOI, 1 by title fallback. bioRxiv matches: 2 are themselves preprints, 10 via bioRxiv's own preprint→publication index, 1 via a Europe PMC link confirmed against the bioRxiv API.

## 2. How much of each curated column could be recovered online?

For every non-empty cell we ask: could this information have been obtained from the online sources, and from where? A cell counts as recoverable when ≥60% of its distinctive terms are present in that tier (identifiers, titles, authors, dates and funding get bespoke checks instead of term matching).

| Column | kind | cells | recoverable | from metadata | from abstract | **only from full text** | partial | not found |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| Date | structured | 723 | **62.1%** | 449 | 0 | **0** | 69 | 205 |
| Family of Compounds | derived | 723 | **47.9%** | 144 | 107 | **95** | 81 | 296 |
| Standard Product Class | derived | 723 | **28.2%** | 94 | 41 | **69** | 153 | 366 |
| Compounds | derived | 723 | **63.1%** | 295 | 104 | **57** | 43 | 224 |
| Concentration/Yield | derived | 723 | **46.6%** | 2 | 188 | **147** | 144 | 242 |
| Extra conditions or comparison for this concentration/Yield | derived | 723 | **42.6%** | 0 | 114 | **194** | 175 | 240 |
| Article | structured | 723 | **70.7%** | 511 | 0 | **0** | 3 | 209 |
| Authors | structured | 723 | **70.0%** | 506 | 0 | **0** | 11 | 206 |
| Corresponding Authors | structured | 723 | **49.1%** | 233 | 0 | **122** | 2 | 366 |
| Acknowledgement | structured | 718 | **36.4%** | 42 | 0 | **219** | 129 | 328 |
| strain used/RLA collection strain | derived | 722 | **32.1%** | 5 | 45 | **182** | 96 | 394 |
| genetic engineering strategy used | derived | 723 | **36.2%** | 1 | 57 | **204** | 156 | 305 |
| carbon source | derived | 723 | **39.1%** | 23 | 74 | **186** | 70 | 370 |
| cultivation mode | derived | 723 | **32.9%** | 1 | 43 | **194** | 109 | 376 |
| Comments | derived | 723 | **35.4%** | 0 | 47 | **209** | 210 | 257 |
| Application | derived | 723 | **38.3%** | 22 | 115 | **140** | 196 | 250 |
| Link | structured | 723 | **71.5%** | 517 | 0 | **0** | 0 | 206 |

- **Bibliographic columns** (Date, Article, Authors, Corresponding Authors, Acknowledgement, Link): mean recoverability **60.0%** — these are what the repositories are built to give you.
- **Experimental/curated columns** (11 columns): mean recoverability **40.2%**. The `only from full text` column is the key number: that is the information that exists online but is *invisible* to a metadata-only or abstract-only pipeline.

## 3. Extraction ceiling — what an LLM could actually catch

If a downstream RAG ingests the *text* and lets an LLM extract these fields at query time, then coverage conditional on ingestion tier is an **upper bound on extraction recall**: a term that is not in the ingested text cannot be recovered without hallucinating.

Comparing the 284 records where we have only a PubMed abstract against the 234 where we retrieved full text:

| Column | abstract-only | with full text | gain |
|---|---:|---:|---:|
| Family of Compounds | 50.4% | **86.8%** | +36.4 pts |
| Standard Product Class | 23.2% | **59.0%** | +35.8 pts |
| Compounds | 81.0% | **96.6%** | +15.6 pts |
| Concentration/Yield | 39.1% | **96.6%** | +57.5 pts |
| Extra conditions or comparison for this concentration/Yield | 26.1% | **100.0%** | +73.9 pts |
| strain used/RLA collection strain | 10.9% | **86.3%** | +75.4 pts |
| genetic engineering strategy used | 10.9% | **98.7%** | +87.8 pts |
| carbon source | 18.7% | **98.3%** | +79.6 pts |
| cultivation mode | 9.5% | **90.2%** | +80.7 pts |
| Comments | 8.1% | **99.6%** | +91.5 pts |
| Application | 25.4% | **87.6%** | +62.2 pts |

**Mean over the curated science columns: 27.6% from abstracts alone → 90.9% with full text.**

Read that as the headline result: an abstract-only pipeline is structurally incapable of answering questions about strain, carbon source, cultivation mode or genetic strategy — that information is almost never in the abstract. Full-text ingestion is not an optimisation, it is the precondition.

Note these are *ceilings*, not achieved accuracy. The residual gap once full text is in hand is small but real, and is mostly values that live in tables, figures and supplementary files rather than in body prose.

## 4. What this means

- **Only 32.4% of the datasheet has full text retrievable from open sources.** The other 67.6% sits behind publisher paywalls — reachable with authenticated institutional access, but not by this pipeline.
- The `partial` and `not found` counts flag cells worth spot-checking: either the source drew on a table/figure/supplement (not in the JATS body text), or the value warrants verification.

## 5. Method & provenance

- **PubMed** — NCBI E-utilities. Papers matched on DOI (`[AID]`); a title search with a ≥0.90 similarity gate is used as fallback.
- **Full text (PubMed side)** — NCBI PMC `efetch`; counted as available only when the JATS `<body>` is actually returned, i.e. the article is in the PMC open-access subset. A PMC record without an open `<body>` is reported as metadata-only.
- **bioRxiv** — the bioRxiv API. A record counts as *on bioRxiv* if (a) its own DOI is a bioRxiv DOI, (b) bioRxiv's `/pubs` index links a preprint to the published DOI, or (c) Europe PMC reports a preprint↔publication link **and** the bioRxiv API confirms that preprint exists. Full text is the preprint's JATS XML.
- bioRxiv DOIs appear under both the `10.1101/` and the newer `10.64898/` prefixes; both are recognised.
- Preprints on Research Square, Preprints.org and similar are reported separately — they are *not* counted as bioRxiv.

## 6. Files

| file | contents |
|---|---|
| `record_report.csv` | one row per datasheet record: identifiers, availability flags, and a `status::`/`score::` pair for each curated column |
| `column_coverage.csv` | the per-column table above, machine-readable |
| `extraction_ceiling.csv` | per-column upper bound on LLM extraction recall, abstract-only vs full text |
| `unresolved.csv` | records found in neither repository — worth a manual look |
| `summary.json` | all statistics in this report, machine-readable |