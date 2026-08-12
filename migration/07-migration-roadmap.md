# Migration Roadmap

## 1. Migration Strategy

Build the successor as a new repository/project and run it beside the current application. Do not perform a big-bang schema rewrite inside the current database.

The strategy is:

```text
stabilise legacy -> inventory and snapshot -> build new foundations
-> shadow discovery -> shadow acquisition/parsing -> shadow extraction
-> build releases/search -> dual-run users -> cut over -> retire safely
```

The old system remains the operational reference until explicit cutover gates pass. New outputs are compared against old outputs and expert gold data. Data is imported through versioned adapters so legacy ambiguity is visible rather than normalised away.

## 2. Guiding Rules

1. Never copy old vector embeddings as canonical data; regenerate projections from approved renditions.
2. Never treat a current cache validator pass as proof of semantic consistency.
3. Never merge PMID and PMCID document rows without an identity decision.
4. Never promote a current datasheet model row directly to an approved claim.
5. Preserve immutable original assets when checksums and rights can be established.
6. Preserve user-visible continuity: identities, memberships, invitations, roles, sessions where appropriate, and familiar chat/search workflows.
7. Keep legacy artefacts read-only after snapshot.
8. Every import run is reproducible, versioned, restartable, and produces an exception report.
9. Cut over at a corpus-release boundary, not in the middle of a pipeline run.
10. Keep rollback possible until the agreed observation period ends.

## 3. Legacy Asset Classification

Before import, classify every legacy artefact:

| Class | Meaning | Action |
|---|---|---|
| A: trusted original | Original bytes, checksum verified, source/access metadata sufficient, rights approved | Import as asset plus legacy provenance. |
| B: usable with review | Original bytes available but identity, rights, or acquisition provenance incomplete | Quarantine, review, then import. |
| C: derived and reproducible | Chunks, embeddings, parsed JSON, exports that can be regenerated from trusted original | Retain for comparison; regenerate in new system. |
| D: derived and not fully verifiable | Datasheet rows/evidence, merged discovery candidates, partial manifests | Import as unreviewed legacy proposals/observations with warning, never as approved truth. |
| E: unsafe or obsolete | Secrets, stale checkpoints, mutable run caches, orphan files, model caches | Do not import; retain only under incident/audit policy if needed. |

## 4. Current-to-New Mapping

| Current artefact | New target | Migration treatment |
|---|---|---|
| `users` | `users` | Import IDs/emails/status; preserve compatible password hashes only with forced upgrade/reset policy; increment auth epoch. |
| user invitations | memberships/invitations | Import pending valid invitations after validating workspace and expiry. |
| `role` | membership role/capabilities | Map researcher/admin; assign data steward/reviewer explicitly later. |
| chat sessions/messages | legacy chat archive or new chat records | Import for read-only history if citations can be resolved; otherwise label citations as legacy/unverified. |
| feedback | feedback linked to migrated/archive messages | Import where message mapping exists. |
| `ingestion_manifests` | legacy import runs and source lineage notes | Do not call them corpus releases; preserve as historical run metadata. |
| `documents` | proposed works, manifestations, source assertions, and possibly renditions | Split through identity reconciliation; do not one-to-one copy. |
| `document_chunks` | comparison artefacts only | Regenerate from approved renditions; old chunk IDs may be kept in mapping table for chat history. |
| chunk vectors | none in canonical import | Do not migrate; rebuild named embedding projections. |
| discovery candidates | source-like merged legacy observations and relevance decisions | Mark as post-merge legacy observations; raw source provenance unavailable. |
| discovery manifests/CSVs | legacy run artefacts | Import checksummed package for audit; not raw observations. |
| datasheet acquisition files | candidate assets | Verify bytes, checksum, identity, route, and rights. Quarantine when attempt history is missing. |
| extracted full-text JSON | legacy parser rendition | Import only for comparison or temporary evidence; reparse original asset for approved use. |
| datasheet rows/cells | unreviewed legacy claim proposals | Convert through a versioned importer; require evidence validation and review. |
| extraction cache | legacy model attempt | Preserve only if model/template/prompt provenance is sufficient; never use as new cache hit. |
| wide CSV exports | historical export packages | Preserve checksums; do not re-import as papers. |
| local inventories/protocols | dataset/protocol work + structured source records | Re-import original files preserving rows/sheets/sections and sensitivity policy. |
| PubMed checkpoints | none | Do not treat as authoritative; start new connector cursor lineage. |
| corpus cache docs/chunks JSONL | legacy snapshot input | Use to find artefacts/mappings; semantic dedupe before work creation. |
| local model cache | deployment cache | Re-download/verify through standard dependency/model process; not migrated data. |
| `backend/adminPass` | none | Security incident, rotate/revoke, remove; never import. |

