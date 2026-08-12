# Lab AI Assistant: Clean-Slate Design and Migration Plan

**Status:** Proposed architecture
**Prepared from:** RLALab AI Research Assistant repository review
**Date:** 2026-08-12
**Audience:** Product owner, lab scientists, software engineers, data stewards, security reviewers, and operators

## Executive Decision

The successor should be a new product, tentatively named **Lab AI Assistant**. It should preserve the current internal-user experience, but it should not preserve the current paper-centric data model or the idea that PubMed is the centre of the system.

The central object in the new design is a **versioned, policy-controlled evidence graph**:

1. Source systems make assertions about a research work.
2. Acquired files are immutable assets with checksums and rights decisions.
3. Parsers create versioned renditions with addressable evidence spans.
4. Extractors propose structured claims linked to those spans.
5. Reviewers approve claims and corpus membership.
6. A corpus release projects approved material into search indexes.
7. Answers cite immutable evidence, not mutable rows or transient search results.

In this vocabulary, **ingestion means only the final promotion of an approved corpus release into serving indexes**. Discovery, acquisition, parsing, extraction, review, and export are separate stages with separate contracts.

The recommended implementation is a **modular monolith with independently scalable workers**, not an early microservice estate. The control plane uses PostgreSQL; immutable bytes and generated packages use S3-compatible object storage; search initially uses PostgreSQL full-text search and pgvector. FastAPI and Next.js remain appropriate.

## Why a New Project

The current repository contains valuable working components, tests, and hard-won lessons. It also contains incompatible architectural eras:

- a PubMed-first RAG application;
- a generic multi-source discovery pipeline;
- a publication acquisition ladder;
- a domain-specific datasheet workflow;
- local inventory and protocol ingestion;
- two job models and several cache formats;
- a global paper/chunk model used for records that are not papers.

Incrementally generalising those abstractions would keep their hidden assumptions. The migration therefore uses a strangler approach: build the new system alongside the old one, replay and compare real workloads, then cut over release by release.

## Reading Order

1. [Current-State Audit](00-current-state-audit.md) - what exists, what works, and where the design drifted.
2. [Product Principles](01-product-principles.md) - scope, users, terminology, and non-negotiable design rules.
3. [Target Architecture](02-target-architecture.md) - runtime architecture, modules, queues, deployment, and key decisions.
4. [Data Model and Provenance](03-data-model-and-provenance.md) - canonical entities, identity, access policy, lineage, and releases.
5. [Data Lifecycle](04-data-lifecycle.md) - discovery through refresh, including inputs, outputs, gates, retries, and human review.
6. [Connectors, Rights, and Security](05-connectors-rights-security.md) - connector SDK, legal acquisition, tenancy, secrets, and model transfer policy.
7. [Quality, Evaluation, and Operations](06-quality-evaluation-operations.md) - acceptance metrics, tests, observability, backup, and incident response.
8. [Migration Roadmap](07-migration-roadmap.md) - legacy mapping, phased delivery, shadow comparison, cutover, and rollback.
9. [Repository and Documentation Plan](08-repository-documentation-plan.md) - proposed source tree, documentation ownership, READMEs, and ADRs.
10. [Implementation Backlog](09-implementation-backlog.md) - ordered epics, acceptance criteria, decision log, and owner questions.

Documents 10-12 were added after a critical review of 00-09. They do not replace anything above;
they supply magnitudes, delivery realism, and the technology decisions that 00-09 leave open.

11. [Scale, Sizing, and Proportionality](10-scale-sizing-and-proportionality.md) - the measurements the plan never states, which controls are P0 at this scale and which are stageable, the cost of multi-workspace, release rebuild cost, re-acquisition volume, and the reviewer-hour budget.
12. [Delivery Model, Continuity, and Tripwires](11-delivery-model-and-continuity.md) - delivery profiles against real staffing, an MVP that ships twenty weeks earlier, the legacy freeze carve-out, the feature-parity register, abort tripwires, and product success in user terms.
13. [Technical Spikes and Open Choices](12-technical-spikes-and-open-choices.md) - the parsing stack and its licence gate, the evidence-span normalisation contract, embedding and index decisions, deployment substrate, the review-UI prototype, and the `mistakes.md` lessons not yet encoded.

