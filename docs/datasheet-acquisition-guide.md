# Datasheet acquisition — curator's guide

This explains what a **datasheet run** does, and what every status, column and
badge in the admin UI (and the CSVs it exports) actually means. It covers two
phases: **discovery** (which papers exist and are relevant) and **acquisition**
(fetching full text for the ones that pass discovery).

Code: `pipelines/discovery/`, `pipelines/acquisition/`, `backend/app/datasheet/`,
`frontend/src/components/admin/AdminDatasheetRunClient.tsx`.

---

## 1. The two phases

1. **Discovery** searches PubMed/Crossref/other sources for candidate papers,
   canonicalises and deduplicates them, and judges each one's **relevance** to
   the corpus topic. Every candidate — kept or dropped — is written to the
   discovery manifest CSV, so a curator can see *why* a paper was excluded and
   disagree (`pipelines/discovery/manifest_csv.py`).
2. **Acquisition** walks an ordered ladder of routes for each candidate that
   discovery marked as "to acquire," trying to fetch full text. A paper that
   fails every automated route is not marked a failure — it is queued for a
   human to download by hand.

---

## 2. Discovery: relevance and the manifest CSV

### Relevance verdicts (`pipelines/discovery/relevance.py`)

| Value | Meaning |
|---|---|
| `studies` | The seed organism/topic is what the paper is about — in the title, repeated in the abstract, or paired with the organism in a MeSH heading (Medical Subject Headings). |
| `mentions` | Present but peripheral — one abstract occurrence, no title hit. |
| `off_topic` | No occurrence in any indexed text. |
| `unknown` | Text too thin to judge (no abstract *and* no title hit). These are adjudicated by an LLM judge rather than a rule, since a keyword rule cannot decide from nothing. |

Product/method terms can only *promote* `mentions` to `studies`; they can never
rescue an `off_topic` paper — a paper that never mentions the organism is not
about the organism no matter what else it discusses.

`studies` is always included; `off_topic` never is; `mentions` is included only
if the run was configured with `include_mentions`; `unknown` follows whatever
the LLM judge decided.

### Discovery manifest CSV columns (`pipelines/discovery/manifest_csv.py`)

One row per candidate found, kept or dropped. Empty cells read `Not reported`,
matching the curators' existing spreadsheet convention.

| Column | Meaning |
|---|---|
| `doi`, `pmid`, `pmc_id` | Identifiers, where known. |
| `title`, `journal`, `publisher`, `year` | Bibliographic metadata. |
| `found_in` | Which source(s) turned this paper up (e.g. PubMed, Crossref). |
| `included` | Whether this row proceeded to acquisition. |
| `relevance`, `relevance_reason` | The verdict above, and why. |
| `doc_type` | Article type as reported by the source. |
| `is_review`, `is_retracted`, `retraction_note` | Flags plus, if retracted, the retraction note. |
| `is_preprint`, `preprint_doi`, `version_of_record_doi` | Preprint status and, if applicable, the link between preprint and its published version of record (VoR). |
| `oa_status`, `license` | Open-access status and licence, where reported. |
| `dedupe_group`, `merged_identifiers` | Which duplicate cluster this row belongs to, and the identifiers merged into it. |
| `possible_duplicate_of`, `duplicate_evidence` | Suspected — not confirmed — duplicates. A human decides whether two rows are really the same work; nothing here is acted on automatically. |
| `url` | A link to the record. |

---

## 3. Acquisition: the ladder

For each candidate, acquisition tries routes in this fixed order and stops at
the first success (`pipelines/acquisition/ladder.py`):

1. `pmc_oa` — PubMed Central open-access JATS XML
2. `europepmc` — Europe PMC JATS (a different OA subset from PMC)
3. `biorxiv` — the preprint, when the published version is paywalled
4. `unpaywall` — any open-access copy Unpaywall knows about (publisher or repository)
5. `publisher_tdm` — publisher text-and-data-mining API (inert without an API key)

A paper already cached under `assets/` from a previous run is never re-fetched —
acquisition is fetch-once across runs.

### Why failure isn't the default outcome

Roughly 46% of the corpus is paywalled, and around 126 papers sit behind bot
protection that returns HTTP 403 on the very first request. Most papers will
therefore fail every automated rung — that is expected, not a bug. So a paper
that exhausts the ladder is queued for a human to open via a resolver link
(LibKey/EZproxy/DOI, whichever is configured), not recorded as a failure. A
failure looks like something to fix; an assisted row looks like work to do —
only one of those is true for a paywalled paper.

Scripted institutional login is deliberately never attempted: driving SSO with
stored credentials is the fastest way to get Imperial's IP range blocked, and
credential handling should not be automated.

### Candidate status values (`acquisition_status`)

These are the values set on each candidate row, and what the admin table's
**Status** column shows verbatim:

| Status | Set when | Meaning |
|---|---|---|
| `pending` | Candidate created, acquisition not yet attempted | Initial state. |
| `fetched` | A route in the ladder returned content | Full text acquired (from cache or a live fetch). Counted in the **"Full texts"** stat. |
| `assisted_pending` | Every automated route was exhausted and a DOI exists | Queued for a human to fetch by hand via the resolver link. Counted in the **"Assisted"** stat and exported by the assisted-links CSV (§5). |
| `failed` | Every automated route was exhausted and there is no DOI | No resolver link can be generated either — a genuine dead end. Counted in the **"Failed"** stat. |
| `skipped` | Candidate excluded during discovery (e.g. `off_topic`, or `mentions` with `include_mentions` off) | Never attempted by acquisition at all. |

