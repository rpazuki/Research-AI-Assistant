# Organism-oriented literature ingestion for the RAG — findings and plan

*Case study: Yarrowia lipolytica, 723 curated records (706 unique DOIs), 2016–2026.*

Context for this document: the RAG already works and can ingest raw PDFs, but its literature
supply is PubMed-dependent. The curated datasheet columns are **not** ingested — the full text
is ingested, and an LLM tool extracts the fields at query time. The target workflow is
**organism-first**, with the bioproduction assistant as a consumer of the same corpus.

---

## 1. The headline result

Because fields are extracted from ingested text at query time, per-column coverage of the
ingested text is an **upper bound on extraction recall**. A term that is not in the ingested
text cannot be recovered by any LLM without hallucinating.

Measured across the 723 records — comparing the 284 where we have only a PubMed abstract
against the 234 where full text was retrieved:

| Curated column | Abstract-only | With full text | Gain |
|---|---:|---:|---:|
| cultivation mode | 9.5% | **90.2%** | +80.7 |
| genetic engineering strategy | 10.9% | **98.7%** | +87.8 |
| strain used | 10.9% | **86.3%** | +75.4 |
| carbon source | 18.7% | **98.3%** | +79.6 |
| Concentration/Yield | 39.1% | **96.6%** | +57.5 |
| Compounds | 81.0% | **96.6%** | +15.6 |
| **Mean, science columns** | **27.6%** | **90.9%** | **+63 pts** |

**An abstract-only pipeline is structurally incapable of supporting a bioproduction assistant.**
Strain, carbon source, cultivation mode and genetic strategy are essentially never in the
abstract — they are Methods-section facts. This is not a tuning problem, a chunking problem or
a prompt problem. Full-text ingestion is the precondition for the feature to work at all.

Correspondingly, the residual failure *once full text is in hand* is small: of 234 full-text
records, only 26 `strain`, 23 `cultivation mode` and 7 `Concentration/Yield` cells fall short.
Those residuals are values living in tables, figures and supplementary files rather than body
prose — real, but second-order. **Acquisition is the whole game.**

---

## 2. PubMed fails this workflow twice, independently

This is the core architectural finding, and both failures are systematic rather than random.

**Failure 1 — discovery.** 191 of the 706 DOIs (**27%**) are not in PubMed at all. They are not
obscure: they are in *Fermentation*, *Biochemical Engineering Journal*, *Green Chemistry*,
*Chemical Engineering Journal*, *ACS Sustainable Chemistry & Engineering*, *Process
Biochemistry*. PubMed indexes biomedical journals; **bioproduction work is largely published in
chemical-engineering journals that PubMed does not index.** A PubMed-seeded organism search
misses exactly the literature the bioproduction assistant exists to serve.

**Failure 2 — depth.** PubMed supplies abstracts. Per §1, abstracts carry ~28% of the science.

An important corollary, and the most useful single reframing from this study:

> **"Not in PubMed" does not mean "not obtainable."** Of the 205 records absent from
> PubMed/bioRxiv, **98 are freely available right now** (66 gold OA, 16 hybrid, 10 bronze,
> 6 green). Corpus-wide, Unpaywall reports **380 of 704 DOIs are open access somewhere**, while
> the PMC-only pipeline retrieved just 234. **~146 free full texts are being left on the table**
> purely because we only looked in PMC.

Availability of the corpus, by acquisition route:

| Route | Papers | Notes |
|---|---:|---|
| PMC open-access XML | 222 | Best quality — structured JATS |
| bioRxiv JATS | 12 | Marginal; 1.8% of corpus. Not worth engineering around |
| **Free, but not in PMC** | **~146** | The quick win. MDPI, Frontiers, RSC, gold ACS |
| Paywalled → needs institutional access | 324 | The main body of work |
| Manual / broken | ~9 | 7 rows with no DOI; 2 DOIs absent from Crossref |

Publisher concentration makes the paywalled tier tractable — **5 publishers cover 88%**:
Elsevier 229, Springer Nature 157, MDPI 88, ACS 83, Wiley 61. Crossref advertises a **sanctioned
text-mining full-text link for 438 of 704 DOIs** (Elsevier: all 229).

---

## 3. Target architecture

The design flaw to fix is that **PubMed currently serves as both the discovery layer and the
content layer.** Split them. They have different failure modes and different solutions.

```
  organism (NCBI Taxonomy ID, not a string)
        │
        ▼
  ┌─────────────────────┐   PubMed + Europe PMC + Crossref/OpenAlex + bioRxiv
  │  FEATURE A          │   dedupe → canonicalise → relevance-filter
  │  List creation      │
  └─────────────────────┘
        │  candidate list (DOI-keyed manifest)
        ▼
  ┌─────────────────────┐   resolution ladder, cheapest & cleanest first,
  │  FEATURE B          │   ending in authenticated library access
  │  Full-text          │
  │  acquisition        │
  └─────────────────────┘
        │  JATS XML  ─or─  PDF
        ▼
  ┌─────────────────────┐   existing RAG ingestion (already handles PDFs)
  │  Ingest + metadata  │   + metadata sidecar for filtering & citation
  │  sidecar            │
  └─────────────────────┘
```

