# Evaluation Metrics And Benchmarking

**Audience:** engineers, data scientists, and researchers who need precise definitions for retrieval, RAG, human review, comparison, and release gating.

## Evaluation Unit

The atomic evaluation unit is one benchmark question. A question record contains:

- `id`: stable benchmark ID;
- `question`: natural-language query;
- `category`: factual, review, methodology, citation stress, or out of scope;
- `difficulty`: easy, medium, or hard;
- `domain_fit`: core, adjacent, out of scope, or remove;
- `expected_behavior`: answer, partial answer with gap, correct false premise, or refuse;
- `expected_pmids` and `expected_dois`: gold source identifiers;
- `gold_answer_outline`: expected answer points for expert review;
- `requires_full_text`: whether abstracts are likely insufficient.

Retrieval metrics require at least one expected PMID or DOI. RAG answer metrics can still be reviewed manually without gold IDs.

## Retrieval Metrics

Let `G` be the set of expected identifiers for a question, using normalized PMIDs and DOIs. Let `R_k` be the set of retrieved identifiers in the top `k`.

### Recall@k

Current implementation uses binary source-hit recall:

```text
Recall@k = 1 if G intersects R_k, otherwise 0
```

This answers a practical question: did the retriever surface at least one expected source within the review window?

Mean recall@k is the arithmetic mean over scorable questions.

### MRR@k

Mean reciprocal rank rewards early retrieval of a gold source:

```text
RR@k = 1 / rank(first relevant item) if a gold source appears in top k
RR@k = 0 otherwise
MRR@k = mean(RR@k)
```

MRR is sensitive to ranking quality. A system that finds the right paper at rank 1 is better for users than one that finds it at rank 10, even if both have recall@10 of 1.

### Precision@k

Precision@k is:

```text
Precision@k = relevant retrieved identifiers in top k / k
```

For early benchmarks with sparse gold labels, precision should be interpreted cautiously. If a question has only one labelled gold PMID, an actually useful unlabelled paper will be counted as non-relevant.

## RAG Metrics

RAG evaluation records answer text, response sources, latency, and source alignment.

Automatic checks include:

- whether response sources include expected PMIDs or DOIs;
- whether refusal-like language appears for expected-refusal questions;
- latency per answer;
- error count.

Human review remains required for:

- correctness;
- completeness;
- citation support;
- grounding;
- usefulness;
- false-premise handling;
- whether the failure came from corpus, retrieval, generation, or labels.

## Human Review Rubric

Scores are 1-5:

- `1`: unusable or misleading;
- `2`: major issues;
- `3`: partially useful with important caveats;
- `4`: useful with minor issues;
- `5`: excellent for internal research support.

Review dimensions:

- correctness: scientific claims match evidence;
- completeness: answer covers the question scope;
- citation support: cited sources actually support claims;
- grounding: answer stays within retrieved context;
- usefulness: answer helps a lab member make progress;
- reviewer confidence: confidence in the judgement.

Issue flags:

- hallucination;
- citation issue;
- corpus gap;
- retrieval issue;
- generation issue;
- latency issue.

These flags are deliberately orthogonal to scores. A useful answer can still reveal a corpus gap, and a fluent answer can still have a citation issue.

## Benchmark Comparisons

A benchmark comparison takes two completed runs:

- baseline run: accepted reference;
- candidate run: new corpus, embedding, retrieval config, prompt, or model.

The comparison reports metric deltas:

```text
delta = candidate_metric - baseline_metric
```

Positive deltas are good for recall, MRR, and precision. Negative deltas are good for latency and failed-question count.

Question-level deltas compare coverage, recall@20, and MRR@10 per question. These are important because an average can improve while a critical core-domain question regresses.

## Release Gate

The first release gate is intentionally simple:

```text
mean_recall_at_20 >= 0.75
mean_mrr_at_10    >= 0.45
n_failed          <= 0
```

The gate is not a substitute for expert judgement. It is a regression detector and a release discipline. A candidate can pass the gate but still need expert review if it changes answer style, citation behavior, refusal behavior, or domain coverage.

## Interpreting Early Results

Early benchmarks often have sparse labels and incomplete corpus coverage. Treat low scores as attribution signals:

- low recall and corpus gap flags: expand or rebalance corpus;
- low recall without corpus gap: tune retrieval, chunking, embedding, or reranking;
- good retrieval but poor review scores: tune generation prompts or model choice;
- high citation issue flags: improve citation extraction and answer instructions;
- high latency: tune top-k, reranking, or deployment resources.

## Reproducibility Requirements

Each run should preserve:

- question set ID;
- corpus manifest ID when available;
- embedding model;
- retrieval configuration;
- reranker configuration;
- LLM provider and model;
- prompt version;
- runner version;
- git commit when available;
- summary metrics;
- per-question results.

The admin UI and CLI report import both write into the same evaluation tables so results remain comparable.

