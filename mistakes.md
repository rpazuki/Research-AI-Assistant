# mistakes.md — Recurring Mistakes Log

Patterns discovered during implementation, review, and debugging.
**Rule:** Updated after every 5 user requests per session or after a significant bug is found.
Agent must consult this file before writing tests or async code.

---

## 2026-05-16 — Python environment mismatch during validation

### Incident
The configured Python environment selected by tooling was `.venv-1` (Python 3.13). Running backend tests there failed because `pytest` was missing, and installing backend dev dependencies failed due `torch>=2.2.0` wheel incompatibility for that interpreter/platform combination.

### Impact
Validation was temporarily blocked until tests were switched to the repository's existing backend environment (`backend/.venv`, Python 3.12), where dependencies are compatible.

### Root cause
Environment auto-selection preferred a newer local virtualenv not aligned with project constraints and existing dependency lock expectations.

### Prevention
- Verify interpreter path and version before backend test execution.
- Prefer the repository-scoped backend virtualenv for this project (`backend/.venv/bin/python`) unless dependency constraints are explicitly updated for another interpreter.
- Add an explicit environment note in onboarding/test commands to avoid accidental Python 3.13 selection for backend validation.

---

## 2026-05-16 — Async generator used as async context manager (test_e2e.py)

**Mistake:** `async def f(): yield ...` then `async with f() as x:` without `@asynccontextmanager`.  
**Error:** `TypeError: 'async_generator' object does not support the asynchronous context manager protocol`  
**Fix:** Add `@contextlib.asynccontextmanager` decorator.  
**Prevention:** Any async generator used with `async with` must carry `@asynccontextmanager`.

---

## 2026-05-16 — Sync lambda monkeypatching an awaited async function

**Mistake:** `monkeypatch.setattr("mod.async_fn", lambda *a: value)` when the caller does `await async_fn(...)`.  
**Error:** `TypeError: object bool can't be used in 'await' expression`  
**Fix:** Use `async def fake(*a): return value` instead of a lambda.  
**Prevention:** Every monkeypatched callable that is `await`-ed must be `async def`.

---

## 2026-05-16 — JWT dependency override scope leakage

**Mistake:** Setting `app.dependency_overrides` in a test without clearing in a `finally` block.  
**Error:** Intermittent failures depending on test execution order (flaky tests).  
**Fix:** Always `app.dependency_overrides.clear()` in `finally` or fixture teardown.  
**Prevention:** Tests that directly mutate `app.dependency_overrides` need explicit `finally` cleanup.

---

## Standing rules (architecture-level)

- **IVFFlat index:** Never create in Alembic migrations. Create after first ingestion only.
- **Embedding dimensions:** Never mix 768-dim and 384-dim in the same vector column.
- **Blocking in async:** Always use `asyncio.to_thread` for CPU-bound calls inside `async def`.
- **transformers version:** Pin `transformers<4.52` to stay compatible with `torch 2.2.x`.
- **Lazy ORM load:** Never call `model_validate(orm_obj)` when relationships may be unloaded.

---

## 2026-07-29 — Walrus truthiness silently swallows boolean filters

**Mistake:** extending `retrieval._apply_filters` with `if exclude_reviews := filters.get("exclude_reviews"):`.
**Why it is wrong:** the existing filters are all strings/ints, where truthiness is harmless. A
boolean filter breaks: `{"exclude_reviews": False}` takes the same branch as an absent key, so the
two cases become indistinguishable, and any future `0`, `""`, or `[]` filter value is dropped too.
**Fix:** `if filters.get("exclude_reviews") is True:` for booleans; keep the walrus only for
values whose falsy form genuinely means "not set".
**Prevention:** when adding a filter key of a new type to a truthiness-based filter builder, add a
test asserting the explicit-`False` case produces **no** clause.

---

## 2026-07-29 — Unconditional predicates do not belong in a caller-filter builder

**Mistake:** planning to add `is_retracted = FALSE AND chat_visible = TRUE` inside
`retrieval._apply_filters`.
**Why it is wrong:** `test_apply_filters_none_returns_query_unchanged` encodes the function's
contract — "no filters" means no clauses. Corpus-wide invariants are not caller filters, and mixing
them breaks that contract (and the test).
**Fix:** separate `_apply_corpus_visibility(query)`, applied by `_vector_search` and
`_lexical_search` alongside `_apply_filters`.
**Prevention:** before extending a helper, read its tests — they define the contract more precisely
than the docstring does.

---

## 2026-07-29 — Hand-written migrations drift from the ORM silently