## 5. Identity Reconciliation During Migration

The current cache demonstrates route-created duplicates. Migration must perform an explicit identity build:

1. Read every legacy document and preserve its legacy table/key/cache/run location.
2. Extract all DOI, PMID, PMCID, accession, internal IDs, and asset digests.
3. Normalise identifiers with versioned functions.
4. Build exact-identifier components.
5. Detect components containing conflicting DOI, PMID, or resource kinds.
6. Link PMID and PMCID manifestations to one work where supported, rather than keeping separate works by route.
7. Propose title/author/year near matches only for review.
8. Produce counts for source rows, proposed works, exact merges, conflicts, and unresolved records.
9. Freeze a reviewed identity mapping table before importing claims or chat citations.

Required legacy mapping table:

```text
legacy_object_map(
  legacy_system, legacy_type, legacy_id, legacy_location_digest,
  new_type, new_id, mapping_status, decision_id, imported_at,
  importer_version, note
)
```

This table allows old links and diagnostic reports to resolve without contaminating new identifiers.

## 6. Migration Phases

### Phase 0: Security, freeze, and baseline

**Objective:** stop preventable loss and establish a trustworthy baseline.

Deliverables:

- close or contain the tracked-credential incident;
- nominate product, data-steward, security, and technical owners;
- freeze architectural expansion in legacy pipelines;
- produce DB schema/data dump, object/cache inventory, Git revision, configs, and checksums;
- record current test, evaluation, corpus, discovery, acquisition, and datasheet metrics;
- produce the ten measurements in [Scale §2](10-scale-sizing-and-proportionality.md); without them
  every "no unexplained regression" gate in this roadmap is undefined;
- produce the re-acquisition list required by [Scale §6](10-scale-sizing-and-proportionality.md):
  how many legacy assets must be fetched again because their bytes, checksum, route, or rights
  evidence are insufficient, at what wall-clock cost under policy-compliant rates, and what is no
  longer obtainable at all;
- publish the legacy freeze carve-out
  ([Delivery §4](11-delivery-model-and-continuity.md)), naming which datasheet runs continue on the
  legacy system and how their outputs are imported;
- identify licence/sensitivity/retention classes for legacy assets;
- choose new project repository and deployment environments;
- define migration decision log and exception process.

Exit gates:

- owner signs snapshot inventory;
- restore of legacy snapshot succeeds in an isolated environment;
- secret incident actions are documented;
- baseline metrics and 706 DOI benchmark are reproducible;
- no unexplained writable legacy copy is used for import.

### Phase 1: Platform and domain foundation

**Objective:** build the secure control plane and immutable data plane.

Deliverables:

- repository skeleton and CI;
- users, workspaces, memberships, groups, invitations, auth, and policy engine;
- object store with content-addressed immutable registration;
- audit events;
- config/scope versioning;
- task DAG, leases, outbox, retry taxonomy;
- source observation, assertion, work identity, manifestation, asset, and rights schema;
- development fake connectors/providers;
- two-workspace isolation suite;
- backup and restore path.

Exit gates:

- complete fixture can be stored and replayed without network;
- duplicate task execution has no duplicate side effect;
- cross-workspace negative tests pass;
- object corruption is detected;
- migrations, OpenAPI, and generated schemas agree.