### Feature A — list creation (organism → candidate list)

1. **Seed from NCBI Taxonomy, not a name string.** *Yarrowia lipolytica* is taxid **4952**, and
   it carries historical synonyms — *Candida lipolytica*, *Saccharomycopsis lipolytica*,
   *Endomycopsis lipolytica*. A literal `"Yarrowia lipolytica"` query silently drops the older
   literature. For an organism-generic feature this matters even more: every organism has
   basionyms and reclassifications. Resolve taxid → synonym set → query expansion.
2. **Query several sources, not one.** PubMed/Europe PMC for the biomedical half; **Crossref or
   OpenAlex for the chemical-engineering half that PubMed cannot see**; bioRxiv for preprints.
   Union, then dedupe on DOI.
3. **Canonicalise.** One work = one entity. Collapse preprint → version of record (10 papers in
   this corpus exist as both, and their numbers can differ). Collapse duplicate rows (723 rows →
   706 DOIs here).
4. **Filter relevance, and record why.** Distinguish "studies the organism" from "mentions it in
   passing." Flag reviews — Crossref types 702 of 704 as plain `journal-article`, so document
   type must be inferred, not read off. Reviews restate primary results and inflate apparent
   consensus in a RAG.
5. **Emit a manifest**, not a finished datasheet: DOI, PMID/PMCID, title, year, journal,
   publisher, OA status, preprint/VoR, doc type, retraction status, acquisition route, licence.

### Feature B — full-text acquisition (the missing piece)

The RAG already ingests PDFs, so what is missing is the layer that turns a DOI into a document.
Implement as an ordered **resolution ladder**, stopping at the first success:

| # | Route | Yield here | Format | Notes |
|---|---|---:|---|---|
| 1 | PMC OA (`efetch db=pmc`) | 222 | JATS XML | Structured; always prefer |
| 2 | Europe PMC full text | overlap | JATS XML | Catches some PMC misses |
| 3 | bioRxiv JATS | 12 | JATS XML | Preprints only |
| 4 | **Unpaywall `best_oa_location`** | **~146** | XML/PDF | **Free, legal, immediate. Do this first.** |
| 5 | **Publisher TDM APIs** (Elsevier ScienceDirect, Springer Nature, Wiley) | up to 438 | XML | Sanctioned bulk route; needs Imperial entitlement + API key |
| 6 | **Authenticated library access** (OpenAthens / EZproxy / link resolver; LibKey if Imperial subscribes) | residual | PDF | DOI → institutional PDF in one hop |
| 7 | ILL / manual | ~9 | PDF | Broken DOIs, no-DOI rows |

Steps 4–6 are the ones to build. Step 4 alone moves full-text coverage from **32% → ~54%** with
no legal question and no credentials.

**On authenticated access — build it as TDM-API-first, proxy-second.** Bulk-pulling PDFs through
the library proxy is the route most likely to (a) trip publisher abuse detection and (b) get
Imperial's whole IP range blocked, affecting colleagues, not just this project. The publisher TDM
APIs exist precisely for this and are the sanctioned path — and Crossref already tells us 438/704
papers offer one. Reserve authenticated proxy retrieval for the residue that has no TDM route,
rate-limit it hard, and cache aggressively so a document is fetched exactly once.

### Ingestion and the metadata sidecar

- **Prefer XML over PDF wherever the ladder offers it.** PDF extraction damages *this corpus
  specifically*: strain names are `Po1g-Δku70`, `ΔEYD`, `Po1f`, and the Greek characters are
  routinely mangled by naive PDF text extraction. A corrupted `Δku70` is an unretrievable
  `Δku70`. Use GROBID (or publisher XML) rather than pdfminer/PyPDF, and validate on ~20
  documents against known-good JATS before trusting the rest.
- **Fetch supplementary material.** Strain tables, plasmid lists and raw yields routinely live in
  the SI, which is *not* in the JATS body. This is where most of the residual extraction gap
  from §1 lives.
- **Attach a metadata sidecar to every chunk** even though the datasheet columns aren't ingested:
  DOI, PMID, year, journal, organism/taxid, OA status, doc type, retraction flag, section label.
  This is what lets the RAG filter, cite to section level, and exclude retracted work — cheap to
  build, and it does not conflict with extract-at-query-time.

---

## 4. What the datasheet is actually for

Given fields are extracted at query time, the datasheet is **not** ingestible content. It has
three higher-value roles:

1. **The extraction contract.** The 17 columns are the specification of what the LLM tool must be
   able to pull out of full text. That is exactly what §1 measures.
