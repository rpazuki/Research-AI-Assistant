# Repository and Documentation Plan

## 1. Repository Strategy

Create a separate repository for the successor. During migration, this repository remains the legacy source and evidence base. The new repository references a migration snapshot ID and commit, not a live relative import of legacy Python packages.

Use a monorepo because the product has one release train, shared contracts, and a small team.

## 2. Proposed Repository Tree

```text
lab-ai-assistant/
  README.md
  AGENTS.md
  CONTRIBUTING.md
  SECURITY.md
  CODEOWNERS
  LICENSE                       # project code licence decision
  pyproject.toml                # workspace tooling and shared Python config
  package.json                  # workspace scripts where useful
  docker-compose.yml
  .env.example
  .editorconfig
  .pre-commit-config.yaml
  .github/
    workflows/
    pull_request_template.md

  apps/
    web/
      README.md
      package.json
      src/
        app/
        components/
        features/
        lib/
        types/
      tests/

  services/
    api/
      README.md
      Dockerfile
      src/lab_assistant_api/
      tests/

  workers/
    discovery/
      README.md
      Dockerfile
    acquisition/
      README.md
      Dockerfile
    parsing/
      README.md
      Dockerfile
    extraction/
      README.md
      Dockerfile
    indexing/
      README.md
      Dockerfile
    evaluation/
      README.md
      Dockerfile

  packages/
    python/
      lab_assistant/
        contracts/
        domain/
        application/
        adapters/
          db/
          object_store/
          connectors/
          parsers/
          models/
          search/
        policy/
        provenance/
        evaluation/
      tests/
    typescript/
      api-client/
      ui/

  schemas/
    source-observation/
    rendition/
    claim/
    release-package/
    config/

  database/
    alembic.ini
    migrations/
    seeds/

  configs/
    examples/
      workspace.example.yaml
      scopes/
      templates/
      policies/

  benchmarks/
    README.md
    synthetic/
    manifests/                  # restricted data stored elsewhere by reference

  tests/
    contract/
    integration/
    e2e/
    fixtures/
    policy/
    migration/

  tools/
    cli/
    migration/
    package-validator/
    docs-check/

  infra/
    compose/
    environments/
    monitoring/
    backup/

  docs/
    README.md
    product/
    architecture/
      adr/
    data-contracts/
    connectors/
    extraction-templates/
    evaluation/
    security/
    operations/
      runbooks/
    migration/
    contributing/
```

Workers are entry-point/deployment directories, not duplicate business-logic packages. They import application handlers from `packages/python/lab_assistant`.

## 3. Dependency Rules

Enforce with import-lint/static checks:

```text
contracts -> no project dependency
domain -> contracts only
policy/provenance -> contracts + domain
application -> contracts + domain + policy/provenance interfaces
adapters -> application/domain interfaces + external SDKs
API/workers -> application composition root + adapters
web -> generated API client + UI package
```

Forbidden:

- domain importing FastAPI, SQLAlchemy, connector SDKs, object storage, or model SDKs;
- connectors writing database tables directly;
- parsers creating search chunks;
- extraction code publishing a release;
- API routes containing pipeline logic;
- frontend reimplementing rights or scientific state rules;
- workers importing code from each other.

## 4. Root README Contract

The root `README.md` should be short and operationally true. It includes:

1. one-paragraph product definition and internal-only warning;
2. architecture diagram and links to authoritative docs;
3. prerequisites with exact supported versions;
4. a tested quick start using example/fake providers;
5. exact commands for lint, type check, tests, and local server;
6. environment/config loading order;
7. links for first workspace, first discovery run, first release, and operations;
8. current project status and supported deployment profile;
9. security reporting link;
10. licence status.

It must not contain copied database schema, stale source lists, long future plans, or duplicated ADR prose.

Every command in the quick start runs in CI through a documentation smoke test.

## 5. Documentation Information Architecture

### 5.1 `docs/README.md`

The documentation index maps audiences to authoritative pages:

| Audience | Start here |
|---|---|
| Scientist/researcher | Product guide, asking questions, citations, collections, review. |
| Data steward | Scope, identity decisions, acquisition, rights, templates, releases. |
| Developer | Architecture, data contracts, local setup, testing, contributing. |
| Connector owner | Connector SDK, source policy, fixtures, runbook. |
| Operator | Deployment, monitoring, backup, runbooks, incidents. |
| Security/privacy reviewer | Threat model, data inventory, policy, model transfer. |

