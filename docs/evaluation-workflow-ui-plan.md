# Evaluation Workflow UI Plan

**Date:** 2026-05-23  
**Project:** RLALab AI Research Assistant  
**Related docs:** `docs/evaluation-phase-review.md`, `docs/evaluation-implementation-plan.md`, `docs/evaluation-expert-questions.md`

## Summary

Evaluation should become a first-class workflow in the application. The current
script-based runner is useful for development, but it does not provide the
operational surface needed for a serious scientific assistant: question-bank
management, reproducible run tracking, expert review assignment, detailed
per-result inspection, scoring, feedback, regression comparison, and release
gate decisions.

The target is an admin and reviewer workflow where:

- admins curate benchmark questions in the UI;
- admins start and inspect evaluation runs;
- each run stores its configuration, corpus state, model state, metrics, and
  artifacts;
- experts can be assigned specific answers to review;
- expert feedback is stored structurally in the database;
- results can be filtered by failure type, question type, reviewer, corpus, and
  model version;
- evaluation summaries can drive release decisions and engineering remediation.

The CLI runner should not disappear. It should become one execution backend for
the same evaluation data model used by the UI.

## Why This Needs Product Workflow

Evaluation is not a one-time script execution. It is a recurring scientific
quality process. The project will need to answer questions such as:

- Which questions are label-complete?
- Which questions still need expert PMIDs or answer outlines?
- Which evaluation runs used which corpus manifest?
- Which runs used which LLM model, prompt, and retrieval settings?
- Which answers still need expert review?
- Which reviewers disagree?
- Which failures are corpus gaps versus retrieval failures?
- Which release is safe enough for internal beta?

These are workflow questions, not just command-line questions. They need
persistent records, user assignment, filters, review states, dashboards, and
audit trails.

## Current Baseline

The current app already has useful building blocks:

- User and role model with `researcher` and `admin`.
- Admin-only API routes under `/api/v1/admin`.
- Frontend admin pages under `/admin`.
- Authenticated proxy calls through `/api/backend/*`.
- Chat sessions and messages already store sources, retrieved chunks, model,
  tokens, and latency.
- `evaluation/run_eval.py` can run retrieval and RAG evaluation against a live
  backend.
- `evaluation/benchmark/questions.jsonl` stores seed questions.

Current gaps:

- Evaluation questions are file-based only.
- Runs are report files only, not database entities.
- Expert scoring is not represented in the app.
- Review assignments do not exist.
- There is no run dashboard or run detail page.
- There is no way to compare runs in the UI.
- There is no release-gate workflow.

## Product Roles

### Admin

Admins can:

- manage questions;
- import/export benchmark files;
- start evaluation runs;
- cancel runs;
- assign results to reviewers;
- view all reviews and reviewer progress;
- mark runs as baselines;
- compare runs;
- set release-gate thresholds;
- close or archive runs.

### Expert reviewer

Expert reviewers can:

- view assigned evaluation results;
- inspect the question, expected answer, generated answer, and sources;
- score answer correctness, completeness, citation support, grounding,
  usefulness, and refusal behavior;
- flag hallucinations, citation problems, missing evidence, or corpus gaps;
- submit notes and recommended remediation;
- mark assignments complete.

Expert reviewers do not need admin privileges for their assigned review queue.
The implemented role model uses a dedicated `evaluator` role for this.

### Researcher

Researchers should not see unreleased evaluation internals by default. Later,
selected summary dashboards may be exposed if useful.

## Proposed Role And Permission Model

The implemented safe path:

- Keep `admin` for full evaluation management.
- Add an `evaluator` role for users who can review assigned evaluation results.
- Allow admins to assign review tasks to active `admin` or `evaluator` users.
- Restrict non-admin reviewers to assignments where `assigned_to_user_id` equals
  their user id.

## Database Schema Plan

Add a dedicated evaluation schema area through Alembic migrations.

### `evaluation_question_sets`

Groups benchmark questions into named sets.

Fields:

- `id`
- `name`
- `description`
- `status`: `draft`, `active`, `archived`
- `created_by_user_id`
- `created_at`
- `updated_at`
- `metadata`

Purpose: allows versioned collections such as `seed-v1`, `beta-v1`, or
`fulltext-v1`.

### `evaluation_questions`

Stores editable benchmark questions.

Fields:

- `id`
- `question_set_id`
- `external_id`: e.g. `q001`
- `question`
- `category`
- `difficulty`
- `domain_fit`
- `expected_behavior`
- `expected_keywords`
- `expected_pmids`
- `expected_dois`
- `gold_answer_outline`
- `supporting_evidence`
- `requires_full_text`
- `review_status`
- `expert_owner_user_id`
- `notes`
- `created_by_user_id`
- `created_at`
- `updated_at`
- `archived_at`

Indexes:

- unique `(question_set_id, external_id)`
- `category`
- `difficulty`
- `review_status`
- `requires_full_text`

### `evaluation_runs`

Stores each execution of retrieval or RAG evaluation.

Fields:

- `id`
- `name`
- `mode`: `retrieval`, `rag`, `combined`
- `status`: `queued`, `running`, `completed`, `failed`, `cancelled`
- `question_set_id`
- `started_by_user_id`
- `started_at`
- `completed_at`
- `corpus_manifest_id`
- `document_count`
- `chunk_count`
- `embedding_model`
- `chunk_size`
- `chunk_overlap`
- `retrieval_config`
- `reranker_config`
- `llm_provider`
- `llm_model`
- `prompt_version`
- `git_commit`
- `runner_version`
- `summary_metrics`
- `error_message`
- `artifact_paths`
- `metadata`

Purpose: replaces anonymous report files with durable app-visible run records.

### `evaluation_run_results`

Stores per-question outputs and metrics for a run.

Fields:

- `id`
- `run_id`
- `question_id`
- `status`: `pending`, `running`, `completed`, `failed`, `skipped`
- `question_snapshot`
- `retrieved_sources`
- `retrieved_pmids`
- `retrieved_dois`
- `retrieved_chunk_ids`
- `expected_pmids_present`
- `expected_dois_present`
- `coverage_status`: `covered`, `missing_gold`, `not_applicable`
- `recall_at_5`
- `recall_at_10`
- `recall_at_20`
- `mrr_at_10`
- `precision_at_k`
- `response_text`
- `response_sources`
- `latency_ms`
- `time_to_first_token_ms`
- `failure_category`
- `error_message`
- `created_at`
- `updated_at`

Purpose: enables per-result inspection and reviewer assignment.

### `evaluation_review_assignments`

Assigns results to expert reviewers.

Fields:

- `id`
- `run_result_id`
- `assigned_to_user_id`
- `assigned_by_user_id`
- `status`: `assigned`, `in_progress`, `submitted`, `returned`, `accepted`
- `due_at`
- `created_at`
- `updated_at`
- `submitted_at`
- `notes`

Indexes:

- `assigned_to_user_id`
- `status`
- `due_at`

### `evaluation_reviews`

Stores expert feedback.

Fields:

- `id`
- `assignment_id`
- `run_result_id`
- `reviewer_user_id`
- `correctness_score`
- `completeness_score`
- `citation_support_score`
- `grounding_score`
- `usefulness_score`
- `refusal_behavior`
- `false_premise_handling`
- `hallucination_flag`
- `citation_issue_flag`
- `corpus_gap_flag`
- `retrieval_issue_flag`
- `generation_issue_flag`
- `latency_issue_flag`
- `recommended_failure_category`
- `reviewer_confidence`
- `free_text_feedback`
- `suggested_answer`
- `created_at`
- `updated_at`
- `submitted_at`

Purpose: structured scoring plus qualitative expert notes.

### `evaluation_run_comparisons`

Optional but useful once baselines exist.

Fields:

- `id`
- `baseline_run_id`
- `candidate_run_id`
- `created_by_user_id`
- `summary`
- `metric_deltas`
- `regressions`
- `improvements`
- `release_gate_status`
- `created_at`

### `evaluation_audit_events`

Optional audit table for high-value actions.

Fields:

- `id`
- `actor_user_id`
- `entity_type`
- `entity_id`
- `event_type`
- `before`
- `after`
- `created_at`

Events to track:

- question created, edited, archived;
- run started, cancelled, failed, completed;
- assignment created or reassigned;
- review submitted or returned;
- baseline set;
- release gate approved or rejected.

## Backend Architecture

Add a backend evaluation module:

```text
backend/app/evaluation/
  runner.py
  metrics.py
  coverage.py
  reports.py
  schemas.py
```

Responsibilities:

- load question sets from DB;
- snapshot questions at run time;
- execute retrieval evaluation;
- execute RAG evaluation through internal service calls or HTTP-compatible
  adapters;
- calculate metrics;
- record run and result rows;
- generate reviewer exports;
- compare runs;
- map failures to remediation categories.

The existing `evaluation/run_eval.py` should call shared service functions where
possible. This keeps CLI and UI behavior aligned.

## API Plan

Use admin routes for management and reviewer routes for assignments.

### Admin question bank endpoints

```text
GET    /api/v1/admin/evaluation/question-sets
POST   /api/v1/admin/evaluation/question-sets
GET    /api/v1/admin/evaluation/question-sets/{set_id}
PATCH  /api/v1/admin/evaluation/question-sets/{set_id}
DELETE /api/v1/admin/evaluation/question-sets/{set_id}

GET    /api/v1/admin/evaluation/question-sets/{set_id}/questions
POST   /api/v1/admin/evaluation/question-sets/{set_id}/questions
GET    /api/v1/admin/evaluation/questions/{question_id}
PATCH  /api/v1/admin/evaluation/questions/{question_id}
DELETE /api/v1/admin/evaluation/questions/{question_id}
POST   /api/v1/admin/evaluation/question-sets/{set_id}/import
GET    /api/v1/admin/evaluation/question-sets/{set_id}/export
```

### Admin run endpoints

```text
GET    /api/v1/admin/evaluation/runs
POST   /api/v1/admin/evaluation/runs
GET    /api/v1/admin/evaluation/runs/{run_id}
POST   /api/v1/admin/evaluation/runs/{run_id}/cancel
POST   /api/v1/admin/evaluation/runs/{run_id}/rerun-failed
GET    /api/v1/admin/evaluation/runs/{run_id}/results
GET    /api/v1/admin/evaluation/runs/{run_id}/summary
GET    /api/v1/admin/evaluation/runs/{run_id}/export
```

### Admin assignment endpoints

```text
POST   /api/v1/admin/evaluation/results/{result_id}/assignments
GET    /api/v1/admin/evaluation/assignments
PATCH  /api/v1/admin/evaluation/assignments/{assignment_id}
POST   /api/v1/admin/evaluation/assignments/{assignment_id}/return
POST   /api/v1/admin/evaluation/assignments/{assignment_id}/accept
```

### Reviewer endpoints

```text
GET    /api/v1/evaluation/reviews
GET    /api/v1/evaluation/reviews/{assignment_id}
PATCH  /api/v1/evaluation/reviews/{assignment_id}
POST   /api/v1/evaluation/reviews/{assignment_id}/submit
```

Reviewer endpoints return only assignments visible to the current user unless
the user is an admin.

### Comparison endpoints

```text
POST   /api/v1/admin/evaluation/compare
GET    /api/v1/admin/evaluation/comparisons
GET    /api/v1/admin/evaluation/comparisons/{comparison_id}
```

## Run Execution Model

### Phase 1: synchronous admin-triggered runs

For the first implementation, a run can execute synchronously from the backend
request if constrained to small question sets. This is simple, but the UI must
show progress and avoid request timeouts.

### Phase 2: background task execution

