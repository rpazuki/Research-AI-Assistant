# Evaluation Phase Review

**Date:** 2026-05-23  
**Project:** RLALab AI Research Assistant  
**Related files:** `evaluation/run_eval.py`, `evaluation/benchmark/questions.jsonl`, `docs/evaluation-guidelines.md`

## Purpose

The evaluation phase is the quality gate for the RAG system. It answers a
simple but high-stakes question: can the assistant retrieve the right lab
literature, cite it faithfully, refuse inappropriate questions, and do this
fast enough for internal researchers?

For this project, evaluation matters more than surface polish because the
assistant is intended to support scientific reasoning. A visually finished chat
interface is not useful if the retrieval layer misses key papers, if the model
answers outside the evidence it retrieved, or if citations point to papers that
do not support the claim.

The current repository already contains an evaluation runner and a seed
benchmark. The next step is to make that benchmark expert-reviewable and
label-complete.

## Rationale

RAG was introduced as a way to connect generated answers to retrieved external
knowledge rather than relying only on model parameters. In biomedical and
bioscience settings, that design is especially relevant because correctness
depends on current papers, exact methods, specific organisms, and traceable
evidence.

Comparable biomedical QA work shows why this project needs expert labels:

- BioASQ-QA is built around biomedical expert questions, supporting documents,
  snippets, exact answers, and ideal summary answers. It is useful as a model
  for how to ask experts to provide not just questions, but also evidence and
  answer material.
- PubMedQA frames biomedical paper QA around PubMed abstracts and expert
  annotations, showing the value of using biomedical literature itself as the
  context for evaluation.
- A recent biomedical RAG study, "Efficient and Reproducible Biomedical Question
  Answering using Retrieval Augmented Generation", compares BM25, BioBERT,
  MedCPT, hybrid retrieval, data stores, latency, and end-to-end RAG behavior
  over PubMed-scale corpora. This is close in spirit to the RLALab assistant
  because it evaluates retrieval strategy, indexing, and response-time
  tradeoffs, not only final answer fluency.
- A microbiology-specific RAG study reports that adding retrieval improved
  large language model performance on microbiology board-style questions. That
  supports the project assumption that domain-grounded retrieval can materially
  improve bioscience QA, but it also reinforces that task-specific evaluation is
  needed.

The key lesson: this project should not evaluate only "does the answer sound
right?". It should separately evaluate retrieval, evidence coverage, answer
faithfulness, refusal behavior, latency, and regression stability.

## Where Evaluation Sits In The Offline Pipeline

Evaluation is downstream of ingestion and indexing. It does not build the
corpus. It checks whether the already-built corpus and live backend behave well.

```text
Corpus config
  -> ingestion
  -> normalization
  -> deduplication
  -> chunking
  -> embedding
  -> Postgres + pgvector
  -> FastAPI search/chat endpoints
  -> evaluation/run_eval.py
  -> evaluation/reports/*.json
  -> expert scoring and remediation
```

This means evaluation should run:

- after the first meaningful corpus ingestion;
- after any corpus update;
- after changing chunk size or chunk overlap;
- after changing embedding model or vector schema;
- after changing retrieval parameters or reranking;
- after changing prompts or LLM provider/model;
- before internal beta release;
- as a regression check before production updates.

Evaluation is also a feedback loop into the offline pipeline. If questions fail
because relevant documents are absent, the remedy is not prompt tuning; it is
corpus expansion or full-text ingestion. If relevant documents are present but
rank too low, the remedy is retrieval tuning, hybrid search changes, reranking,
or chunking changes.

## Current Evaluation Assets

### Evaluation runner

`evaluation/run_eval.py` is the executable harness. It supports two modes:

- `retrieval`: tests direct search without LLM generation.
- `rag`: tests the full chat path through retrieval, prompt assembly,
  streaming generation, source return, and latency capture.

The runner reads:

```text
evaluation/benchmark/questions.jsonl
```

It writes JSON reports to:

```text
evaluation/reports/
```

The comments in the runner mention JSONL output, but the current implementation
actually writes pretty-printed `.json` files named like:

```text
eval_retrieval_YYYYMMDD_HHMMSS.json
eval_rag_YYYYMMDD_HHMMSS.json
```

### Benchmark questions

The current benchmark has 20 seed questions:

| Category | Count |
| --- | ---: |
| factual | 6 |
| methodology | 4 |
| review | 6 |
| out_of_scope | 3 |
| citation_stress | 1 |

| Difficulty | Count |
| --- | ---: |
| easy | 5 |
| medium | 8 |
| hard | 7 |

These questions cover the right broad themes for the lab: `Y. lipolytica`,
oleaginous yeasts, lipid accumulation, CRISPR, genome-scale models, microbial
consortia, sustainable protein, fermentation, and lipid droplet biology.