**Context:** migration `0006` adds 4 tables (85 columns) plus 13 columns to existing tables. Alembic
autogenerate is not usable here (it misses ARRAY additions — see the standing rules), so the
migration and `models.py` were written by hand and can disagree without any test failing: the suite
never touches a real database.
**Prevention:** after writing a hand-authored migration, diff it against the ORM before running it —
parse the migration with `ast`, collect `create_table` / `add_column` column names, and compare with
`Model.__table__.columns`. Cheap, offline, and catches the whole class of typo/omission bugs.

---

## 2026-07-29 — Repo-root resolution must match the Docker-aware convention

**Mistake:** `_REPO_ROOT = Path(__file__).resolve().parents[3]` in a new `backend/app/*` module that
imports from `pipelines`.
**Why it is wrong:** correct locally, wrong in the container — the image copies `pipelines/` *inside*
`backend/`, so the parent walk overshoots and the import fails at runtime, not in tests.
**Fix:** reuse the existing convention from `app/ingestion/admin_service.py`:
`_BACKEND_DIR = parents[2]`, then `_REPO_ROOT = _BACKEND_DIR if (_BACKEND_DIR / "pipelines").exists() else _BACKEND_DIR.parent`.
**Prevention:** never hand-roll a path to `pipelines/` from backend code; copy the two-line idiom.

---

## 2026-07-29 — Replacing a cascaded child collection collides with unique constraints

**Incident:** `update_template` replaced a template's column set with
`template.columns = [NewColumn(...), ...]` under `cascade="all, delete-orphan"`. Against Postgres this
raised `UniqueViolationError` on `uq_datasheet_template_columns_key` for the first key present in
both the old and new sets — i.e. it broke on essentially every real edit, since a normal edit keeps
most keys. All route tests passed: they mock the session, so no flush ever happens.

**Root cause:** SQLAlchemy does not order orphan DELETEs before the new INSERTs inside a single
flush. The old `(template_id, 'date')` row is still present when the replacement row is inserted.

**Fix:** clear and flush before attaching the replacements.

```python
template.columns.clear()
await db.flush()          # issues the DELETEs
template.columns = [Child(...) for ... ]
```

**Prevention:**
- Any wholesale replacement of a cascaded child collection whose table has a unique constraint on
  `(parent_id, <natural key>)` needs an explicit `clear()` + `await db.flush()` first.
- Mock-session tests cannot catch this class of bug. Either exercise the write path against a real
  database, or add a test that asserts the *ordering* (record `clear` / `flush` / assign on a
  timeline via a fake session, then assert `clear < flush < assign`) — and verify the test fails
  with the fix reverted, so it is not vacuous.

---

## 2026-07-29 — `column != None` compiles to `IS NOT NULL`, widening an UPDATE to every row

**Incident:** `create_template(is_default=True)` called
`_clear_other_defaults(keep_id=None)`, which built `UPDATE datasheet_templates SET is_default = false`
with no WHERE clause. Because `db.execute()` autoflushes first, the pending INSERT landed and was then
cleared by the UPDATE: the seeded default template came back with `is_default = false`. Nothing raised,
and every test passed — the flag was simply wrong in the database.

**Two compounding causes:**
1. `keep_id` was allowed to be `None`, and `Model.id != None` renders as `id IS NOT NULL` — matching
   every row rather than none.
2. `Model(...)` does **not** populate a `default=uuid.uuid4` primary key in Python; the id stays
   `None` until flush. Code that needs the id before flushing cannot rely on it.

**Fix (correctness by construction, not by call ordering):** assign the PK client-side —
`DatasheetTemplate(id=uuid.uuid4(), ...)` — so the id exists immediately, and raise `ValueError` in
`_clear_other_defaults` if `keep_id` is None.

**Prevention:**
- Never pass an optional value into a `!=` filter that scopes a mutating statement. Require it, and
  fail loudly when it is missing.
- When "only one row may be flagged" is an invariant, assert the generated SQL is scoped in a test
  (`"WHERE …id != " in str(stmt)` **and** `"IS NOT NULL" not in str(stmt)`).
- A bug that only corrupts a *value* raises nothing. After writing a service method that mutates
  sibling rows, read the table back and check the flags — do not infer success from a green suite.

---

## 2026-07-29 — Documenting `source .env` imposes shell syntax on the file

**Incident:** the refactor made `.env` safe to source (no addresses), and `run_and_deploy.md`
duly told developers to run `set -a; source .env; set +a`. The very first attempt failed:

```
./.env:53: command not found: AI
```

`SENDGRID_FROM_NAME=RLALab AI Assistant` was unquoted. Docker Compose's `env_file` parser
accepts that happily; POSIX shells do not — they execute `AI` as a command.

**Root cause:** two consumers with different grammars. Compose's parser is lenient about
whitespace and quoting; `source` is a shell parser. A file read by both must satisfy the
stricter one.