Move run execution to FastAPI background tasks or a lightweight worker. The run
record becomes the coordination object:

```text
queued -> running -> completed
queued -> running -> failed
queued -> cancelled
```

### Phase 3: durable worker queue

If runs become large or long, introduce a proper job queue. Do not start here
unless needed.

## Frontend Information Architecture

Add a top-level admin evaluation area:

```text
/admin/evaluation
  Overview dashboard
/admin/evaluation/questions
  Question sets and question bank
/admin/evaluation/questions/[questionId]
  Question editor and labels
/admin/evaluation/runs
  Evaluation run list
/admin/evaluation/runs/new
  Start run form
/admin/evaluation/runs/[runId]
  Run summary
/admin/evaluation/runs/[runId]/results
  Result table
/admin/evaluation/runs/[runId]/results/[resultId]
  Per-question result detail
/admin/evaluation/assignments
  Assignment management
/admin/evaluation/comparisons
  Run comparison list
/admin/evaluation/comparisons/[comparisonId]
  Comparison detail
```

Add reviewer pages:

```text
/evaluation/reviews
  My review queue
/evaluation/reviews/[assignmentId]
  Review form for one assigned result
```

## UI Design Requirements

This is an operational tool, not a marketing surface. It should be dense,
quiet, and table-forward.

### Evaluation dashboard

Show:

- active question sets;
- label completeness;
- latest run status;
- latest retrieval metrics;
- latest RAG review status;
- open expert assignments;
- release-gate status;
- key regressions.

### Question bank UI

Required features:

- list questions with filters by set, category, difficulty, review status,
  full-text requirement, expected behavior, and domain fit;
- add question;
- edit question;
- archive question;
- duplicate question;
- import JSONL;
- export JSONL or CSV;
- validate labels;
- show missing fields;
- show linked gold PMIDs/DOIs;
- show whether gold papers are present in the current corpus.

The question list should support bulk selection for status changes, assignment,
export, and validation.

### Run list UI

Required features:

- list runs with mode, status, question set, started by, corpus manifest, model,
  start time, duration, and key metrics;
- filter by status, mode, question set, corpus manifest, and model;
- start a new run;
- cancel running run;
- mark completed run as baseline;
- compare against baseline;
- export report.

### Run detail UI

Required sections:

- run configuration;
- corpus state;
- model and retrieval settings;
- summary metrics;
- failure categories;
- question coverage;
- latency distribution;
- reviewer progress;
- artifacts and exports.

### Result detail UI

Show all context needed for expert review:

- question and category;
- expected behavior;
- gold answer outline;
- gold PMIDs/DOIs;
- coverage audit status;
- retrieved sources and ranks;
- retrieved chunks or excerpts;
- generated response;
- returned sources;
- automatic citation checks;
- metrics for this question;
- assignments and review status;
- remediation flags.

### Reviewer queue UI

Show:

- assignments grouped by due date and status;
- question category and difficulty;
- run name;
- expected behavior;
- review completion state.

### Reviewer form UI

Form fields:

- correctness score;
- completeness score;
- citation support score;
- grounding score;
- usefulness score;
- refusal behavior;
- false-premise handling;
- hallucination flag;
- citation issue flag;
- corpus gap flag;
- retrieval issue flag;
- generation issue flag;
- latency issue flag;
- recommended failure category;
- reviewer confidence;
- comments;
- suggested answer or correction.

The form should save drafts and allow final submission.

## User Workflows

### Question curation workflow

1. Admin opens question bank.
2. Admin creates or imports question set.
3. Admin adds or edits questions.
4. Admin validates missing labels.
5. Admin assigns questions to experts for label completion.
6. Expert labels gold PMIDs, expected answer, and behavior.
7. Admin marks questions `label_complete`.

### Evaluation run workflow

1. Admin opens run creation form.
2. Admin selects question set, mode, retrieval settings, and model.
3. Backend snapshots question set and run metadata.
4. Run status becomes `queued`.
5. Runner executes retrieval or RAG path.
6. Results are inserted as they complete.
7. Summary metrics are calculated.
8. Run status becomes `completed` or `failed`.