### Phase 2: Discovery shadow

**Objective:** replace PubMed-centric discovery with reproducible source observations and reviewed identity.

Deliverables:

- PubMed, Europe PMC, Crossref, OpenAlex, and DataCite discovery connectors;
- raw response store and parser fixtures;
- source assertions and identity graph;
- relevance, conflict, merge/split/version-link review UI;
- source completion and coverage dashboard;
- immutable scope/query versions and cursors;
- legacy candidate importer.

Shadow method:

1. Run current and new discovery from equivalent frozen scope.
2. Compare the 706 DOI gold set and source-unique contributions.
3. Explain every gold regression and every identity difference.
4. Have experts sample new-only and old-only records.

Exit gates:

- no unexplained loss of relevant gold works;
- title-only auto-merge count is zero;
- every source result is replayable from stored raw bytes;
- required source degradation blocks or visibly gates freezing;
- steward approves identity/relevance workflow.

### Phase 3: Acquisition and parsing shadow

**Objective:** create the lawful immutable asset and rendition foundation.

Deliverables:

- Europe PMC/PMC, open repository, Unpaywall resolution, approved TDM, and assisted routes;
- distributed host/credential rate control;
- full acquisition-attempt history and rights engine;
- upload quarantine, malware, MIME, size, SSRF, and identity checks;
- JATS and layout-aware PDF parsing;
- OCR path;
- structured table/cell rendition;
- parser quality dashboards and review queue;
- legacy asset inventory/import tool.

Shadow method:

- run acquisition planning for the same candidate set without duplicate unauthorised fetches;
- reuse only assets whose rights and checksums permit it;
- compare acquired tiers, route outcomes, file identity, section/table counts, and character fidelity;
- sample current extracted JSON against new renditions.

Exit gates:

- all eligible assets have rights and attempt provenance;
- assisted acquisition completes in the product UI;
- no incorrect-work asset enters eligible renditions;
- gold parser fixtures pass;
- legacy assets are classified A-E with exception list.

### Phase 4: Claims, review, and export

**Objective:** replace one-row-per-paper extraction with evidence-backed scientific claims.

Deliverables:

- entities, experiments, conditions, claims, revisions, and reviews;
- template/prompt/selector/validator versioning and complete fingerprints;
- deterministic bibliographic projection;
- table-aware and multi-pass extraction;
- exact evidence and numeric/unit validation;
- claim review UI and assignment;
- long-form release export plus optional wide XLSX;
- RO-Crate/BagIt-inspired package validator;
- legacy row importer as unreviewed proposals.

Shadow method:

1. Select a scientifically representative current datasheet sample.
2. Correct it into claim/evidence gold labels.
3. Run new extraction from approved renditions.
4. Compare at experiment/claim level, not spreadsheet row equality.
5. Review every mismatch and classify parser, selector, model, template, or gold error.

Exit gates:

- 100 percent accepted machine claims have verified evidence pointers;
- multi-experiment works are represented without row loss;
- deterministic metadata does not depend on model output;
- reviewer can correct and version every claim;
- package validation and checksum verification pass offline;
- legacy proposals remain visibly unapproved until reviewed.

### Phase 5: Corpus release, indexing, and RAG

**Objective:** make approved evidence the serving boundary.

Deliverables:

- draft/validate/approve/publish/rollback release state machine;
- deterministic release manifest and parent diff;
- versioned chunk, lexical, embedding, and structured claim projections;
- retrieval planner and policy-first filtering;
- stable evidence citation resolver;
- generation provenance and citation validation;
- release evaluation report and alias switch;
- current RAG benchmark importer and comparison UI.

Shadow method:

- build new release from the reconciled current corpus;
- answer benchmark and sampled live questions in both systems;
- compare retrieval, duplicate-work rate, citation accuracy, faithfulness, latency, and cost;
- red-team restricted groups and a second isolated workspace.

Exit gates:

- retrieval metrics meet approved non-regression bounds;
- unsupported/citation metrics meet release threshold;
- no policy leakage in automated or manual probes;
- release can publish and roll back without reindexing;
- every new answer citation resolves to an immutable evidence span.