### 5.2 Product docs

```text
product/overview.md
product/user-roles.md
product/collections-and-releases.md
product/asking-and-citations.md
product/review-workflows.md
product/export-guide.md
```

These describe supported user behaviour, not implementation details.

### 5.3 Architecture docs

```text
architecture/system-context.md
architecture/containers-and-deployment.md
architecture/modules-and-dependencies.md
architecture/task-orchestration.md
architecture/search-and-rag.md
architecture/provenance.md
architecture/adr/NNNN-title.md
```

Diagrams should be generated from text-based sources where possible and verified in docs CI.

### 5.4 Data contracts

```text
data-contracts/terminology.md
data-contracts/source-observations.md
data-contracts/work-identity.md
data-contracts/assets-and-rights.md
data-contracts/renditions-and-spans.md
data-contracts/entities-experiments-claims.md
data-contracts/corpus-release.md
data-contracts/export-package.md
data-contracts/state-and-error-taxonomy.md
```

Each contract links to generated JSON Schema/OpenAPI and database constraints. Handwritten examples are validated in CI.

### 5.5 Connector docs

One page per connector using the standard template from [Connectors, Rights, and Security](05-connectors-rights-security.md). A source matrix links current official terms and technical docs. Review dates and owners are mandatory.

### 5.6 Template docs

Each production extraction template documents:

- scientific purpose and exclusions;
- template ID/version and compatibility;
- entities/claims/cardinality;
- evidence standard;
- unit and controlled-vocabulary rules;
- abstention semantics;
- benchmark and quality thresholds;
- reviewer instructions;
- export projections and data dictionary;
- change history.

No domain template is embedded as an unexplained default in core code.

### 5.7 Operations and runbooks

Operations pages describe normal deployment and monitoring. Runbooks describe time-sensitive recovery. Commands are versioned, tested in a safe environment, and avoid copying secrets.

## 6. Architecture Decision Records

Use one ADR per durable decision:

```markdown
# ADR-NNNN: Short title

- Status: proposed | accepted | superseded | rejected
- Date: YYYY-MM-DD
- Owners: names/roles
- Supersedes: ADR links

## Context
## Decision
## Consequences
## Alternatives Considered
## Validation / Revisit Trigger
## References
```

ADRs are immutable after acceptance except status/link corrections. A changed decision creates a superseding ADR. Plans and READMEs link to ADRs rather than restating their rationale.

Initial ADR set:

1. source-neutral evidence graph;
2. modular monolith and worker boundaries;
3. PostgreSQL control plane/task queue/search;
4. content-addressed object storage;
5. workspace isolation and policy model;
6. identity reconciliation rules;
7. rendition/evidence addressing;
8. claim/review model;
9. corpus releases and search aliases;
10. external model data-transfer policy;
11. export package profile;
12. authentication now and OIDC migration path.

## 7. Status and Version Labels

Every non-evergreen design or guide page begins with:

```text
Status: proposed | active | deprecated | historical
Applies to: product version or component versions
Owner: team/role
Last verified: YYYY-MM-DD
Next review: YYYY-MM-DD where policy-sensitive
Source of truth: code/schema/ADR/config link
```

Plans have explicit completion state. Historical plans move to `docs/archive/` and cannot be mistaken for operations guidance.

## 8. Agent Guidance

Keep one concise root `AGENTS.md` as the repository agent entry point. It should contain:

- project purpose and internal-only boundary;
- required reading links;
- architectural dependency rules;
- common commands;
- editing/testing/security rules;
- pointers to current ADRs and data contracts.

Do not duplicate the entire architecture in both `AGENTS.md` and `CLAUDE.md`. If another tool-specific file is required, make it a short pointer or generate it from a common source. CI can verify that tool guidance links to the same authority.

## 9. Configuration Documentation

### 9.1 Loading order

Document one deterministic order, for example:

```text
compiled defaults
< versioned deployment config file
< workspace config records
< environment variables for deployment endpoints/secrets only
< explicit CLI flags for one invocation
```

The exact order is an ADR. Startup logs show safe config source IDs and checksums, not secret values.

