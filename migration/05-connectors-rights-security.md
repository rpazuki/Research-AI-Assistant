# Connectors, Rights, and Security

## 1. Connector Architecture

A connector is a versioned adapter with declared capabilities and policy, not a conditional branch in a monolithic ingestion script.

### 1.1 Capability contract

```python
class ConnectorCapabilities(BaseModel):
    connector_id: str
    connector_version: str
    resource_kinds: set[str]
    operations: set[Literal["discover", "resolve", "acquire", "delta"]]
    query_schema_id: str | None
    output_schema_id: str
    pagination_modes: set[str]
    supports_bulk_snapshot: bool
    supports_incremental_cursor: bool
    content_formats: set[str]
    identifier_schemes: set[str]
    terms_url: str
    rate_policy: RatePolicy
    data_classification: str
```

```python
class SourceConnector(Protocol):
    capabilities: ConnectorCapabilities

    async def compile_query(self, scope: ScopeVersion) -> CompiledQuery: ...
    async def discover(self, request: DiscoveryRequest) -> AsyncIterator[RawPage]: ...
    async def resolve(self, identifiers: list[Identifier]) -> AsyncIterator[RawPage]: ...
    async def acquire(self, request: AcquisitionRequest) -> RawAcquisition: ...
    async def changes(self, cursor: Cursor) -> AsyncIterator[RawPage]: ...
```

Not every connector implements every operation. Unsupported operations are absent capabilities, not runtime surprises.

### 1.2 Connector package requirements

Each connector includes:

- capability manifest;
- query compiler and validator;
- response parser with versioned fixtures;
- error/outcome mapper;
- pagination and cursor implementation;
- rate/identity/contact policy;
- terms and licence notes with review date;
- secrets required by name, never value;
- deterministic contract tests;
- opt-in live smoke tests;
- fixture provenance and redaction statement;
- operational dashboard dimensions;
- owner and deprecation policy.

### 1.3 Raw-response rule

Connector code must hand the raw response envelope to immutable storage before domain parsing. For streaming or very large responses, it can stream to a quarantine object, checksum it, register it, and then parse from the registered object.

The raw layer must preserve enough information to replay while redacting credentials and prohibited personal data. It should not store session cookies, bearer tokens, API keys, or full sensitive request URLs.

## 2. Initial Source Portfolio

The clean-slate product should begin with a deliberate portfolio rather than a privileged central source.

| Connector | Primary role | Strength | Important limitation |
|---|---|---|---|
| PubMed/NCBI | Biomedical discovery and identifiers | Curated biomedical indexing, MeSH, PMID | Not a universal DOI registry; abstract/full-text rights vary. |
| Europe PMC | Biomedical discovery and OA content | Broad life-science records and OA XML/full text | Full text is limited to available collections/licences. |
| Crossref | DOI metadata and relations | Broad publisher metadata and DOI relations | Metadata completeness varies; not all DOIs are Crossref. |
| DataCite | Dataset/software/report DOI metadata | Distinguishes non-publication research outputs | Search semantics differ from literature databases. |
| OpenAlex | Broad discovery/enrichment | Coverage across scholarly graph | Aggregated fields require source-aware validation. |
| Unpaywall | OA-location resolution | Useful lawful access routes | It resolves locations; it is not the canonical work identity source. |
| bioRxiv/medRxiv | Preprint versions and content | Versioned preprints | Must link versions and later versions of record without merging them. |
| Local upload | Internal or authorised files | Essential assisted route | Requires malware, identity, sensitivity, and rights review. |
| Local tabular import | Inventories and curated datasets | Structured values and stable source context | Must preserve rows/cells/schema; never flatten the first N rows into prose. |
| Local protocol import | Internal methods | High lab relevance | Often sensitive and group-restricted. |

Optional enrichment connectors can include ORCID for researcher identity and ROR for institutions. They should enrich assertions, not make author-name strings globally unique.