### Phase 6: User and workflow cutover

**Objective:** move real users while preserving operational continuity.

Deliverables:

- final user/membership/invitation import;
- password reset or compatible hash-upgrade flow;
- optional read-only legacy chat archive with citation status;
- user training and steward/operator runbooks;
- dual-link period from old UI to new UI;
- support and incident channels;
- final production release and rollback checkpoint.

Cutover sequence:

1. Announce freeze window and expected user impact.
2. Stop new legacy ingestion/datasheet runs.
3. Let in-flight work finish or cancel at recorded checkpoints.
4. Take final incremental snapshot and import decisions/users/history.
5. Validate counts, mappings, access, and active release.
6. Set legacy application read-only.
7. Route users to new web application.
8. Monitor auth, policy denials, query quality, queue health, and support reports.
9. Keep legacy read-only and new release rollback available through observation period.

Exit gates:

- user/account reconciliation signed off;
- no critical migration exceptions unresolved;
- restore/rollback drill completed;
- users can complete ask, discovery, assisted acquisition, review, export, and admin journeys;
- owner approves end of observation period.

### Phase 7: Retirement and archive

**Objective:** remove legacy risk without losing required evidence.

Deliverables:

- final checksummed archive and data-retention decision;
- legacy environment credentials revoked;
- legacy workers and write endpoints disabled;
- old indexes/model caches removed under policy;
- old database/object access reduced to archive custodians;
- unresolved exception register retained;
- post-migration evaluation and lessons learned;
- ownership transferred to normal operations.

Exit gates:

- no production traffic depends on legacy services;
- archive restore/read procedure tested;
- deletion/retention/legal obligations signed off;
- cost and security monitoring confirms retirement.

## 7. Recommended Delivery Order and Planning Envelope

For planning, assume:

- 2-3 backend/data engineers;
- 1 frontend engineer shared across phases;
- regular scientific data-steward/reviewer time;
- part-time security/platform support;
- no new custom OCR/model research in the critical path.

A realistic initial envelope is **32-40 working weeks** to controlled production cutover, followed by an observation and retirement period. This is a planning range, not a commitment. Phase 0 should refine it using corpus size, asset rights classification, and review throughput.

**This envelope is conditional on the staffing above actually existing.** The legacy repository is a
single-maintainer, agent-assisted codebase; if the four-FTE team is not named and committed, this
roadmap is not slow but unexecutable, and the scope must be reduced to the M1 milestone before
Phase 1 begins. See [Delivery Model §2](11-delivery-model-and-continuity.md) for the three delivery
profiles and their comparison.

**Users should not wait until week 33.** The architecture supports a useful release at the end of
Phase 3 - retrieval and citation over verified evidence spans, without the claim graph and therefore
without claim review. Dual-run real researchers on that milestone (M1) rather than at Phase 6; it
retires the audit's critical findings C-2 and C-3 twenty weeks earlier and produces the best
evaluation signal available. See [Delivery Model §3](11-delivery-model-and-continuity.md).

Suggested overlap:

```text
Weeks 1-4:   Phase 0
Weeks 3-10:  Phase 1
Weeks 8-15:  Phase 2
Weeks 12-21: Phase 3
Weeks 18-28: Phase 4
Weeks 24-34: Phase 5
Weeks 33-40: Phase 6
After gate:  Phase 7 and observation
```

Do not compress steward review, security gates, or shadow comparison merely to match the range.

## 8. Cutover Reconciliation Report

The final report must reconcile:

```text
legacy users -> new users/memberships
legacy works/documents -> new works + unresolved/quarantined
legacy original assets -> imported + rejected + missing
legacy rows -> imported proposals + approved claims + rejected/unmapped
legacy chats -> imported archive + omitted with reason
legacy active corpus -> new release items
legacy benchmark -> new evaluation run
```

For each line provide source count, distinct logical count, imported count, merged count, rejected count, unresolved count, and a downloadable exception list.

