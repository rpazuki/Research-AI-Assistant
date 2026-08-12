# Delivery Model, Continuity, and Tripwires

Status: proposed
Applies to: the whole migration plan
Owner: product owner + technical owner
Last verified: 2026-08-12

## 1. The Staffing Assumption Is Unverified

[Migration Roadmap §7](07-migration-roadmap.md) sets its 32-40 week envelope on:

> 2-3 backend/data engineers; 1 frontend engineer shared across phases; regular scientific
> data-steward/reviewer time; part-time security/platform support.

That is roughly 4 FTE of engineering plus fractional specialists for most of a year. The legacy
repository shows a different production reality: about 40,000 tracked lines of Python across 176
files and 15,000 lines of TypeScript, with an `AGENTS.md`, a `CLAUDE.md` written as instructions to
an implementing agent, and a `mistakes.md` whose update rule is addressed to an AI agent. This is a
single-maintainer, agent-assisted codebase.

If the 4-FTE team does not exist, the roadmap is not slow - it is unexecutable, and every phase gate
in it is aspirational. The plan must state which delivery profile it assumes, because the answer
changes the architecture, not only the schedule.

## 2. Three Delivery Profiles

| | **A. Staffed rewrite** | **B. Single maintainer, agent-assisted** | **C. Strangle in place** |
|---|---|---|---|
| Assumption | ~4 FTE, as roadmap §7 | 1 maintainer plus coding agents, part-time steward | 1 maintainer, no new repository |
| Repository | New monorepo | New monorepo, reduced surface | Current repository, new packages beside old |
| Scope | Documents 00-09 as written | §3 below: evidence-and-release core only, claim graph staged | Same target model, introduced module by module |
| Multi-workspace | Shared-safe from the start | Tenancy-ready single-tenant ([Scale §3.3](10-scale-sizing-and-proportionality.md)) | Tenancy-ready single-tenant |
| Worker topology | Six deployments | Two deployments, per-stage concurrency caps | Existing worker plus durable queue |
| First user-visible value | Week ~33 (cutover) | Week ~12 (§3) | Week ~6, continuous |
| Envelope to cutover | 32-40 weeks | 40-60 weeks for the reduced scope | No cutover event; continuous |
| Principal risk | Team does not exist | Maintainer bandwidth; agent-introduced defects at scale | Legacy assumptions survive the refactor - the failure mode the plan was written to prevent |
| Principal advantage | Clean boundaries, fastest to full target | Clean boundaries, value early, honest scope | No dual-system drift, no freeze, no cutover risk |

The plan's [README](README.md) rejects profile C in a single paragraph - "incrementally generalising
those abstractions would keep their hidden assumptions" - without comparing it. That rejection is
probably right for the *data model*: `NormalizedDocument` as universal schema cannot be
incrementally corrected, and the audit's root-cause analysis (00 §9) is convincing. But it is not
obviously right for *everything else*. Auth, session handling, the frontend shell, the provider
abstractions, the evaluation harness, and the deployment scripts carry no PubMed-shaped assumption
and are already working.

A defensible hybrid, and the recommended position if profile A is not staffed:

> **New repository, new domain and lifecycle. Port - not rewrite - auth, the frontend shell, the
> provider abstractions, the resilience layer, the evaluation harness, and the operations scripts,
> after extracting each as a contract and re-testing it against the new model.**

This is what [Roadmap §12](07-migration-roadmap.md) means by "reuse is by extracted contract and
verified behaviour, not by copying modules wholesale", but the roadmap never turns it into
allocated, sequenced work. It should: porting five working subsystems is weeks of effort, and
rewriting them is months.

**Decision required before Phase 1:** which profile. Record as an ADR with the staffing commitment
attached. Do not begin Phase 1 against profile A without named people.

## 3. MVP: What a Lab Member Can Use, and When

Under the roadmap as written, users receive nothing until Phase 6 at weeks 33-40, while Phase 0
simultaneously freezes the legacy system. Eight months of frozen legacy plus no successor is the
single largest product risk in the plan and it is not listed in the risk table.

The architecture supports a much earlier useful release, and the plan does not exploit it. The key
observation is in [Lifecycle §10](04-data-lifecycle.md):

> Unstructured literature search may include approved renditions without claim review if policy
> permits, but citations still use verified spans.

That is the MVP. **Retrieval and citation need the evidence chain - work, asset, rendition, span,
release - but do not need the entity/experiment/claim graph, and therefore do not need claim
review.** The claim graph is what makes the datasheet workflow rigorous; it is not what makes the
chatbot work.

### Milestone M1 - "Ask, with real citations" (target: end of Phase 3, not Phase 6)

Contents: workspaces and auth; object store; task DAG; two or three discovery connectors; identity
reconciliation with reviewed conflicts; rights decisions; acquisition including the assisted loop;
JATS and PDF parsing with verified spans; a corpus release; lexical plus vector projections;
release-aware retrieval; answer generation with resolvable citations.