**Fix:** single-quote any value containing whitespace or shell metacharacters
(`[]{}()$&|;<>*?#\`\\!~'"`). Compose strips matching surrounding quotes, so both consumers
see the same value.

**Prevention:**
- Any env file a document tells a human to `source` must be validated by actually sourcing it
  in a subshell, not just by `docker compose config`.
- Check both directions after editing such a file: `bash -c 'set -a; . ./.env; set +a; ...'`
  **and** `docker compose config`, and confirm the parsed value matches in each.
- Caught here only because the verification step ran the documented command verbatim. Prefer
  running a doc's own commands over re-deriving an equivalent check.

---

## An absolute filesystem path in a shared column is a per-topology address

**Incident:** the admin stats and acquisition pages failed with
`Cache path must live under data/corpora` while the folder plainly existed. The containerised
ingestion worker had written `/app/data/corpora/rlalab-pubmed-v1` into `ingestion_jobs.cache_path`;
the host backend serving the API computes its cache root from the checkout, so
`/app/data/...` sat outside it and validation rejected the worker's own value.

**Root cause:** the same class as `getaddrinfo ENOTFOUND backend`, one layer down. An absolute
path stored in the database means "wherever the writing process's filesystem was". The path
had no owner: whichever process wrote last decided what it meant.

`_REPO_ROOT` differing between topologies is the mechanism — in the image the backend directory
*is* the repo root (`/app` contains `pipelines/`), on the host it is one level up — but the
defect is storing a resolved absolute path at all.

**Fix:** store the portable tail (`data/corpora/<name>`) and resolve it against the local root
on every read (`store_cache_path` / `resolve_cache_path`), plus a migration rewriting existing
rows and a read path that re-roots legacy absolute values.

**Prevention:**
- Anything persisted in the database or a manifest and consumed by more than one process must be
  **relative to a root that process owns** — never a resolved absolute path.
- When re-rooting an untrusted tail, resolve and re-verify containment afterwards: otherwise
  `data/corpora/../../etc` becomes a way out of the allowed root.
- A named volume (`corpus_data:/app/data`) is not the host `./data`. Before bind-mounting one
  over the other, compare both — here the volume held 2.3 G / 6079 files against the host's
  1.5 G / 4504, so flipping the mount would have hidden ~1500 files.
- Symptom to recognise: a validation error that names a path the user can see on disk. Ask which
  process resolved it, not whether the folder exists.

---

## `.//` in an XML parser reaches into the record's own reference list

**Incident:** discovery found 507 of 507 gold papers that PubMed indexes, but the recall
measurement reported 273. The papers were being found and then filed under the **wrong DOI**:

```python
ids = {node.get("IdType"): node.text for node in article.findall(".//ArticleIdList/ArticleId")}
```

PubMed's efetch response embeds the paper's entire reference list, and every reference carries its
own `ArticleIdList`. The descendant search collected all of them, and the dict comprehension kept
the **last** — so a paper's `doi` became the DOI of the final work it cited. This silently
mislabelled most PMC-deposited records.

**Root cause:** `.//` is a descendant search, and a bibliographic record contains other
bibliographic records. Scope matters most exactly where the schema is self-similar.

**Fix:** read identifiers only from `PubmedData/ArticleIdList`, other fields only from
`MedlineCitation/Article`, with `ELocationID[@EIdType='doi']` as the fallback. Regression test uses
a fixture that *has* a reference list.

**Prevention:**
- In any nested-record format (PubMed XML, JATS, Crossref JSON with `relation`/`reference`), address
  fields by explicit path from the record root. Reserve `.//` for elements that cannot nest.
- When a dict comprehension collapses a repeated element, ask what happens when there are several:
  "last one wins" is a silent choice.
- **A recall measurement against a known-good set is what exposed this.** Unit tests with a
  hand-written fixture passed, because the fixture had no reference list. Measure against real data
  before trusting a parser.

## An upstream's paging contract is not the one you assumed

**Incident:** Crossref returned exactly 400 records per term regardless of budget. Its
`next-cursor` is *repeated* on the second page for `query.bibliographic` searches, so a
cursor-walk loop terminates correctly and silently truncates at two pages. Separately, shrinking
`rows` as a budget ran down invalidated the cursor.

**Fix:** offset paging (documented to offset 10000), with the truncation logged when a term has
more results than that.

**Prevention:**
- Log "N of M retrieved" per paged source, not just N. The 400-vs-2014 gap was invisible until the
  total was printed next to the count.
- Verify a paging loop advances by asserting distinct records across pages, not by trusting the
  next-page token to change.
- Never let a budget change a request parameter mid-walk.

---

## Title matching is not identity