That ADR must reconcile this layered order with the configuration model the legacy system already
learned the hard way (CLAUDE.md §14): one variable names the scenario, the secrets file holds no
hostnames, ports, or URLs, each address has exactly one owner, and no password is duplicated into a
`DATABASE_URL` in an address file. Those rules exist because breaking them produced a specific
recurring failure - a host process handed a Compose service name. Discarding them because the
surrounding architecture changed would repeat the pattern this plan criticises elsewhere. See
[Delivery Model §6](11-delivery-model-and-continuity.md).

### 9.2 Example configuration

- all referenced example paths exist;
- examples validate against current schema in CI;
- examples use fake endpoints/credentials;
- domain examples live under workspace examples, not global defaults;
- deprecated keys fail with a useful migration message after a defined period;
- `--print-effective-config` emits redacted canonical config and provenance.

## 10. API and Schema Documentation

- OpenAPI is generated from the API build and published with each version;
- Python/TypeScript clients are generated or validated against it;
- domain JSON Schemas have stable IDs and semantic versions;
- database migrations include data migration and rollback notes;
- event schemas are versioned and backward compatibility tested;
- example payloads are machine validated;
- breaking changes require ADR/release notes and migration guide.

## 11. Developer Guidelines

`CONTRIBUTING.md` should define:

- local environment and supported tool versions;
- branch/PR/review expectations;
- module dependency boundaries;
- database migration workflow;
- how to add a connector/parser/template/provider;
- fixture provenance/redaction and live-test rules;
- test levels and required commands;
- documentation requirements;
- security and secret handling;
- performance/cost considerations;
- definition of done.

Definition of done for a lifecycle feature:

- typed contract and state/outcome taxonomy;
- domain invariants and authorisation;
- idempotency/retry semantics;
- provenance/audit events;
- metrics and operational errors;
- unit/contract/integration tests;
- user and operator documentation;
- migration/backward compatibility where applicable;
- threat/rights review for new data movement;
- no unexplained config or generated-schema drift.

## 12. Review Ownership

Use CODEOWNERS or equivalent:

| Area | Required review |
|---|---|
| Domain/data contracts | Technical owner + data steward. |
| Rights/security/policy | Security/privacy owner + data steward. |
| Connector | Connector owner + platform reviewer. |
| Parser/extraction template | Data/extraction engineer + scientific reviewer. |
| Auth/workspace policy | Security reviewer. |
| Database migration | Backend owner + operator. |
| Release/evaluation threshold | Product/scientific owner. |
| Runbook | Operator who exercises it. |

Small-team staffing may combine people, but the review perspectives remain explicit.

## 13. Documentation CI

CI checks:

- broken internal and external links, with allowlisted transient exceptions;
- missing status/owner headers where required;
- invalid Mermaid syntax;
- README commands through smoke scripts;
- example configs against schema;
- example API/event/export payloads against schema;
- OpenAPI/generated client drift;
- ADR numbering/status/supersession integrity;
- orphan docs not linked from the index;
- duplicate authoritative headings/terms where a generated reference should be used;
- secret scanning across docs and fixtures.

## 14. Release Notes and Change Communication

Each application release states:

- user-visible changes;
- schema/migration actions;
- connector/parser/model/template changes;
- policy/terms implications;
- reproducibility impact and cache invalidation;
- required reparse/re-extract/reindex actions;
- deprecations and removal dates;
- rollback compatibility;
- known issues.

Corpus releases have separate scientific release reports. Do not mix application code versions and corpus versions.

## 15. Cleaning Up the Current Documentation

During Phase 0, do not rewrite every legacy guide. Add a clear banner to active entry points:

```text
This repository is the legacy RLALab implementation. The successor design and
migration plan are in migration/. Existing plans may describe historical or
partially implemented behaviour; verify against code and tests.
```

Then:

1. mark each current doc active, historical, or superseded;
2. fix dangerous operational inaccuracies such as nonexistent config paths;
3. avoid duplicating the new architecture into legacy root guidance;
4. archive plans only after snapshot and owner approval;
5. preserve `mistakes.md` as migration evidence, then turn its durable lessons into ADRs/tests in the new project. The lesson-by-lesson mapping, including the four not yet reflected anywhere in this plan, is in [Spikes §9](12-technical-spikes-and-open-choices.md). Of those, the fixture-keyed-fake rule matters most: this plan's deterministic test strategy rests entirely on fake connectors and fake model providers, and a fake that answers an unmatched request with a default makes the whole end-to-end suite pass while proving nothing.
