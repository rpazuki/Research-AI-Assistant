# Product Principles

## 1. Product Definition

**Lab AI Assistant** is an internal research-evidence platform for a scientific lab. It helps authorised lab members discover, acquire, organise, extract, review, search, and synthesise external literature and internal research material.

The software is lab-agnostic. A deployment becomes specific to a lab through versioned configuration, policies, source connectors, extraction templates, evaluation sets, and branding. Domain assumptions such as organism, pathway, experimental method, or output columns do not belong in the core.

The same deployed service may host more than one workspace, but data is isolated by default. A single-workspace deployment remains the simplest supported production profile.

## 2. Users and Access

The current user model remains recognisable:

- users are pre-provisioned by an administrator or invited;
- there is no public query endpoint;
- `researcher` and `admin` remain the initial roles;
- browser sessions use a secure `httpOnly` cookie and same-origin API proxy;
- backend access tokens remain short lived;
- future institutional login uses OpenID Connect;
- self-registration is disabled unless a deployment explicitly enables an approved identity domain.

The new model adds:

- **workspace membership**, so the same identity can belong to one or more labs;
- **data steward** and **reviewer** capabilities, assignable independently of broad administration;
- **groups**, for projects or restricted datasets;
- **policy grants**, evaluated against assets, renditions, claims, indexes, exports, and chat citations;
- service accounts with narrow scopes for connectors and automation.

Roles are convenient bundles. Authorisation is ultimately capability and resource based.

## 3. Primary User Journeys

### 3.1 Ask a research question

1. A researcher selects a workspace and optionally a corpus release.
2. The system retrieves authorised structured claims and unstructured evidence.
3. The answer clearly separates supported findings, uncertainty, and evidence gaps.
4. Every citation opens the exact evidence span and its work metadata.
5. The user can provide feedback or flag a source/claim for review.

### 3.2 Build a literature collection

1. A researcher or steward defines a versioned scope.
2. Connectors run a reproducible discovery strategy.
3. The user reviews conflicts, duplicates, and uncertain relevance.
4. The system records a frozen discovery snapshot and decisions.

### 3.3 Acquire content

1. The system proposes policy-compliant access routes.
2. Automatic acquisition records every attempt and stores immutable assets.
3. Blocked work enters an assisted queue.
4. A user can upload or register an authorised copy against the candidate.
5. The system validates file identity, type, integrity, malware status, and rights.

### 3.4 Build a scientific datasheet

1. A steward selects a versioned extraction template.
2. The system parses source assets and proposes entities, experiments, conditions, and claims.
3. Mechanical validators reject unsupported evidence and invalid units.
4. Reviewers correct and approve proposals in context.
5. The system exports long-form evidence tables and optional wide spreadsheets from an approved release.

### 3.5 Publish or refresh a corpus

1. A steward assembles approved works, renditions, and claims into a draft release.
2. Automated quality, policy, and evaluation gates run.
3. An authorised approver publishes the release.
4. Serving aliases switch atomically and can roll back.
5. Later source updates create new assertions and release candidates without rewriting old evidence.

## 4. Non-Goals

The first production release does not aim to be:

- a public search engine;
- an electronic lab notebook or LIMS replacement;
- a publisher-entitlement circumvention tool;
- an autonomous scientific decision maker;
- a universal knowledge graph for all scientific ontology work;
- a data warehouse for raw instrument data;
- a multi-region, internet-scale microservice platform;
- a system that treats LLM confidence as scientific validation;
- a replacement for data stewardship or expert review.

Native ELN/LIMS integrations may be added later. Initial internal sources should use documented file exports and APIs with stable contracts.

## 5. Vocabulary

| Term | Definition |
|---|---|
| Workspace | A lab or isolated research environment with its own membership, policy, configuration, and releases. |
| Scope | A versioned statement of research questions, inclusion/exclusion rules, date boundaries, languages, source strategy, and intended use. |
| Discovery run | An execution of a scope against specified connector versions and cursors. |
| Source observation | An immutable response or record obtained from one source at one time. |
| Assertion | A parsed claim made by a source about an identifier or metadata field. |
| Work | A canonical intellectual work, such as an article, preprint, dataset, protocol, or thesis. |
| Manifestation | A version or expression of a work, such as preprint v2, version of record, accepted manuscript, or supplementary file. |
| Asset | Immutable acquired bytes with checksum, MIME evidence, acquisition event, and rights decision. |
| Rendition | A parser-produced representation of an asset: text, sections, pages, tables, figures, and addressable spans. |
| Claim | A structured scientific assertion linked to one or more evidence spans and review state. |
| Template | A versioned projection specification that selects and formats claims for a use case such as a datasheet. |
| Export package | A self-describing, checksummed projection of a release. |
| Corpus release | An immutable approved set of works, renditions, claims, policies, and search projections. |
| Ingestion | Promotion of an approved corpus release into serving indexes. It does not mean discovery or acquisition. |

