# Technical Spikes and Open Choices

Status: proposed
Applies to: Phases 1-4
Owner: technical owner
Last verified: 2026-08-12

## 1. Purpose

Documents 00-09 specify contracts and gates. Several of those gates depend on technology choices
that the plan leaves entirely open, and at least two of them are not obviously achievable with
available components. A gate whose feasibility is unknown is not a gate; it is a hope that will be
quietly renegotiated under schedule pressure, in the direction of the thing the plan was written to
prevent.

Each spike below is time-boxed, produces a written decision, and blocks a named epic. Run them
early - most are cheap, and all of them are cheaper than discovering the answer in Phase 4.

## 2. S1 - Document parsing stack (blocks E7; highest technical risk in the plan)

[Lifecycle §8](04-data-lifecycle.md) requires a parser table covering JATS, born-digital PDF,
scanned PDF with OCR, DOCX, XLSX/ODS, CSV/TSV, HTML, and plain text, producing hierarchical
sections with stable node IDs, exact text with source coordinates, tables as structured cells with
captions and footnotes, figures, separated reference sections, and parser quality metrics.

The plan names no candidate for any of these, and never acknowledges that the PDF and table
requirements are the hardest engineering in the entire design. The whole evidence model - and
therefore the product's central claim - rests on this layer.

### Required decisions

| Need | Candidates to evaluate | Notes |
|---|---|---|
| JATS/NLM XML | `lxml` with a namespace-aware traversal | Legacy code already does this; audit finding M-5 says it is duplicated and mishandles nesting. Rebuild once, with fixtures. |
| Born-digital PDF text plus geometry | PyMuPDF; pdfplumber over pdfminer.six; GROBID; Docling | **Licence gate below.** |
| Scholarly PDF structure | GROBID (TEI XML with coordinates) | Java service; adds a deployment unit; strong on scholarly layout and references. |
| OCR | Tesseract; OCRmyPDF; PaddleOCR | Needs language, model, and version recorded per page (04 §8). |
| Table structure | Camelot; pdfplumber; Docling; GROBID | Table fidelity is a named quality gate (06 §2.4) with no chosen implementation. |
| DOCX / XLSX / CSV | `python-docx`, `openpyxl`, stdlib `csv` with dialect detection | Low risk. |

### Licence gate

At least one leading candidate is copyleft. PyMuPDF is dual-licensed AGPL-3.0 or commercial;
adopting it under AGPL has consequences for a network-served application if the project is ever
distributed or open-sourced. [Quality §5](06-quality-evaluation-operations.md) already requires a
"dependency and licence scan" in CI, but the plan never states the project's own licence position -
[Repository Plan §2](08-repository-documentation-plan.md) leaves `LICENSE` as an open comment and
[Backlog §7](09-implementation-backlog.md) omits it from the owner decisions.

**Decide the project licence before S1 concludes.** An AGPL parser is fine for an internal,
undistributed service and a problem the day someone wants to publish the code - which, for a
research-group tool at a university, is a realistic future.

### Deliverable

A 1-2 week spike producing: a chosen stack per content type with licence recorded; a gold fixture
set of 15-25 real papers spanning born-digital, scanned, two-column, table-heavy, and
supplementary-material cases; measured values for every metric in
[Quality §2.4](06-quality-evaluation-operations.md); and the achievable threshold per metric. If a
threshold in 06 §2.4 is not achievable, revise the threshold in writing, with evidence.

## 3. S2 - The evidence-span exactness contract (blocks E7/E8; the plan's central unproven assumption)

[Data Model §9.4](03-data-model-and-provenance.md) requires that span creation "verifies that the
quoted text or structured cell value matches the referenced rendition node".
[Quality §2.4](06-quality-evaluation-operations.md) sets evidence-coordinate validity at **100
percent**. [Lifecycle §9](04-data-lifecycle.md) requires that "evidence span exists and exact quoted
bytes/text match".

"Exact" is undefined, and for PDFs it is not achievable in the naive reading. Between the asset
bytes and any quotable string sit: ligature decomposition (fi, fl), soft and hard hyphenation across
line and page breaks, multi-column reading order, superscripts and subscripts flattened into the
text run, Unicode normalisation forms, non-breaking and thin spaces, en/em dashes versus hyphens,
Greek letters emitted from symbol fonts, and per-engine whitespace policy. Two parsers of the same
PDF do not produce byte-identical text, and a model quoting from supplied evidence will not
reproduce the parser's whitespace.