### Expert answer review workflow

1. Admin opens a completed RAG run.
2. Admin filters results needing review.
3. Admin assigns results to users.
4. Reviewer opens personal queue.
5. Reviewer scores answers and submits feedback.
6. Admin reviews disagreements or low-confidence reviews.
7. Run summary updates with expert-reviewed quality metrics.

### Regression workflow

1. Admin selects baseline run.
2. Admin selects candidate run.
3. Backend compares metrics, failures, and review scores.
4. UI highlights improvements and regressions.
5. Admin records release decision.

## Integration With Existing Evaluation Scripts

`evaluation/run_eval.py` should remain useful for local development and CI.

Planned evolution:

- move core metric logic into shared backend/evaluation functions;
- keep CLI as a thin wrapper;
- allow CLI reports to import into DB;
- allow UI-triggered runs to export the same JSON format;
- keep script-based smoke tests for non-UI validation.

This avoids split-brain evaluation behavior.

## Data Migration Strategy

Migration order:

1. Add DB tables without changing existing evaluation scripts.
2. Add CRUD and schemas.
3. Add admin APIs for question sets and questions.
4. Add run storage APIs.
5. Add reviewer assignment and review APIs.
6. Add UI pages.
7. Connect runner to DB.
8. Add imports from existing JSONL.
9. Add report export.
10. Add run comparison and release gates.

The existing `questions.jsonl` should be importable into
`evaluation_question_sets` and `evaluation_questions`.

## Testing Plan

Backend tests:

- question set CRUD;
- question CRUD;
- JSONL import/export;
- schema validation;
- run creation and status transitions;
- coverage audit;
- retrieval result persistence;
- RAG result persistence;
- assignment access controls;
- review draft and submission;
- admin-only management restrictions;
- reviewer-only assignment visibility;
- run comparison calculations.

Frontend tests:

- question list filters;
- question add/edit/archive flows;
- run list rendering;
- run detail metrics rendering;
- result detail rendering;
- assignment creation flow;
- reviewer queue;
- review form draft and submit;
- access-denied states;
- loading and error states.

End-to-end tests:

- import seed questions;
- run retrieval evaluation against mocked backend/search service;
- inspect result list;
- assign result to reviewer;
- submit expert review;
- see run summary update.

## Release Gates

Before this workflow is considered ready:

- admins can import existing questions;
- admins can add, edit, and archive questions;
- label validation works;
- admins can create a run from a question set;
- run results persist in DB;
- run details are visible in UI;
- experts can be assigned results;
- experts can submit structured review;
- admins can export reports;
- access control is tested.

Before the project is considered scientifically credible:

- at least 70 questions are expert-reviewed;
- retrieval metrics are non-empty;
- RAG answers have expert scoring;
- citation faithfulness is measured;
- refusal behavior is measured;
- regression comparison exists;
- release decisions are tied to evaluation results.

## Open Decisions

- Whether to add a distinct `evaluator` role or rely on assignment-based
  permissions.
- Whether evaluation run execution should begin as synchronous, background
  task, or worker-queue based.
- Whether expert labels should remain in question records or move to a
  separate labels table.
- Whether reviews should allow multiple submitted reviews per assignment or one
  current review with version history.
- Whether retrieved chunk text should be stored in results or reconstructed from
  chunk ids at view time.
- How much of the workflow should be visible to non-admin lab members.

## First Implementation Slice

The smallest useful slice:

1. Add DB tables for question sets, questions, runs, run results, assignments,
   and reviews.
2. Import current `questions.jsonl` into a draft question set.
3. Build admin question list with add/edit/archive.
4. Build run list and run detail pages from stored records.
5. Persist a retrieval evaluation run into DB.
6. Build result detail page.
7. Add assignment and reviewer review form.

That slice gives the project a real evaluation workflow while leaving advanced
comparison, release gates, and background execution for later.
