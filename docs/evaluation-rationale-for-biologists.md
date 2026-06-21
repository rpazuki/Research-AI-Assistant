# Evaluation Rationale For Biology Readers

**Audience:** RLA Lab researchers, PhD students, postdocs, and collaborators who need to decide whether the assistant is scientifically useful and safe enough for internal use.

## Why Evaluation Matters

The RLALab AI Research Assistant is not a general chatbot. It is a literature-grounded tool for synthetic biology, metabolic engineering, yeast biology, microbial communities, bioproduction, and sustainable food systems. Its answers should help researchers find and interpret evidence, but it must not create unsupported claims, invent citations, or hide uncertainty.

Evaluation is the way we make that promise testable. A good answer is not only fluent. It must retrieve the right papers, cite them correctly, stay within the evidence, and say when the corpus does not support an answer.

## What We Are Testing

The evaluation workflow asks four practical questions:

1. Can the system retrieve the papers that a domain expert expects?
2. Can it turn retrieved evidence into a useful answer?
3. Can it refuse or qualify answers when the evidence is missing?
4. Can changes to ingestion, embeddings, retrieval, prompts, or models be trusted before release?

The benchmark question set is therefore deliberately mixed. It includes direct factual questions, review-style synthesis questions, methods questions, citation-stress questions, false-premise questions, and out-of-scope questions.

## Why Low Early Scores Are Acceptable

Low scores during early evaluation are not a failure. They are diagnostic. They tell us whether the issue is:

- the corpus does not contain the relevant evidence;
- the evidence exists but retrieval missed it;
- retrieval found the evidence but the generated answer did not use it well;
- the question label is incomplete or too strict;
- the question requires full text while only abstracts are indexed.

This is why the evaluation UI records both automatic metrics and expert review. Automatic retrieval scores show whether expected papers were found. Expert review explains whether the answer is scientifically useful.

## What Counts As A Good Benchmark Question

A benchmark question should represent a real information need from the lab. It should be answerable from literature evidence, not personal lab knowledge unless internal documents are explicitly indexed.

Each question should include:

- a stable ID, such as `q021`;
- a clear question;
- category and difficulty;
- expected behavior, such as answer, partial answer, or refuse;
- expected PMIDs or DOIs when retrieval can be judged automatically;
- a gold answer outline for human review;
- notes on whether full text is required.

Questions without PMIDs or DOIs can still be useful for expert answer review, but they cannot produce strict retrieval recall scores.

## How Expert Review Should Be Done

Expert reviewers should judge the answer, not the model's writing style alone. The key questions are:

- Is the answer correct according to the cited literature?
- Is it complete enough for the question asked?
- Are citations relevant and supportive?
- Does the answer avoid overclaiming?
- Does it identify gaps when the evidence is incomplete?
- Does it refuse out-of-scope or unsupported questions?

The UI records 1-5 scores for correctness, completeness, citation support, grounding, usefulness, and reviewer confidence. It also records issue flags for hallucination, citation problems, corpus gaps, retrieval problems, generation problems, and latency.

## How Results Become Action

Evaluation should lead to specific fixes:

- Corpus gap: ingest more relevant PubMed, PMC full text, PDF, or lab documents.
- Retrieval issue: adjust embeddings, chunking, hybrid search, filters, or reranking.
- Generation issue: revise prompts, citation handling, or model configuration.
- Label issue: improve the benchmark record with better gold IDs or answer outlines.
- Latency issue: tune top-k, reranking, batching, model choice, or deployment resources.

The goal is not to maximize one metric in isolation. The goal is to make the assistant reliably useful for internal scientific work.

## Release Gate

Before a new retrieval setup, model, prompt, or corpus build becomes the default, run an evaluation benchmark and compare it with the previous accepted run.

The first release gate uses conservative default checks:

- mean recall@20 should be at least 0.75;
- mean MRR@10 should be at least 0.45;
- failed questions should be 0.

These thresholds are starting points. They should be refined with expert input as the benchmark grows and the corpus becomes more complete.