However, they are currently seed questions, not a validated benchmark.

## What Happens When The Eval Script Runs

### Shared setup

When the command starts, the runner:

1. Parses CLI arguments: `--mode`, `--api-url`, `--token`, and optional
   `--question-id`.
2. Loads questions from `evaluation/benchmark/questions.jsonl`.
3. Filters to one question if `--question-id` is supplied.
4. Uses the supplied JWT bearer token to call the live FastAPI backend.

The backend must already be running, the database must already be populated,
and the token must belong to an active user.

### Retrieval mode

Command:

```bash
python evaluation/run_eval.py \
  --mode retrieval \
  --api-url http://localhost:8000 \
  --token <jwt>
```

For each question, retrieval mode:

1. Skips the question if it has no `expected_pmids`.
2. Calls `POST /api/v1/search` with `{"query": question, "top_k": 20}`.
3. Reads the returned chunks.
4. Extracts PMIDs from retrieved chunks.
5. Computes:
   - Recall@5
   - Recall@10
   - MRR@10
   - request latency in milliseconds
6. Prints one per-question line.
7. Writes a JSON report with summary and per-question results.

Important current behavior: because none of the 20 seed questions currently
contain `expected_pmids`, retrieval mode will skip all questions and report
`n_questions: 0`. This is the largest immediate evaluation gap.

### RAG mode

Command:

```bash
python evaluation/run_eval.py \
  --mode rag \
  --api-url http://localhost:8000 \
  --token <jwt>
```

For RAG mode, the runner:

1. Creates a throwaway chat session with a title like `eval_<timestamp>`.
2. Iterates through each question.
3. Calls `POST /api/v1/chat/sessions/{session_id}/messages`.
4. Consumes the SSE stream.
5. Accumulates `token` events into `response_text`.
6. Captures `sources` events.
7. Stops on the `done` event and records `latency_ms`.
8. Writes a JSON report with question, category, response text, sources, and
   latency.

RAG mode does not currently compute answer quality, faithfulness, citation
support, or refusal correctness. It collects the material needed for human
scoring.

Side effects: RAG evaluation creates an actual chat session and messages in the
database. It also consumes LLM tokens. There is no automatic cleanup step.

## Current Gaps

### Benchmark labeling gaps

- No question has `expected_pmids`, so retrieval metrics cannot run.
- There is no `labels.jsonl` file even though the architecture notes mention
  one.
- There are no gold answer outlines.
- There are no gold supporting snippets.
- `expected_keywords` are useful but too weak for scientific quality scoring.
- Out-of-scope questions lack an explicit expected refusal policy field.
- Citation-stress questions lack mandatory evidence papers.

### Runner gaps

- Retrieval mode does not report Recall@20 despite retrieving top 20.
- Retrieval mode cannot compare vector-only, lexical-only, and hybrid modes.
- RAG mode has no automatic scoring or export format for expert review.
- RAG mode does not compare returned sources against expected PMIDs.
- Reports do not capture corpus manifest id, embedding model, chunk settings,
  retrieval parameters, LLM model, or prompt version.
- Evaluation sessions remain in the database unless cleaned manually.
- There is no longitudinal comparison between report files.

### Methodological gaps

- The seed set is small: 20 questions rather than the 70-question minimum
  proposed in `docs/evaluation-guidelines.md`.
- The current set is light on citation-stress questions.
- The current set has only three out-of-scope questions.
- There are no adversarial questions beyond one false-premise question.
- There are no questions explicitly tied to a known lab paper, grant, protocol,
  or full-text-only methods section.
- There is no inter-rater protocol for expert scoring.

### Corpus-readiness gaps

- Several questions may require full text, not abstracts only:
  - CRISPR implementation details.
  - fermentation conditions.
  - genome-scale model validation.
  - lipid droplet regulation.
- Some broad questions may require corpus expansion:
  - biosafety and regulation;
  - sustainable protein from microbial fermentation;
  - synthetic microbial consortia.
- If relevant papers are absent from the current PubMed query, evaluation
  failure should be attributed to corpus coverage before blaming retrieval.

## Expert Review Before Hand-Off

Before asking domain experts to score model answers, the benchmark itself should
be reviewed by experts. The review should ask them to improve the questions and
provide labels.

Each question should receive:

- domain fit: core, adjacent, out of scope, or remove;
- corrected wording if the question is ambiguous;
- expected answer outline;
- 1 to 5 gold PMIDs and/or DOIs;
- optional supporting snippets or section hints;
- expected keywords;
- whether full text is required;
- whether the system should refuse;
- difficulty estimate;
- notes on false premises or controversies.