The plan is right to demand mechanical verification - audit finding C-3 is real and important. The
gate simply needs a definition, or it will be weakened silently the first time a real paper fails it.

### Deliverable: a written normalisation contract

Specify, versioned as `span_normalisation_version`:

- the exact transformation chain applied before comparison, in order - Unicode normalisation form,
  whitespace collapsing, hyphenation rejoining across line breaks, ligature expansion, quotation and
  dash folding, case policy;
- what is preserved verbatim and never folded - digits, units, chemical and strain names, Greek
  letters, superscript/subscript markers;
- the comparison rule: exact match on the normalised form, with the raw offsets into the rendition
  retained so the original bytes remain addressable;
- what happens on failure - the proposal is rejected as unverified evidence, not repaired;
- how the contract is versioned, since changing it invalidates prior verification.

Then restate the gate precisely: **100 percent of accepted claims have spans that resolve to their
rendition node and match under normalisation version N.** That is provable. "Exact bytes" is not.

Also add a fixture suite for the hard cases above, and a property test that span verification is
stable under re-serialisation of the rendition.

## 4. S3 - Embedding profile and inference hardware (blocks E10)

The plan defines embedding *profiles* and per-dimension tables (03 §13.3) and never says which model
is used, where it runs, or what it costs. Three unaddressed points:

1. **The inherited default is questionable.** The legacy system uses
   `microsoft/BiomedNLP-PubMedBERT-base-uncased-abstract-fulltext` as the primary retrieval encoder.
   That checkpoint is a masked-language model, not a sentence-embedding model - it was not trained
   with a contrastive retrieval objective. Mean- or CLS-pooled raw MLM checkpoints commonly
   underperform much smaller purpose-trained bi-encoders on retrieval, sometimes badly, despite
   superior domain vocabulary. The migration is the moment to test this rather than inherit it.
   Evaluate at minimum: the current PubMedBERT configuration as baseline, a strong general-purpose
   retrieval encoder, and a biomedical model trained for retrieval. Decide on measured
   recall@k / nDCG@k on the workspace benchmark, not on domain-vocabulary reasoning.
2. **Hardware is unstated.** Local embedding of the full corpus at each new embedding profile is a
   compute event. Is there a GPU on the deployment VM? If not, measure CPU throughput and multiply
   by the chunk count from [Scale §2](10-scale-sizing-and-proportionality.md) to get the honest
   release-build time. A hosted embedding API is an alternative that has a rights consequence -
   [Connectors §9](05-connectors-rights-security.md) treats `create_embeddings_external` as a
   distinct permitted action, which means restricted content cannot use it and needs a local path
   regardless.
3. **Model weights are deployment state, not migration data.** Already correct in
   [Roadmap §4](07-migration-roadmap.md); make sure the persistent-volume caching rule from the
   legacy deployment carries over so a rebuild does not re-download on every restart.

## 5. S4 - Vector index strategy and release build time (blocks E10)

The plan specifies "pgvector tables separated by embedding model and dimension" and nothing about
indexes. Concrete choices with real consequences:

- **Index type.** pgvector offers IVFFlat and HNSW. HNSW gives better recall/latency and does not
  need a populated table to build well; IVFFlat builds faster and uses less memory but needs
  representative data and re-tuning as the corpus grows. The legacy system uses `ivfflat` with
  `lists = 100`, chosen for a corpus that no longer describes the target. Choose deliberately and
  record the parameters in the embedding profile, since they are part of what makes a release
  reproducible.
- **Dimension limits.** pgvector's indexable dimension ceiling for the `vector` type constrains
  which models can be indexed directly; higher-dimension models require half-precision or reduced
  representations. Check the ceiling against candidate models in S3 before committing, and record
  the storage type in the profile.
- **Build time is the publish cost.** Combined with [Scale §5](10-scale-sizing-and-proportionality.md),
  measure index build time per 100k chunks on target hardware and set a publish-window SLO. If
  incremental projection is implemented as §5 requires, index maintenance rather than full rebuild
  becomes the normal path - state which one the release worker does.
- **Two projections coexist during publish.** Size disk for it.

## 6. S5 - Deployment substrate (blocks E1)

[Backlog §7](09-implementation-backlog.md) defers "which managed Postgres and object-store providers
are approved" to the owner. Three further substrate choices are not even listed, and E1 cannot be
built without them:

| Substrate | Plan position | Needed decision | Fallback if the institution provides nothing |
|---|---|---|---|
| Object storage | "S3-compatible" (02 §4.2) | Named service with versioning, encryption, lifecycle, access logs | Self-hosted MinIO on the deployment VM - then state explicitly how it is backed up, since a local object store on the same disk as the database is not a durable data plane, and [Quality §9.1](06-quality-evaluation-operations.md) forbids calling a local directory a backup |
| Secret manager | "institution-approved" (05 §8.1) | Named service and rotation mechanism | Encrypted-at-rest environment injection with documented rotation, plus the ban on runtime secret files that the `backend/adminPass` incident motivates |
| Observability | Metrics, logs, traces listed (06 §6) with no tooling | OpenTelemetry plus a named backend, or structured logs plus a named metrics store | Structured JSON logs plus the existing `logs.sh` / `collect-logs.sh` support-bundle approach, with tracing deferred per [Scale §3.2](10-scale-sizing-and-proportionality.md) |
| Malware scanning | Required gate (04 §7) | Named scanner and its update path | ClamAV in the parsing worker image, with signature-freshness monitored - an out-of-date scanner passing everything is worse than a recorded exception |

Each of these is a one-line decision that blocks weeks of work if made late.

## 7. S6 - The evidence-in-context review interface (blocks E7/E8; largest frontend unknown)

[Target Architecture §10](02-target-architecture.md) requires that "evidence review shows quote in
source context with page/section/table coordinates". [Lifecycle §10](04-data-lifecycle.md) requires
the claim review screen to show "exact evidence highlighted in page/section/table context".

That is a PDF viewer with coordinate-accurate overlay highlighting, plus a table cell inspector,
plus a JATS section renderer, plus keyboard-driven queue navigation, plus optimistic-concurrency
edit conflicts. It is a significant piece of frontend engineering in its own right, and the roadmap
allocates "1 frontend engineer shared across phases" to it alongside candidate adjudication, merge
and split, the acquisition queue, assisted upload, parse quality review, release comparison, export,
admin, and evaluation screens.

The new frontend is several times the surface of the current one, and the plan never says so.
Actions:

- prototype the evidence viewer in Phase 2, not Phase 4 - it determines what the parser must emit
  (bounding boxes per span, or only character offsets), so S1 and S6 constrain each other;
- decide the rendering approach: render the PDF with overlays from stored coordinates, or render the
  rendition tree as HTML and drop the page image entirely for born-digital content;
- pick and record a component library, a table/virtualised-list approach for review queues, and an
  accessibility target (name a WCAG level - [Quality §5](06-quality-evaluation-operations.md)
  mentions "accessibility smoke tests" without a standard);
- re-estimate frontend effort after the prototype, and reflect it in the roadmap envelope.

## 8. S7 - Provider behaviour the design depends on (blocks E8/E11)

Two mechanisms are load-bearing and provider-dependent:

1. **Structured output with schema adherence** for extraction proposals (04 §9). Validate that the
   chosen provider enforces the schema strictly, how it behaves on refusal or truncation, and
   whether `max_tokens` truncation can produce syntactically valid but semantically truncated
   output that passes schema validation. Include a truncation fixture in the contract tests.
2. **Citation handles supplied to and returned by the model** (02 §8.3): "the server validates that
   every cited handle was supplied". Confirm the failure mode when the model returns a plausible but
   unsupplied handle, and make the invalid-handle path a first-class outcome rather than an error -
   an answer with one bad citation should degrade to a flagged answer, not a 500.

Also note a constraint the legacy system already learned and that
[CLAUDE.md §17.11](../CLAUDE.md) records: sampling parameters are model-gated, and newer Claude
models reject `temperature`/`top_p`/`top_k` with a 400 rather than ignoring them. The provider
adapter must decide sampling parameters per target model. Carry this into the new provider
abstraction as a contract test, since [Data Model §11.1](03-data-model-and-provenance.md) puts
`model_settings_json` into the extraction fingerprint and a settings field the provider rejects
would break every run.

## 9. Encoding `mistakes.md` Into the New Project

[Repository Plan §15](08-repository-documentation-plan.md) says to "preserve `mistakes.md` as
migration evidence, then turn its durable lessons into ADRs/tests in the new project", but never
lists the lessons. Several are already reflected in the plan; several are not.

