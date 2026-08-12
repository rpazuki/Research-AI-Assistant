# Scale, Sizing, and Proportionality

Status: proposed
Applies to: the whole migration plan
Owner: technical owner + product owner
Last verified: 2026-08-12

## 1. Why This Document Exists

Documents 00-09 specify mechanisms with great precision and never state a magnitude. There is
no figure anywhere for corpus size, asset bytes, chunk count, query rate, embedding throughput,
reviewer hours, or budget. Every architectural choice that the plan presents as settled -
PostgreSQL instead of OpenSearch, pgvector instead of a vector service, a PostgreSQL task DAG
instead of a workflow engine, one release rebuild per publication - is a scale judgement made
without the scale.

The one quantity the plan does report is from the audit: the cumulative cache held **13,221
document records** across **13,063 distinct document IDs**, with **4,040 PMIDs** appearing under
more than one identity. For a target population of **50-100 internal users**, that is a small
system. Most of the control machinery in this plan is drawn from regulated-data and
public-service practice. Some of it is correct at this scale. Some of it is not, and the plan
never separates the two.

This document does three things:

1. names the measurements that must exist before Phase 1 exits;
2. right-sizes each control against measured scale, so P0 means P0;
3. states the costs the owner needs in order to answer the deferred decisions in
   [Implementation Backlog §7](09-implementation-backlog.md).

## 2. Measurements Required Before Phase 1 Exit

None of these are estimates to be guessed in a planning meeting. They are measurements of the
legacy system taken during the Phase 0 snapshot, and they belong in the signed inventory.

| # | Quantity | Why it decides something | Source |
|---|---|---|---|
| 1 | Distinct canonical works after reconciliation | Postgres FTS/pgvector viability; release rebuild time | Legacy identity build (Roadmap §5) |
| 2 | Assets held, count and total bytes, by media type | Object-store sizing, encryption, egress, backup | Acquisition cache inventory |
| 3 | Assets whose original bytes plus checksum plus route are recoverable | Determines re-acquisition volume (§6) | Legacy asset classification A-E |
| 4 | Chunks at the current chunking profile, and projected under the new profile | Embedding compute, index size, index build time | `document_chunks` count |
| 5 | Total embedding compute for one full corpus pass, on the target hardware | Release publish latency; whether GPU is required | Timed benchmark run |
| 6 | Peak and mean concurrent users; queries per day | API sizing, LLM budget, SSE connection limits | Legacy chat message table |
| 7 | Claims per work in the current datasheet, and target predicates per template | Review throughput budget (§7) | Datasheet row/claim inspection |
| 8 | Discovery run volume: source requests per run, raw response bytes per run | Raw-observation storage growth, rate-limit wall clock | Discovery run logs |
| 9 | Current retrieval and answer benchmark values | Every "no regression" gate is undefined until these exist | `evaluation/` run |
| 10 | Monthly external model spend, by stage | Extraction budget gates; batch-versus-online decision | Provider billing |

**Gate:** [Backlog E1](09-implementation-backlog.md) does not pass until rows 1-9 have values in
the migration decision log. A plan that promises "no unexplained regression" against an unmeasured
baseline promises nothing.

## 3. The Proportionality Rule

> A control is P0 when its absence can cause an unrecoverable loss - of data, of legal standing,
> of scientific validity, or of the ability to explain a published answer. A control is stageable
> when its absence causes extra work that is detectable and repairable.

The backlog currently marks E1-E7 and E10-E13 as P0, which is eleven of thirteen epics. That is
not a priority ordering; it is a list. Applying the rule above splits them.

### 3.1 Genuinely unrecoverable, therefore P0 at any scale

| Control | Unrecoverable loss if absent |
|---|---|
| Raw source response stored before parsing | A parser fix cannot be replayed; the observation is gone. |
| Content-addressed immutable assets | Citation targets drift; evidence cannot be re-verified. |
| Rights decision recorded before processing | Legal exposure that no later work repairs. |
| Evidence-span verification against the rendition | The core scientific claim of the product fails silently. |
| Strong-identifier-only automatic merge | Merged distinct works cannot be reliably unmerged later. |
| Workspace/policy key on every domain row | Retrofitting tenancy onto populated tables is a rewrite. |
| Append-only audit of human decisions | The decision record cannot be reconstructed. |
| Release immutability and alias switching | Published answers become unreproducible. |
| Task idempotency fingerprints | Duplicate side effects corrupt counts and cost. |