## 8a. Migration Tripwires

This section covers rolling back a *cutover*. It does not cover abandoning or re-scoping the
*migration*, which is the more likely failure and needs criteria agreed before the work starts,
while they are still cheap to agree. Those tripwires - unstaffed profile, missing Phase 0
measurements, an unachievable evidence-exactness gate, an unaffordable review budget, a breached
freeze, and elapsed time beyond 1.5x the envelope - are in
[Delivery Model §7](11-delivery-model-and-continuity.md). Review them at each phase gate.

## 9. Rollback Plan

### Before user cutover

Rollback is simply continued use of legacy while new shadow runs are corrected.

### During cutover window

1. Stop new writes in the successor.
2. Preserve successor task and audit state.
3. Restore routing to legacy read/write only if its final snapshot delta can be safely reconciled later.
4. If legacy was already read-only and data was created only in successor, prefer fixing/rolling back the corpus release rather than returning to split writes.
5. Communicate which user actions are delayed or require replay.

### After successful write cutover

Do not reopen both systems for independent writes. Use:

- corpus alias rollback for content/search faults;
- application version rollback for software faults;
- database PITR only for severe data-store incidents;
- task cancellation/retry for pipeline faults;
- legacy read-only archive for historical reference.

## 10. Major Migration Risks

| Risk | Likelihood/impact | Mitigation |
|---|---|---|
| Legacy content rights are unclear | High/high | Asset classification, steward/legal queue, metadata-only fallback, no assumed permission. |
| PMID/PMCID/DOI duplicates inflate or split works | High/high | Explicit identity graph, reviewed mapping, comparison report. |
| Current rows lack valid evidence | High/high | Import as proposals, reparse/re-extract, required review. |
| New multi-source discovery changes corpus unexpectedly | High/medium | Gold benchmark, source contribution report, expert old/new sample. |
| Review throughput becomes bottleneck | High/medium | Prioritise critical predicates, assignment queues, measure correction rate, staged release. |
| Two systems drift during build | Medium/high | Architecture freeze, frozen snapshots, scripted deltas, one migration owner. |
| External API/terms change | Medium/high | Connector version/policy review, raw replay, degraded gates, alternate sources. |
| New model/provider unavailable | Medium/medium | Provider abstraction, local/restricted fallback, batch park/resume, deterministic fixtures. |
| Multi-workspace policy bug | Low/high | Required workspace scope, RLS, negative tests, staged second workspace. |
| Overbuilding delays useful release | Medium/medium | Modular monolith, Postgres queue/search, MVP gates, defer optional integrations. |

## 11. What Not to Carry Forward

- `NormalizedDocument` as the universal domain schema;
- PubMed, PMID, or PubMedBERT as core identity;
- one vector dimension in the document chunk table;
- one row per paper as extraction truth;
- mutable append-only run caches with changing checksums;
- checkpoints not keyed by full query/config/connector version;
- run-directory paths as asset identity;
- source-priority merge without field assertion lineage;
- title-based automatic deduplication;
- in-memory rate state that forces one worker topology;
- wide CSV as the primary auditable output;
- re-importing an export as fake paper text;
- global `chat_visible` as access control;
- model confidence as review;
- unverified evidence quotes;
- status labels that mix discovery, acquisition, extraction, and ingestion;
- plans and READMEs that mix current, future, and historical truth.

## 12. What to Reuse

- FastAPI/Next.js/PostgreSQL competence and deployment knowledge;
- internal-only login and invitation user experience;
- same-origin `httpOnly` cookie pattern;
- provider abstraction concepts;
- retry/backoff and outcome taxonomy lessons;
- strong-ID-only automatic canonicalisation lesson;
- respectful acquisition ladder principles;
- persisted batch parking/resume pattern;
- evaluation question and expert review workflows;
- useful test fixtures after rights/redaction review;
- existing gold discovery set and corrected samples;
- user feedback and analytics concepts, redesigned around releases.

Reuse is by extracted contract and verified behaviour, not by copying modules wholesale.