2. **A gold-standard evaluation set — the most valuable artefact here.** 723 records × 17 fields
   ≈ 12,000 field-level assertions with known answers. Generate Q/A pairs ("what carbon source
   did *<paper>* use?", "what titre was reported?") and measure retrieval hit-rate and extraction
   accuracy per column. **Without this you cannot tell whether the ingestion actually works**, and
   §1 tells you the ceiling to measure against: ~91%, not 100%.
3. **Optionally, a structured numeric sidecar** (see the ranking caveat below).

---

## 5. Caveats and weak points

**Discovery**
- PubMed-only discovery misses **27%** of the relevant corpus, biased toward chemical-engineering
  journals — the bioproduction core. *This is the single most important finding.*
- Organism synonyms (*Candida lipolytica* et al.) will silently truncate results if the query is
  a string rather than a taxid.
- Reviews are not distinguishable from primary research via Crossref metadata.
- Indexing lag: the newest papers are not yet in PubMed (every miss in a 25-record 2026 sample was
  a recent paper). Refresh must re-check prior misses rather than marking them permanently absent.
- Non-English and grey literature (one *Chinese Journal of Biotechnology* DOI here) sit outside
  all of these indices.

**Acquisition**
- 324 papers (46%) are paywalled — the feature does not work without institutional access.
- Bulk proxy download risks an institution-wide block.
- Data hygiene: 2 DOIs are not registered in Crossref; 7 rows carry no DOI at all.

**Extraction**
- PDF-vs-XML fidelity: Greek characters, two-column interleaving, ligatures. Directly damages
  strain-name retrieval.
- Tables, figures and SI carry the residual ~9% that full-text prose does not.

**Corpus integrity**
- Preprint vs version-of-record: 10 papers exist as both, and reported numbers can differ. Two
  contradictory yields for one experiment, with no basis to choose between them, is a bad failure
  mode for an assistant.
- **Retraction monitoring is currently absent, and my check for it was weak** — Crossref's
  `update-to` field lives on the retraction *notice*, not the retracted article, so the "0 found"
  result should not be read as an all-clear. Wire in PubMed's `Retracted Publication` type and
  Retraction Watch on every refresh. A RAG citing a retracted yield is the worst available
  failure.

**Retrieval and answering**
- **Vector search cannot rank numbers.** "Which strain gave the highest lupeol titre?" is a
  ranking over quantities with heterogeneous units (`488.7 mg/L`, `13.4 mg/g WCO`,
  `400 mL CH₄ gVS⁻¹`). Embeddings will happily return a semantically similar passage with the
  wrong number. If the bioproduction assistant must answer superlative or comparative questions,
  a normalised structured table is required alongside the vector index — and the datasheet is
  already most of one.
- Entity synonyms — `(2S)-hesperetin` vs `hesperetin`; `DGA1` vs diacylglycerol acyltransferase;
  `Po1f`/`Po1g`/`W29`/`A101` — will cause silent retrieval misses without a normalisation layer.

**Method caveat on the numbers in this document**
- Coverage is measured by **token recall**: "is this vocabulary present in the source text?", not
  "does the source assert this claim?" It is a sound *upper bound* on extraction recall, which is
  what §1 claims — but it is not a measure of achieved accuracy. Only the eval harness (§4.2) can
  give you that.
- The ~146 free-full-text figure is Unpaywall's claim, not verified end-to-end. Expect some
  attrition when actually fetched.

---

## 6. Sequencing

| Phase | Work | Unblocks |
|---|---|---|
| **0** | Library TDM/licensing conversation; confirm LibKey/OpenAthens availability | Everything in Phase 3. Start now — it has human latency |
| **1** | **Unpaywall harvest (~146 free full texts)** | Full text 32% → ~54%, zero legal risk. Highest value per unit effort |
| **2** | Extraction spike: 20 docs, JATS vs GROBID-on-PDF; measure Δ/μ and table fidelity | Evidence-based choice of the PDF path the RAG already has |
| **3** | Publisher TDM APIs (Elsevier first — 229 papers, all TDM-linked), then authenticated library access for the residue | Full text → ~95%+ |
| **4** | Multi-source discovery (Feature A) with taxid-driven synonym expansion | Closes the 27% discovery hole |
| **5** | Eval harness from the datasheet | Tells you whether any of the above actually worked |
| **6** | Refresh loop: new papers, retraction checks, preprint→VoR promotion | Keeps the corpus honest |

Phase 1 before Phase 3 is deliberate: it is free, legal, and immediate, and it also de-risks the
extraction pipeline on real documents before any paywalled content is touched.

## 7. Decisions needed from you

1. **Organism-oriented scope**: does "studies the organism" include papers that merely mention it?
   This sets the discovery precision/recall trade-off.
   Answer: No need for papers that only mnetioned them.
2. **Legal**: may full text go to an external LLM/embedding API, or must the stack be local?
   *Architecture-determining.*
   Answer: All full text are kept on local embedding. The chunks from tool calling is the only thing that goes to external LLM.
3. **Numeric ranking**: must the bioproduction assistant answer superlative questions ("highest
   titre")? If yes, budget for the structured sidecar; vector search alone will not do it.
   Answer: Yes.
4. **Reviews**: include, exclude, or down-weight?
   Answer: include, with an extra flag that they are reviews.