NCBI requests must follow its current identification, batching, and rate guidance; Crossref recommends identified/polite access and response caching; Unpaywall requires request identity and publishes limits. Connector policy should link to the current official guidance rather than copying values permanently into architecture prose.

## 3. Connector Selection Rules

1. Choose sources by scope coverage and field authority, not familiarity.
2. Use multiple discovery sources when the benchmark proves one source misses relevant work.
3. Define field-specific resolution policy: for example, a DOI registry may outrank an aggregator for registration metadata while a full-text asset outranks both for reported experimental values.
4. Keep source disagreement visible.
5. Prefer bulk snapshots/change feeds when terms and volume make them safer and more reproducible than repeated API calls.
6. Record connector degradation in release provenance.
7. A new connector cannot enter production until contract tests, live smoke tests, terms review, rate policy, and fixture redaction pass.

## 4. Rights Policy Model

Rights are not one `license` string. The policy evaluates an action on a subject in a workspace context.

### 4.1 Actions

```text
discover_metadata
store_metadata
store_content
process_local
send_to_external_model
create_embeddings_local
create_embeddings_external
display_excerpt
display_full_content
share_with_group
export_metadata
export_claims
export_evidence
export_content
retain
delete
```

### 4.2 Inputs

- source terms and API licence;
- asset/content licence expression;
- access route and entitlement;
- workspace institution and jurisdiction;
- content type and publication status;
- user-supplied acknowledgement;
- sensitivity classification;
- intended use;
- external processor and region;
- retention period;
- institutional policy version.

### 4.3 Decision outputs

- allow, deny, or require review;
- allowed actions;
- conditions and restricted groups;
- evidence for the decision;
- policy/rule version;
- expiry or review date;
- decision actor;
- required deletion/retention behaviour.

Do not claim the software decides copyright law. It executes institution-approved rules and preserves the evidence and human decision.

## 5. Access and Content Handling

### 5.1 Acquisition boundaries

Allowed automated routes are explicit APIs, repositories, TDM endpoints, bulk feeds, and direct file URLs permitted by policy. The system must not:

- automate a user's institutional SSO session;
- retain browser cookies for workers;
- solve CAPTCHAs;
- bypass robots or anti-bot controls;
- scrape publisher pages when an approved route is absent;
- interpret a successful HTTP response as an unrestricted licence.

### 5.2 User-assisted upload

The user attests the access basis using deployment-approved options. This is an input to a rights decision, not a blanket waiver. Uploaded content follows quarantine, malware scanning, identity verification, policy assignment, and retention rules.

### 5.3 Excerpts and citations

An answer may be allowed to cite metadata while not displaying full content. Evidence display policy should support:

- full evidence span;
- bounded excerpt;
- locator only;
- metadata citation only;
- content hidden from the requesting user.

The generation model must not receive content the user or provider is not permitted to process.

## 6. Multi-Workspace Isolation

### 6.1 Isolation default

Every private object is workspace scoped. Public metadata may be physically deduplicated later, but logical source observations, identity decisions, assets, claims, prompts, evaluations, chats, and usage remain isolated unless a deliberate sharing policy exists.

### 6.2 Enforcement layers

1. API authorisation establishes workspace and capabilities.
2. Repository methods require workspace ID, never an optional filter.
3. PostgreSQL row-level security is recommended as defence in depth for principal workspace tables.
4. Object keys are accessed through a server-side authorisation check or short-lived signed URL.
5. Search projections carry workspace/release scope and policy grants.
6. Retrieval applies policy in candidate SQL before ranking and again after ranking.
7. Cache and idempotency keys include workspace/policy scope.
8. Logs and metrics avoid raw content and sensitive query labels.
9. Tests create two workspaces and actively attempt inference through search, counts, errors, timing, export, and object IDs.

Do not rely on UUID unpredictability as access control.

## 7. Authentication and Session Security

### Initial mode