`blocked` is defined as a constant in the code (`STATUS_BLOCKED`) but is **not
currently assigned as a final candidate status** — a route returning "blocked"
makes the ladder try the next route, and if every route is exhausted the
candidate becomes `assisted_pending` (or `failed` with no DOI), never `blocked`
itself. "Blocked" is visible instead at the *host* level — see below.

---

## 4. Per-host blocking and the circuit breaker

Every fetch is tallied by host, so publisher blocking is visible in the UI
instead of silent (`pipelines/acquisition/ratelimit.py`). Each host badge in
the admin page shows `successes/requests`, plus:

- **`N blocked`** — appears once that host has returned one or more HTTP
  401/402/403 responses (bot protection or missing entitlement). These are
  never retried: retrying is how a per-request block turns into an
  institution-wide IP-range block.
- **`circuit open`** — appears once a host has returned **three consecutive**
  blocked responses (`MAX_CONSECUTIVE_BLOCKS = 3`). Once open, every further
  request to that host in the run short-circuits immediately with outcome
  `circuit_open` and is *not* sent — this is what stops a single stubborn
  publisher (the example in code comments: ~48 MDPI papers) from producing 48
  separate 403s. The tooltip on this badge reads: *"Circuit opened: three
  consecutive blocks, so this host was left alone for the rest of the run."*
  The badge is styled red when the circuit is open, amber if only blocked
  (but not yet open), grey otherwise.

The breaker is scoped to the whole run process (not per-worker), and does not
persist between runs — each new run starts every host's circuit closed.

Separately, a per-host token bucket enforces minimum intervals between
requests (documented API quotas for NCBI/Crossref/Unpaywall/etc., a
conservative 3-second default for anything else assumed to be a publisher),
and `robots.txt` is honoured for direct publisher fetches (not for the
documented APIs, since e.g. NCBI's E-utilities disallows crawlers but not the
API clients it's meant to serve).

---

## 5. Fidelity warnings

After a full-text fetch, extracted text is checked for **character fidelity**
(`pipelines/acquisition/extract_text.py`) — specifically, whether Greek
characters used in strain names (Δ, μ) survived extraction intact. This
matters because a lost Δ silently renames a strain (e.g. `Po1g-Δku70` becomes
`Po1g-Dku70`), which is a data-quality problem, not a formatting one.

A candidate is flagged as a **fidelity warning** if its extracted text has
Unicode replacement characters, or contains a strain name pattern that looks
like it lost a Δ or "delta" during extraction. This does **not** change the
candidate's `acquisition_status` — the fetch still counts as `fetched`, the
asset is kept and usable — it only adds to the **"Fidelity warnings"** stat and
logs a warning naming the affected strain names, so a curator can go check the
source text if a downstream strain name looks wrong.

---

## 6. The admin page, top to bottom

### Acquisition summary panel

Four stats, each drawn from the run's tallies (not the raw candidate table):

| Label | Source | Notes |
|---|---|---|
| **Full texts** | count of `fetched` | Hint shows how many of those came from cache rather than a live fetch this run. |
| **Assisted** | count of `assisted_pending` | Hint: "Downloadable by hand via the resolver link." |
| **Failed** | count of `failed` | |
| **Fidelity warnings** | count of `fetched` candidates with `looks_corrupted` | Hint: "Greek characters may not have survived extraction." |

Below the stats, one badge per host that received at least one request (see §4
for the blocked/circuit-open styling).

### Candidates table

One row per candidate in the run, filterable by relevance and by an
"only those to acquire" checkbox. Columns: Title (with DOI link and journal),
Year, Found in, Relevance (badge, colours per §2), Why (the relevance reason),
Flags (review / retracted / preprint / has-preprint / possible-duplicate
badges — see the discovery manifest columns above for what each means), and
Status (the raw `acquisition_status` string from §3, unstyled).

---

## 7. Exports

- **Discovery manifest CSV** — every candidate found, kept or dropped, with
  the full column set in §2. This is the audit trail for discovery decisions.
  A copy is also written into the run's own cache directory at
  `<run>/discovery/manifest.csv` at the end of the discovery phase. That copy is
  what makes the directory readable from outside this process: the file names
  under `assets/` and `fulltext/` are one-way hashes of a DOI, so without the
  CSV nothing can say which paper a fetched file belongs to.
- **Assisted links CSV** (`assisted_links_csv` in
  `backend/app/datasheet/acquisition_service.py`) — one row per
  `assisted_pending` candidate, sorted by publisher then year (so a curator can
  batch requests to the same publisher). Columns: `doi`, `title`, `journal`,
  `publisher`, `year`, `resolver_url`, `reason`, `relevance`. `reason` is the
  acquisition detail note (e.g. "no automated route; blocked by publisher
  protection" vs "no automated open-access route"). This is the actual work
  list handed to a human — deliberately a plain link list rather than any
  automated proxy session, for the same credential-handling reason routes
  never attempt scripted login.

---

## 8. Feeding a finished run into the corpus

A finished run is a corpus source. Three ingestion sources read a run directly,
so the papers it found and the full text it fetched become answerable in chat
instead of staying inside the datasheet feature:

| Ingestion source | What it indexes |
|---|---|
| `datasheet_manifest` | the papers the run judged relevant — PMC full text where available, abstracts otherwise |
| `datasheet_fulltext` | the text the ladder already fetched, chunked per section so citations can name Methods or Results |
| `datasheet_rows` | curated datasheet rows, one document per row, each citing its own paper |

Point the config's `[datasheet].run_dir` at the run's cache directory (the
ingestion config editor lists finished runs in a dropdown), then queue the job
from the admin ingestion page. Commands and options are in
`docs/ingestion-guide.md`.

Nothing in `datasheet_fulltext` touches the network: a run's full text is
fetched once, by the ladder, under its rate limits.