| Lesson in `mistakes.md` | Status in the plan | Action |
|---|---|---|
| Title matching is not identity | Central - P-3, E5 invariant | Covered. |
| `robots.txt` is a crawler rule, not an API contract | 05 §5.1 | Covered. |
| An absolute filesystem path in a shared column is a per-topology address | Content-addressed objects, "no serving citation points to a mutable path" | Covered. |
| An upstream's paging contract is not the one you assumed | 04 §4 pagination integrity gate | Covered. |
| A long provider call in a shared worker starves the other queue | 02 §6 worker pools | Covered in principle; ensure the durable per-stage concurrency cap is the mechanism, not the deployment count ([Scale §3.2](10-scale-sizing-and-proportionality.md)). |
| `.//` in an XML parser reaches into the record's own reference list | 04 §8 "references marked separately from focal-study content" | Covered; make it a named JATS fixture in S1. |
| Hand-written migrations drift from the ORM silently | 06 §5 migration/schema consistency check | Covered. |
| A dedupe rule inherits an assumption the new source breaks | Partially - identity is per-assertion now | Add a connector-onboarding checklist item: state which existing reconciliation rules the new source violates. |
| **A blanket-matching test fake answers the next query with the wrong entity** | **Not covered** | The plan relies heavily on "fake scholarly connector and fake model provider" (02 §11.1) for its deterministic tests. Require fakes to be fixture-keyed and to raise on an unmatched request rather than returning a default. A permissive fake makes the entire end-to-end suite pass while proving nothing. |
| **A disabled feature must not depend on what the enabled path needs** | **Not covered** | Every staged/flagged control in [Scale §3.2](10-scale-sizing-and-proportionality.md) creates this hazard. Require that a disabled feature's dependencies are exercised by the enabled path's tests, or that the flag removes the dependency entirely. |
| **Walrus truthiness silently swallows boolean filters**; `column != None` widens an UPDATE to every row | **Not covered** | These are policy-filter and bulk-update hazards in a system whose central safety property is "no request retrieves an item it cannot open". Add both as lint rules or reviewer checklist items on repository and policy code. |
| Documenting `source .env` imposes shell syntax on the file; each address has one owner | Conflicts with 08 §9.1 | See [Delivery §6](11-delivery-model-and-continuity.md); resolve in the configuration ADR. |

## 10. Spike Register

| ID | Spike | Time box | Blocks | Output |
|---|---|---|---|---|
| S1 | Document parsing stack and licence | 2 weeks | E7 | Chosen stack, gold fixtures, achievable quality thresholds |
| S2 | Evidence-span normalisation contract | 1 week | E7, E8 | Versioned contract, fixture suite, restated gate |
| S3 | Embedding model and inference hardware | 1 week | E10 | Measured model comparison, throughput, hardware decision |
| S4 | Vector index strategy and build cost | 3 days | E10 | Index type and parameters in the embedding profile, publish SLO |
| S5 | Deployment substrate decisions | 1 week, mostly owner time | E1 | Named services or documented fallbacks |
| S6 | Evidence-in-context review prototype | 2 weeks | E7, E8 | Working prototype, parser coordinate requirements, re-estimated frontend effort |
| S7 | Provider structured output and citation handles | 3 days | E8, E11 | Contract tests including truncation and invalid-handle paths |

S1, S2, and S6 are mutually constraining and should run together, before Phase 3 planning is
finalised. S5 should start immediately, since it depends on institutional response times rather than
engineering effort.

## 11. Additional Owner Decisions

To be added to [Backlog §7](09-implementation-backlog.md):

| Question | Recommended default | Decision owner |
|---|---|---|
| Project code licence, and will the successor be open-sourced? | Decide before S1; it constrains the parser stack | Product owner + institution |
| Is GPU available on the deployment target for embedding and OCR? | Assume no; measure CPU and size accordingly | Platform |
| Accessibility standard for the web application | WCAG 2.2 AA for review and chat surfaces | Product |
| Does the wide XLSX datasheet remain a first-class supported output? | Yes, generated from the release | Scientific owner |
| Are corpus analytics in the first release, or deferred to M3? | Deferred to M3; state it, do not drop it silently | Product |
| Which delivery profile ([Delivery §2](11-delivery-model-and-continuity.md))? | B or the hybrid, unless profile A staffing is named | Product owner |