## Scope of This Plan

This plan covers:

- literature and dataset discovery;
- metadata reconciliation and human adjudication;
- lawful automatic and assisted acquisition;
- parsing, OCR, table extraction, and structured claim extraction;
- reviewer correction and approval;
- reproducible exports;
- corpus release, indexing, retrieval, RAG, and citations;
- refresh, correction, retraction, and deletion propagation;
- internal users, roles, invitations, sessions, feedback, and future OIDC;
- multi-lab configuration without making data cross-lab by default;
- security, quality, operations, repository structure, and documentation.

It does not prescribe a commercial cloud provider, a particular external LLM provider, or institution-specific legal interpretations. Those are deployment policy decisions with explicit gates in this plan.

## Success Definition

The new project is ready for production when a lab can:

1. define a versioned research scope and source strategy;
2. reproduce every discovery run from immutable source responses;
3. explain why two records were or were not merged;
4. acquire content only through an approved access route;
5. trace every extracted value to a verified evidence span;
6. review, correct, approve, and version scientific claims;
7. export a self-describing, checksummed release package;
8. publish and roll back a corpus release without rewriting history;
9. retrieve only material the requesting user may access;
10. measure discovery recall, extraction quality, retrieval quality, answer faithfulness, latency, and cost;
11. recover the service and its evidence store from tested backups;
12. show an auditor the complete lineage from source request to answer citation.

All twelve criteria are architectural. None of them says a researcher is better served, and an
auditor is not a user of this system. The user-facing success measures are in
[Delivery Model §8](11-delivery-model-and-continuity.md) and carry equal weight: a system that
passes all twelve criteria above and that nobody prefers to the current one has failed.

## Immediate Actions Before Migration Work

1. Treat the tracked `backend/adminPass` file as a potential credential exposure. Rotate or revoke the credential, inspect access logs, remove the file from the tracked tree, and decide whether repository-history rewriting is required. Do not reproduce its contents in an issue or migration log. **Status as of 2026-08-12: still tracked in the repository. Not started.**
2. Freeze new architectural expansion in the current ingestion and datasheet layers. Continue only defect fixes, security work, and changes needed to export or compare data.
3. Snapshot the current database, object/cache directories, configuration, model identifiers, and evaluation results. Record checksums before cleanup.
4. Establish a named data steward and a named technical owner for the migration. Neither identity resolution nor rights policy can be safely ownerless.

## Source Standards Used by This Design

The design is informed by, but does not claim conformance with, the following primary specifications and service documentation:

- [W3C PROV-O](https://www.w3.org/TR/prov-o/) for provenance concepts.
- [RO-Crate](https://www.researchobject.org/ro-crate/) for self-describing research packages.
- [RFC 8493 BagIt](https://www.rfc-editor.org/info/rfc8493) for checksummed payload packaging.
- [OpenID Connect Core 1.0](https://openid.net/specs/openid-connect-core-1_0.html) for future institutional identity integration.
- [NCBI E-utilities usage guidance](https://www.ncbi.nlm.nih.gov/books/NBK25497/) for PubMed request identity, rate limits, and history-based batching.
- [Europe PMC REST API](https://europepmc.org/RestfulWebService) for publication metadata and open-access full text.
- [Crossref REST API](https://www.crossref.org/documentation/retrieve-metadata/rest-api/) and [DataCite APIs](https://support.datacite.org/docs/api) for DOI metadata from distinct registration ecosystems.
- [Unpaywall API](https://unpaywall.org/api) for open-access location resolution, subject to its current terms and limits.

These references belong in connector policies and architecture decisions. They are not a substitute for institutional legal review.