These stay P0 whether the corpus is 13k works or 13M. They are cheap to build in from the start
and expensive-to-impossible to add afterwards.

### 3.2 Real, but stageable at measured scale

| Control | Plan position | Proportionate first position | Trigger to upgrade |
|---|---|---|---|
| PostgreSQL row-level security | "recommended defence in depth" (05 §6.2) | Repository-level workspace enforcement plus the two-workspace negative suite; RLS behind a flag, enabled when a second workspace holds real data | Second workspace onboarded |
| Malware scanning | Required gate on every asset (04 §7) | Required for user uploads and non-allowlisted hosts; skippable for OA repository fetches with recorded exception | Any upload path opened beyond named stewards |
| Sandboxed parser workers with no network | Required (05 §10) | Container-level resource and network limits from the start; full seccomp/sandbox profile staged | First externally-sourced PDF corpus beyond OA |
| Double review and adjudication | Policy option (04 §10) | Single review with a measured correction rate; double review only for predicates whose correction rate exceeds threshold | Correction rate above template threshold |
| Quarterly production-like DR drill | Required (06 §9) | Monthly synthetic restore; production-like drill once before cutover, then semi-annually | Corpus becomes irreplaceable by re-acquisition |
| RO-Crate / BagIt strict conformance | Package profile (04 §11) | Documented "inspired-by" profile plus a checksum validator; certification deferred | External deposit or publication requirement |
| Six separate worker deployments | Worker topology (02 §6) | Two deployments - network-bound and compute-bound - reading the same durable queues, with per-stage concurrency caps | Measured contention or divergent scaling needs |
| Cost/budget engine per workspace | Required (06 §11) | Per-run token and request accounting plus a hard monthly cap at the provider | More than one workspace with separate budgets |
| Full OpenTelemetry trace fabric | Required (06 §6.3) | Structured logs with correlation IDs plus stage metrics; tracing when a latency problem resists logs | Unattributable latency incident |