## 6. Non-Negotiable Design Principles

### P-1. Source-neutral core

No external catalogue defines the domain model. PubMed, Europe PMC, Crossref, OpenAlex, DataCite, local upload, and future lab systems are connectors with capabilities and policies.

### P-2. Preserve observations before interpretation

Store the immutable source response before parsing, merging, filtering, or normalising it. A parser fix must be replayable without contacting the source again.

### P-3. Identity is a graph and a decision

Identifiers and relations are assertions, not columns that magically agree. Strong identifiers drive automatic reconciliation. Conflicts are quarantined. Title similarity proposes a review; it never auto-merges.

### P-4. Bytes are immutable

An asset is addressed by a cryptographic digest. New downloads, corrected files, and parsed outputs create new records. They do not overwrite prior evidence.

### P-5. Provenance is queryable data

Every material value records who or what created it, from which inputs, with which code/config/model versions, at what time, under which workspace and policy.

### P-6. Rights before processing

The system determines and records whether it may acquire, store, parse, transfer to an external model, index, display, and export content. Those permissions can differ.

### P-7. Policy before scoring

Retrieval filters unauthorised content before lexical or vector scoring. The final result is filtered again. Counts and analytics follow the same policy.

### P-8. Claims, not rows

Scientific facts are represented as entities, experiments, conditions, measurements, and evidence-backed claims. Rows and spreadsheets are projections.

### P-9. LLM output is a proposal

Structured output is schema validated, evidence verified, and reviewable. An LLM cannot approve its own scientific result merely by reporting high confidence.

### P-10. Abstention has a reason

The system distinguishes `not_reported`, `not_searched`, `source_unavailable`, `parser_failed`, `ambiguous`, `conflicting`, `policy_redacted`, and `extractor_abstained`.

### P-11. Release, do not mutate

Serving corpora are immutable releases behind atomic aliases. Refresh creates a candidate release. Rollback changes an alias, not historical rows.

### P-12. Reproducibility includes selection

An extraction fingerprint includes the exact evidence selection, deterministic metadata, parser and selector versions, full prompt/schema/template content, model settings, and policy scope.

### P-13. Human decisions are first-class records

Include/exclude, merge/split, rights overrides, claim corrections, and approvals record actor, reason, timestamp, before/after value, and affected version.

### P-14. One authority per fact

Documentation, configuration, generated schemas, and source code must not offer competing definitions. Architecture decisions are recorded once and referenced elsewhere.

### P-15. Measure each stage independently

Discovery recall, identity precision, acquisition coverage, parse fidelity, extraction accuracy, retrieval quality, answer faithfulness, access leakage, latency, and cost are separate metrics.

## 7. Product-Level Invariants

These invariants should be encoded as database constraints, policy tests, or release gates:

1. No serving citation points to a mutable filesystem path.
2. No accepted claim lacks a valid evidence span unless explicitly marked as reviewer-authored interpretation.
3. No evidence span refers to a rendition whose asset is missing or checksum-invalid.
4. No asset enters processing without a recorded rights decision.
5. No automatic merge closes an unresolved strong-identifier contradiction.
6. No index contains material outside its release manifest.
7. No request can retrieve an item it cannot open.
8. No export is called complete until its manifest and checksums validate.
9. No failed or degraded discovery run silently becomes a release input.
10. No cache hit is accepted across a changed reproducibility fingerprint.
11. No workspace can observe another workspace's private source observations, assets, prompts, claims, or usage.
12. No old release changes when a source corrects or retracts a work; a successor release records the change.

## 8. Configuration Model

Each workspace has versioned configuration bundles:

```text
workspace profile
  + source policies
  + discovery scopes
  + connector credentials/restrictions
  + vocabularies and entity resolvers
  + extraction templates
  + retrieval profile
  + evaluation benchmark
  + retention and export policy
  + branding
```

Configuration is validated against JSON Schema or Pydantic models, stored as immutable versions, and referenced by ID from runs. Environment variables contain deployment secrets and endpoints, not scientific scope or pipeline behaviour.

## 9. Definition of Lab-Agnostic

The core is lab-agnostic only if all of the following are true:

- no organism, method, product, or date range is compiled into domain code;
- templates are workspace data with stable IDs and versions;
- connectors describe capabilities rather than being selected by a source switch statement;
- entity vocabularies and synonym sets are replaceable;
- retrieval prompts use workspace profiles and release metadata;
- evaluation benchmarks are workspace-scoped;
- policy can forbid external model transfer for selected collections;
- the same test fixture can create two isolated workspaces with different domains and prove zero leakage.