- invitation or admin provisioning;
- no anonymous access;
- modern adaptive password hashing such as Argon2id, with migration from existing hashes as users log in;
- short-lived access token with issuer, audience, subject, auth epoch, and token ID;
- secure, `httpOnly`, `SameSite` cookie at the web tier;
- CSRF protection for cookie-authenticated state changes;
- refresh/session rotation or a deliberately short re-login policy;
- rate limiting and audit for login and invitation operations;
- forced reset and global token revocation after migration/security incidents.

### OIDC readiness

Model external identities separately:

```text
user_external_identities(user_id, issuer, subject, email_at_link, linked_at)
```

Do not key users by email from an identity provider. OIDC `issuer + subject` is the stable pair. Account linking requires an authenticated and audited flow.

## 8. Secrets and Credentials

### 8.1 Rules

- no secret values in Git, Docker images, config files, logs, task payloads, URLs, or exception traces;
- local development uses ignored environment files or a developer secret tool;
- production uses an institution-approved secret manager and workload identity where available;
- each connector has a distinct credential and minimal scope;
- credentials record owner, purpose, creation, rotation target, and last use;
- rotation does not require rebuilding the application image;
- test fixtures use impossible fake credentials;
- CI runs secret scanning on the full diff and repository baseline.

### 8.2 Immediate legacy incident procedure

For `backend/adminPass`:

1. Open an internal security incident without including the value.
2. Determine the system/account associated with it.
3. Rotate/revoke before removing evidence needed for investigation.
4. Search Git history, build artefacts, deployment bundles, logs, and backups for exposure.
5. Review authentication logs from the earliest known commit containing it.
6. Remove it from the current tree and add a targeted ignore rule if a local runtime file is still required.
7. Decide whether to rewrite Git history based on repository distribution and institutional process.
8. Invalidate sessions or force resets if the credential could grant application access.
9. Document closure, residual risk, and prevention controls.

## 9. External Model and Embedding Policy

Before any content leaves the controlled environment, the policy engine evaluates:

- workspace and collection classification;
- content licence and access route;
- personal/confidential information;
- provider, endpoint, region, retention, training-use terms, and contract;
- user and intended action;
- prompt/evidence minimum necessary;
- logging and model-response retention.

Provider adapters declare:

- data retention/training properties configured for the deployment;
- supported regions and endpoints;
- request limits and timeout semantics;
- model/revision identifiers;
- deterministic/seed support;
- structured output and citation capabilities;
- batch-job lifecycle;
- retryable error classes;
- content logging/redaction controls.

Restricted content falls back to local processing or is not processed. The UI should explain the policy outcome without exposing confidential policy internals.

## 10. Untrusted Document Content

Research documents are untrusted input. They may contain malicious PDFs, spreadsheet formulas, links, embedded files, or text that attempts to instruct the model.

Controls:

- quarantine and malware scan all uploaded/downloaded files;
- parse in a sandboxed worker with CPU, memory, time, file, and network limits;
- disable parser network access;
- reject dangerous archive paths, decompression bombs, and excessive nesting;
- sanitise HTML and active document content;
- neutralise spreadsheet formula injection on export;
- never execute macros or embedded code;
- label retrieved text to the model as untrusted evidence;
- system prompts state that instructions found in evidence are content, not commands;
- tools are not exposed to the generation model during evidence synthesis unless separately authorised;
- validate returned citations against supplied handles;
- red-team prompt injection in documents and metadata.

## 11. Network Security

- TLS for every network hop outside a trusted local development bridge;
- outbound allowlist for worker pools when feasible;
- DNS and redirect validation to prevent SSRF;
- reject private, loopback, link-local, metadata-service, and disallowed schemes for user-supplied URLs;
- revalidate every redirect target;
- cap redirects, response size, and transfer duration;
- connect/read/total timeouts per connector;
- no credentials forwarded across host redirects;
- signed object links short lived and scoped to one object/action;
- database connections use TLS and least-privilege roles;
- API, migration, read-only analytics, and worker roles are separated.

## 12. Audit and Privacy

Audit events cover:

- login/session/invitation and policy changes;
- source queries when not too sensitive, otherwise a protected fingerprint;
- acquisition attempts and user-assisted attestations;
- asset view/download/export;
- identity and relevance decisions;
- claim review and correction;
- release approval/publication/rollback;
- admin and break-glass access;
- secret/credential configuration changes by reference;
- failed authorisation attempts.

Do not put source content, passwords, tokens, full prompts, or sensitive queries in ordinary logs. Protected model envelopes and raw requests have explicit retention and access policy.

Privacy work before production includes:

- data inventory and classification;
- retention schedule;
- data-processing agreements for external providers;
- user notice for chat and usage telemetry;
- subject-access/deletion process where applicable;
- policy for author names and other public research metadata;
- review of internal protocol/inventory personal or confidential data.

## 13. Threat Model Baseline

| Threat | Primary controls |
|---|---|
| Cross-workspace data leakage | Required workspace keys, RLS, policy-first retrieval, isolation tests. |
| Stolen user session | Secure cookies, short tokens, auth epoch, CSRF, login audit, revocation. |
| Secret committed to source | Secret manager, scanning, rotation runbook, no runtime secret files. |
| Malicious PDF/document | Quarantine, malware scan, sandboxed parser, no worker network. |
| SSRF through acquisition URL | Allowlist, IP/scheme validation, redirect revalidation, limits. |
| Prompt injection in source | Evidence labelling, no model tools, citation validation, red-team tests. |
| Unauthorised external model transfer | Policy gate at task creation and provider call, local fallback. |
| Poisoned source metadata | Immutable observations, source provenance, conflict detection, review. |
| Tampered asset/export | SHA-256 content addressing, package manifests, validation on use. |
| Worker replay/duplicate side effect | Idempotency fingerprints, leases, transactional outbox. |
| Reviewer account misuse | Least privilege, decision audit, optional double review, anomaly alerts. |
| Destructive admin action | Soft state transitions, approval for purge, backup, immutable releases. |

The implementation phase should produce a formal data-flow threat model and review it at each release boundary.

## 14. Security Release Gates

Before first production cutover:

- legacy potential credential incident is closed;
- secret scan is clean;
- dependency and container scans have no unaccepted critical/high findings;
- authorisation matrix tests pass, including two-workspace negative tests;
- object access and signed URL tests pass;
- upload/acquisition malware and SSRF tests pass;
- external model policy tests pass;
- prompt-injection and citation-forgery tests pass;
- backup encryption and restore are tested;
- audit retention and access are approved;
- incident, credential rotation, rights takedown, and emergency release runbooks have been exercised.

## 15. Connector and Policy Documentation

Every production connector page should show:

```text
Owner
Version and last review date
Supported capabilities and resource types
Authoritative/non-authoritative fields
Query semantics and examples
Pagination/cursor behaviour
Rate/request identity policy
Terms/licence links and approved uses
Required credentials
Raw response and fixture policy
Error/outcome mapping
Known coverage limitations
Operational metrics and alerts
Change/deprecation procedure
```

Copied rate-limit numbers become stale. Link official primary documentation and keep runtime values in versioned connector policy.

## 16. Primary References

- [NCBI E-utilities usage guidelines](https://www.ncbi.nlm.nih.gov/books/NBK25497/)
- [Europe PMC REST API](https://europepmc.org/RestfulWebService)
- [Crossref REST API](https://www.crossref.org/documentation/retrieve-metadata/rest-api/)
- [Crossref API access and authentication](https://www.crossref.org/documentation/retrieve-metadata/rest-api/access-and-authentication/)
- [DataCite API guide](https://support.datacite.org/docs/api)
- [Unpaywall API](https://unpaywall.org/api)
- [OpenID Connect Core 1.0](https://openid.net/specs/openid-connect-core-1_0.html)
- [W3C PROV-O](https://www.w3.org/TR/prov-o/)

Service terms and technical guidance can change. Connector owners must re-review them on a scheduled basis and before material volume changes.