Excluded: the claim graph, extraction templates, claim review, long-form export, wide XLSX,
OCR beyond a basic path, DOCX/XLSX parsers, evaluation automation beyond the retrieval benchmark.

Why it is worth shipping alone: it is already strictly better than the current product on the
dimension users notice - every citation resolves to a verified span in an immutable asset rather
than to a chunk of a possibly-stale row - and it retires the audit's critical findings C-2
(no access policy in retrieval) and C-3 (unverified evidence) without waiting for E8.

### Milestone M2 - "Datasheets, with evidence" (end of Phase 4)

Adds the claim graph, templates, extraction, review, and long-form export. This is where the
review-throughput budget in [Scale §7](10-scale-sizing-and-proportionality.md) is spent, and where
it should be measured on a pilot first.

### Milestone M3 - "Full replacement" (Phase 5-6)

Adds refresh, retraction propagation, release comparison, second-domain proof, and cutover.

**Change to the roadmap:** dual-run users on M1 rather than waiting for M3. Real questions from real
researchers against the new retrieval path is the highest-value evaluation signal available, and it
arrives twenty weeks earlier than the current plan allows.

## 4. Legacy Freeze Carve-Out

[Roadmap Phase 0](07-migration-roadmap.md) requires: "freeze architectural expansion in legacy
pipelines. Continue only defect fixes, security work, and changes needed to export or compare data."

For an eight-month build this is untenable without a carve-out, and the plan provides none. The lab
has an active scientific deliverable - the Yarrowia datasheet - and cannot suspend it while the
platform is rebuilt.

Carve-out policy:

| Legacy change class | Permitted during freeze | Condition |
|---|---|---|
| Defect fix, security fix | Yes | Always. |
| Data export, snapshot, comparison tooling | Yes | Always. |
| Running existing pipelines to produce scientific output | **Yes** | Outputs are treated as class D legacy proposals on import; no new schema. |
| New extraction template or column in the existing wide model | Case by case | Only if the scientific need is dated and the owner accepts re-review at import. |
| New source connector in the legacy pipeline | No | Build it in the successor instead. |
| New schema, new job type, new cache format | No | This is the drift the freeze exists to stop. |
| Frontend changes to legacy workflow screens | No | Except defect and security fixes. |

**Datasheet continuity:** name explicitly which datasheet runs will be produced on the legacy system
during the migration, and record for each that its rows import as unreviewed proposals
(Roadmap §4). Do not let a scientific deliverable created during the freeze become an
undocumented reason to keep the legacy system alive after cutover.

## 5. Feature-Parity Register

[Roadmap §4](07-migration-roadmap.md) maps legacy *data* to new targets. It does not map legacy
*features*. Several user-visible capabilities of the current product have no home in documents
00-09 and would disappear silently at cutover.

| Current feature | Evidence in legacy | Target home in the plan | Status |
|---|---|---|---|
| Chat with SSE streaming | `api/routes/chat.py` | 02 §8.3, 09 E11 | Covered |
| Session list, restore, rename, delete | `chat/[sessionId]`, `ChatClient.tsx` | 03 §14 mentions sessions only | **Under-specified** |
| Auto-generated session title from first message | `test_api_integration.py` | Nowhere | **Missing** |
| Direct semantic search endpoint without generation | `api/routes/search.py` | 02 §9 lists `/search`; no behaviour defined | **Under-specified** |
| Feedback rating and comment | `feedback` table, 09 E11 | 03 §14, E11 | Covered |
| Corpus analytics: temporal, journals, MeSH terms, topics, corpus stats | `api/routes/analytics.py`, `/analytics` page | Mentioned only as a leakage surface (01 §P-7) | **Missing** |
| Admin user management and provisioning | admin routes, 09 E2 | E2 | Covered |
| Admin datasheet run monitoring UI | `AdminDatasheetRunClient.tsx` | Replaced by the review UIs in 02 §10 | Covered by replacement |
| Wide XLSX datasheet as the lab's deliverable | `csv_writer.py`, `docs/*.xlsx` | 03 §12.2 demotes it to "convenience view" | **Needs stakeholder agreement** |
| Operations scripts: deploy, restart, status, logs, collect-logs | `scripts/` | 06 §12 requires runbooks; no port plan | **Missing** |
| `RLALAB_ENV` single-variable config scenario model | CLAUDE.md §14 | 08 §9 proposes a different loading order | **Conflict, see §6** |

Actions:

1. **Analytics needs a design.** Release-scoped analytics over the new model is not a port of the
   old queries; counts must be policy-filtered and release-anchored, and "MeSH terms" is a
   PubMed-specific field that in a source-neutral model becomes a subject-assertion projection.
   Add it to E11 or state that it is dropped for M1 and returns in M3.