**Incident:** candidate identity matched on normalised title + year as a fallback when no
DOI/PMID was shared. Measured on one Yarrowia run, that merged **205 candidates carrying two or
more distinct DOIs**, including:

- four separate peer-review reports (`.../v1/review1`, `v1/review2`, `v2/review1`, `v2/review2`)
  into one row, because all four are titled `Review for "..."`;
- two different book front-matter sections, both titled `Front Matter`;
- papers with their own figshare/Zenodo data deposits, which share the paper's title.

The last one caused real loss. `merge_records` unions each record's `types`, so a paper that
absorbed a deposit inherited `dataset`, `doctype.classify` then filed the **paper** as `other`, and
it was dropped from acquisition — 4 papers judged `studies` in one run. One row's identity became
the Zenodo DOI, so a citation from it would have pointed at a dataset rather than the paper.

**Root cause:** a title is a string a publisher chose, not an identifier a registrar assigned.
Generic titles ("Front Matter", "Editorial", `Review for "X"`) are shared by construction, and
attachments (data deposits, repository copies, review reports) inherit the parent work's title on
purpose.

**Fix:** identity = DOI, PMID, PMCID only. Title similarity demoted to
`possible_duplicate_of` + `duplicate_evidence`, recorded for a human and never acted on. A DOI-class
preference makes sure a dataset or repository DOI can never become a row's citable identity.

**Prevention:**
- Merge records only on identifiers assigned by a registrar. Any weaker signal becomes a flag, not
  a decision.
- Owner framing worth keeping (2026-07-30): **ingesting one work twice is harmless if each copy
  cites itself correctly; merging two distinct works is not recoverable.** Prefer duplicates to
  wrong merges wherever a dedupe rule is uncertain.
- When merging unions a field that another rule then reads (`types` → doc-type), check what a
  wrongly merged record would do to that rule. The loss here was silent: papers simply stopped
  appearing.
- Audit a dedupe rule by asking it to show its work — "how many rows merged ≥2 distinct DOIs, and
  what were they" found this in one query.

---

## robots.txt is a crawler rule, not an API contract

**Incident:** the acquisition ladder was built with a robots.txt check before every fetch, per the
plan. Its first live run sent **every** paper to the assisted queue, including PMC open-access ones
that should have been fetched automatically. The per-host tally showed the cause:

```
eutils.ncbi.nlm.nih.gov  requests: 0
```

NCBI serves `Disallow: /` on the E-utilities host — a rule aimed at crawlers indexing the website,
while E-utilities is a documented API with its own usage policy (rate limits, `api_key`, contact
email), all of which the client already honoured. Applying robots there disabled the ladder's most
productive route.

**Fix:** robots is checked for **publisher-direct fetches only**; hosts with a documented API
contract (the same set that has published quotas) are exempt.

**Prevention:**
- Distinguish *crawling a site* from *calling an API*. A politeness rule copied from one context
  into the other can silently disable the thing it was meant to protect.
- The per-host tally is what made this a two-minute diagnosis instead of a hunt: a route that made
  **zero requests** is a different failure from one that was refused, and only per-host counters
  tell them apart. Instrument before the first live run, not after.
- A live run against real upstreams found this immediately; 42 offline tests did not, because the
  mock transport had no robots.txt to disallow.

---

## A dedupe rule inherits an assumption the new source breaks

**Incident:** the `datasheet_rows` ingester makes one document per datasheet row, because a row is
what a researcher asks about and each row cites its own paper. Its first real indexing run reported
`datasheet rows: 2 of 2 rows indexed` and then `Indexing complete: 1 documents`. The deduplicator
had dropped the second row: two rows about one paper share that paper's PMID and its title, and the
default rules match on both.

**Root cause:** the deduplicator was written when every document *was* a paper, so "same PMID" and
"same title" meant "same document". A row-scoped source violates that silently — nothing raised,
and the ingester's own count said 2.

**Fix:** `ROW_SCOPED_SOURCES` in `build_index.py`; those sources dedupe on `document_id` only (the
row hash), which still catches an accidental re-read.

**Prevention:**
- When adding a source whose document is *about* a paper rather than *being* one, re-read every
  rule keyed on `pmid` / `title` / `doi`. Identity assumptions live far from the new code.
- Compare the ingester's own count with the indexer's count. `2 of 2 rows indexed` next to
  `1 documents` is the whole bug, visible in two adjacent log lines — but only if a real run is
  performed. 597 unit tests passed with the defect present.
- The unit suite never touches Postgres, so the SQL and the pipeline wiring are both untested by it.
  A scratch database (`CREATE DATABASE`, `alembic upgrade head`, run, drop) is cheap and catches
  the whole class: this same pass verified the COALESCE upsert clause, `section_label` reaching
  `document_chunks`, and that a `--local-only` replay does not duplicate documents.