Staging is not deletion. Each row keeps its schema and its gate; only the enforcement depth moves.
The worker-topology row in particular should be read together with [mistakes.md's](../mistakes.md)
lesson that a long provider call in a shared worker starves the other queue - the fix is durable
per-stage concurrency control, which is P0, not six deployment units, which is not.

### 3.3 Costs the owner has not been shown

[Backlog §7](09-implementation-backlog.md) asks the owner to decide "one workspace per deployment
or shared multi-workspace deployment" and recommends "build shared-safe". The owner cannot decide
this without the cost. It is:

- a required `workspace_id` on roughly every domain table, and on every index and constraint;
- workspace scope in every cache key, idempotency key, and object-encryption scope, which
  forbids cross-workspace asset deduplication (03 §8.5) and therefore re-acquires and re-parses
  the same public paper per workspace;
- workspace scope in search projections, meaning per-workspace embedding and index storage;
- the two-workspace negative test suite across API, search, counts, errors, timing, export,
  and object IDs (05 §6.2), maintained forever;
- RLS policy authorship and its migration burden;
- one more dimension in every metric, log, and dashboard.

Estimate: this is not a column. It is a persistent tax on every subsequent epic, plausibly
10-20 percent of total build effort and a permanent multiplier on storage and compute for shared
public content.

The counter-position deserves a fair hearing: **single-tenant now, tenancy-ready schema.** Carry
`workspace_id` on domain tables with a single seeded workspace, keep repository signatures
workspace-scoped, and defer RLS, per-workspace encryption scoping, the isolation suite, and the
no-shared-cache rule until a second lab exists. The irreversible part - the column and the
repository signature - is preserved. The expensive part is bought when it is needed.

Recommendation: adopt tenancy-ready single-tenant unless a named second lab has committed. Record
the choice as an ADR with this cost table attached.

## 4. Search Substrate Sizing

The plan chooses PostgreSQL FTS plus pgvector and defers OpenSearch until "corpus size, query
latency, or ranking features demonstrate a need" (02 §8.1). At the measured legacy scale the
choice is clearly right. State the thresholds so the deferral is testable rather than rhetorical:

| Signal | Suggested re-evaluation threshold |
|---|---|
| Chunk rows in one active release | above ~5M |
| p95 vector search latency at target `top_k` | above 500 ms after index tuning |
| Index build time per release publish | above the acceptable publish window (§5) |
| Ranking features required beyond RRF plus a cross-encoder | any learned-sparse or field-boost requirement |
| Concurrent search queries | above database connection pool capacity at target latency |

## 5. Release Rebuild Cost

The release model requires that publishing builds new projections and switches an alias
(04 §13, 03 §13.4). The plan gives a rollback SLO of "under 15 minutes by alias switch" (06 §7)
and no build SLO at all. Build is the expensive half.

Per release publication the system must, for each changed item: chunk, embed, write lexical
projections, write vector rows, and build vector indexes. Two consequences the plan does not state:

1. **Storage doubles during publication.** Old and new projections coexist until the alias
   switches and the old projection is garbage-collected. Object and database sizing must budget
   for at least two concurrent projections per active embedding profile.
2. **Full rebuild is not the normal case and must not be.** A release whose parent shares most
   items should copy unchanged projection rows by content digest and only recompute the diff.
   [Data Lifecycle §13](04-data-lifecycle.md) defines chunk identity from release item, rendition
   digest, node set, chunker profile, and content digest - which makes incremental projection
   possible. The plan never says it is required. It is: without it, publish time grows with corpus
   size rather than with change size, and frequent releases become impractical.

**Add to E10 acceptance:** a release whose diff against its parent is N items builds projections in
time proportional to N, not to total corpus size, and this is proved by a test comparing a
full-build release against a one-item-diff release.

## 6. Re-Acquisition Volume

The mapping table (07 §4) sends legacy `extracted full-text JSON` to "reparse original asset for
approved use", and the audit records (H-4, H-5) that the acquisition cache is run-local, keyed by
a DOI-derived filename, and lacks asset manifests including source URL, checksum, and rights basis.

The unstated consequence: an unknown fraction of already-acquired content will be classified B
(usable with review) or D (not fully verifiable) and will need **re-fetching from publishers and
repositories**, subject to per-host rate limits, over an unbudgeted wall-clock period.

Required before Phase 3 planning is credible:

- count of legacy assets whose bytes exist and whose checksum can be computed;
- of those, how many have sufficient route and rights evidence to import as class A;
- the re-acquisition list size, split by route class;
- the wall-clock estimate for re-acquisition at policy-compliant rates, per host;
- whether any content is no longer obtainable through a permitted route, and what happens to
  claims that depend on it.

If a material fraction is unobtainable, that changes the corpus, the benchmark, and the cutover
gate. It is better discovered in Phase 0 than in Phase 3.

## 7. Human Review Throughput Budget

The plan makes review mandatory in several places - [Lifecycle §10](04-data-lifecycle.md) gates
claim release on approved revisions, [Quality §2.5](06-quality-evaluation-operations.md) requires
100 percent evidence validity for accepted machine claims, and
[Backlog §7](09-implementation-backlog.md) recommends "100 percent reviewed before release" for
the first claim-based release. It lists review throughput as a `High/medium` risk and offers
mitigations. It never estimates the work.

In an academic lab, expert reviewer time is the scarcest resource in the system, scarcer than
engineering time and far scarcer than compute. A design that silently requires more of it than
exists will stall at Phase 4 regardless of code quality.

Required budget, to be measured in a pilot rather than assumed:

```text
works in scope
  x experiments per work
  x claims per experiment
  x minutes per claim review (measured on a 50-claim pilot, by predicate)
  = reviewer hours per release

available reviewer hours per week
  = named reviewers x committed hours
```

Run the pilot during Phase 4 before committing to the review policy. If the ratio is infeasible,
the response is a policy decision made in the open, not a quiet lowering of gates:

- reduce predicate count in the first template;
- accept sampled review for predicates with a measured low correction rate, with the sample size
  and confidence interval recorded on the release;
- accept a smaller first release rather than a lower evidence standard;
- stage claim-based release after an unstructured-retrieval release that needs no claim review.

The last option is the important one and it is compatible with the architecture: renditions with
verified spans can serve retrieval and citation without any approved claim. **The first useful
release does not require the claim graph to be reviewed, only parsed.** See
[Delivery Model §3](11-delivery-model-and-continuity.md).

## 8. What This Document Changes

| Document | Change |
|---|---|
| 02 §8.1 | Search deferral thresholds become the table in §4 above. |
| 03 §8.5 | Cross-workspace deduplication prohibition is costed, not merely stated. |
| 06 §11 | Cost tracking gains the measurement set in §2 as its input. |
| 07 Phase 0 | Snapshot inventory must produce measurements 1-10 and the re-acquisition list. |
| 09 §3 | P0 marking is re-read through §3.1/§3.2 before sprint planning. |
| 09 §7 | The multi-workspace decision gains the cost table in §3.3. |