2. **Wide XLSX is a stakeholder decision, not an architecture decision.** The plan is right that
   long-form is the auditable projection. But the wide sheet is what the lab currently hands to
   scientists. Confirm with the scientific owner that wide XLSX remains a first-class, supported,
   documented output generated from the release - not an afterthought - before demoting it in
   writing.
3. **Port the operations scripts.** `deploy.sh`, `status.sh`, `logs.sh`, and `collect-logs.sh` with
   its redaction library encode real operational knowledge and satisfy several of the runbook
   requirements in 06 §12. Allocate the port; do not rediscover it.

## 6. Carrying Forward the Configuration Lesson

The current repository documents a hard-won configuration model in CLAUDE.md §14: one variable
(`RLALAB_ENV`) names the scenario, `.env` holds secrets and behaviour with **no hostnames, ports,
or URLs**, and address files are per-scenario and committed. The stated reason is a specific class
of bug - a host process handed a Compose service name, producing `getaddrinfo ENOTFOUND backend` -
plus the rule that each address has exactly one owner.

[Repository Plan §9.1](08-repository-documentation-plan.md) proposes a different loading order and
never references this lesson. That is exactly the pattern the plan criticises elsewhere: discarding
a learned correction because the surrounding architecture changed.

**Action:** write an ADR for configuration that carries forward, at minimum: one scenario variable;
no addresses in the secrets file; exactly one owner per address; no password duplicated into a
`DATABASE_URL` in an address file; and `--print-effective-config` showing source and checksum per
key. Reconcile it with the layered order in 08 §9.1 rather than replacing one with the other.

Apply the same treatment to the rest of [`mistakes.md`](../mistakes.md) - see
[Spikes §9](12-technical-spikes-and-open-choices.md).

## 7. Tripwires and Abort Criteria

The plan has a rollback plan for *cutover* (07 §9). It has no abort criterion for the *migration*.
Second-system rewrites fail in a characteristic way: the new system is always six weeks from
overtaking the old one, and the old one is frozen the whole time. A plan of this ambition needs
tripwires that are agreed before the work starts, when they are cheap to agree.

| Tripwire | Check at | Response if tripped |
|---|---|---|
| Profile A staffing not committed with named people | Phase 1 start | Re-plan against profile B scope in §2-3 before writing code. |
| Phase 0 measurements ([Scale §2](10-scale-sizing-and-proportionality.md)) incomplete | Phase 1 exit | Do not start Phase 2. Non-regression gates are undefined without them. |
| Re-acquisition list is a large fraction of the corpus, or contains unobtainable content | Phase 0 end | Re-scope the first release; decide whether metadata-plus-abstract tiers are acceptable. |
| Phase 2 exit gates unmet 6 weeks past plan | Week ~21 | Owner review: reduce connector set to the two with proven unique contribution. |
| Evidence-span exactness gate unachievable on real PDFs at target fidelity | Phase 3, spike S2 | Renegotiate the gate ([Spikes §3](12-technical-spikes-and-open-choices.md)) before it silently becomes 99 percent. |
| Review-throughput pilot shows the release cannot be reviewed with available reviewer hours | Phase 4 | Apply the staged options in [Scale §7](10-scale-sizing-and-proportionality.md); ship M1 without the claim graph. |
| M1 dual-run shows no measurable improvement over the legacy product for researchers | Phase 5 | Stop and re-examine. The rewrite's justification is auditability plus quality; if neither is visible, the premise is wrong. |
| Legacy freeze has been breached more than twice with new schema | Any phase | The freeze is not holding; either the carve-out is too narrow or profile C is the honest choice. |
| Elapsed time exceeds 1.5x the envelope with no cutover date | Week ~60 | Owner decision to continue, reduce scope to M1 permanently, or return to profile C. |

Tripping a tripwire is not failure. Failing to notice one is.

## 8. Product Success in User Terms

[README §Success Definition](README.md) lists twelve criteria. All twelve are architectural - "can
reproduce every discovery run", "can show an auditor the complete lineage". None is about whether a
researcher in the lab is better served. An auditor is not a user of this system; the twelve criteria
describe a system that is *defensible*, not one that is *used*.

Add, and measure at M1 dual-run and again at cutover:

1. A researcher gets a useful, correctly cited answer to a real question more often than with the
   legacy system, judged on a blinded expert rubric on the same question set.
2. A researcher can tell, without leaving the answer, why a claim is supported - the citation opens
   the exact evidence in its source context.
3. The time from "we need a datasheet on X" to "reviewed datasheet exists" falls, measured
   end-to-end including human review, not only machine stages.
4. Weekly active lab members after cutover is at least the legacy baseline.
5. Researchers report fewer instances of the failure they actually complain about - record that
   complaint set during Phase 0 and re-measure it.

Without these, the plan can pass every gate it defines and still deliver a system nobody prefers.