Experts should not be asked only "is this a good question?". They need a
structured review sheet that makes the question set executable as a benchmark.
See `docs/evaluation-expert-questions.md`.

## Notes On Current Seed Questions

- `q001`, `q003`, `q011`, `q017`, and `q020` are strong core-domain factual
  questions, but they still need gold PMIDs.
- `q002`, `q006`, `q009`, and `q019` are methodology questions likely to expose
  the abstract-only/full-text boundary.
- `q004`, `q005`, `q008`, `q012`, and `q018` are useful synthesis questions but
  need answer outlines and multiple supporting papers.
- `q010` may be under-covered by the current PubMed query and may need a
  separate biosafety/regulation corpus slice.
- `q013` to `q015` are useful out-of-scope probes; they should be marked with an
  explicit expected refusal.
- `q016` is valuable because it tests correction of a false premise, but it
  needs gold evidence showing the lipid content range.

## Recommended Evaluation Data Model

Keep `questions.jsonl` as the machine-readable source, but expand each record.

Recommended fields:

```json
{
  "id": "q001",
  "question": "Question text",
  "category": "factual",
  "difficulty": "easy",
  "expected_keywords": ["DGA1", "ACC1"],
  "expected_pmids": ["12345678"],
  "expected_dois": ["10.xxxx/example"],
  "gold_answer_outline": "Short answer outline for expert scoring.",
  "supporting_snippets": [
    {
      "pmid": "12345678",
      "section": "Abstract",
      "text": "Short allowed excerpt or paraphrased evidence note."
    }
  ],
  "requires_full_text": false,
  "expected_behavior": "answer",
  "expert_owner": "TBD",
  "notes": "Any ambiguity or false-premise note."
}
```

For out-of-scope questions:

```json
{
  "expected_behavior": "refuse",
  "refusal_reason": "Outside RLA Lab literature corpus and biomedical research assistant scope."
}
```

## Recommended Scoring Protocol

### Retrieval scoring

Use retrieval mode only after `expected_pmids` are added.

Primary metrics:

- Recall@5
- Recall@10
- Recall@20
- MRR@10
- latency per query

Interpretation:

- If expected papers are absent from the database, mark as corpus coverage
  failure.
- If expected papers are present but rank low, mark as retrieval failure.
- If expected papers are retrieved but answer is weak, mark as generation or
  context-use failure.

### RAG answer scoring

For each RAG output, score:

| Criterion | Scale | Meaning |
| --- | --- | --- |
| Answer correctness | 1 to 5 | Is the scientific answer accurate? |
| Completeness | 1 to 5 | Does it cover the expected answer outline? |
| Citation support | 1 to 5 | Do cited papers support the claims? |
| Grounding | 1 to 5 | Are claims limited to retrieved evidence? |
| Usefulness | 1 to 5 | Would a lab researcher find it useful? |
| Refusal behavior | pass/fail | For out-of-scope questions only. |

At least two expert reviewers should score a subset of answers before internal
release. Disagreements should be reviewed to refine both benchmark labels and
assistant prompts.

## Recommended Implementation Work

1. Expand `questions.jsonl` with `expected_pmids`, `expected_dois`,
   `gold_answer_outline`, `requires_full_text`, and `expected_behavior`.
2. Add `evaluation/benchmark/labels.jsonl` if labels should be separated from
   questions.
3. Update `run_eval.py` to report Recall@20.
4. Record run metadata in every report:
   - corpus manifest;
   - document count;
   - chunk count;
   - embedding model;
   - retrieval settings;
   - LLM model;
   - prompt version.
5. Add a reviewer-facing RAG report export, such as Markdown or CSV.
6. Add a cleanup option for evaluation chat sessions.
7. Add regression comparison between two evaluation reports.

## References

- Lewis et al. 2020. "Retrieval-Augmented Generation for Knowledge-Intensive
  NLP Tasks." arXiv. https://arxiv.org/abs/2005.11401
- Krithara et al. 2023. "BioASQ-QA: A manually curated corpus for Biomedical
  Question Answering." Scientific Data. https://www.nature.com/articles/s41597-023-02068-4
- Jin et al. 2019. "PubMedQA: A Dataset for Biomedical Research Question
  Answering." arXiv / EMNLP-IJCNLP. https://arxiv.org/abs/1909.06146
- Stuhlmann, Saxer, and Fuerst. 2025. "Efficient and Reproducible Biomedical
  Question Answering using Retrieval Augmented Generation." arXiv.
  https://arxiv.org/abs/2505.07917
- "Retrieval-augmented generation salvages poor performance from large language
  models in answering microbiology-specific multiple-choice questions." Journal
  of Clinical Microbiology / PubMed. https://pubmed.ncbi.nlm.nih.gov/39932275

