# Evaluation Implementation Plan

**Date:** 2026-05-23  
**Project:** RLALab AI Research Assistant  
**Source review:** `docs/evaluation-phase-review.md`  
**Expert question pack:** `docs/evaluation-expert-questions.md`

## Summary

This plan turns the evaluation review into an implementation roadmap. The goal
is to make evaluation a release gate, not an optional afterthought. The system
should not be considered useful until it can show, with expert-reviewed
evidence, that it retrieves relevant literature, answers within the retrieved
context, cites faithfully, refuses out-of-scope questions, and remains stable
after corpus, embedding, retrieval, prompt, or model changes.

The current repository has a useful foundation:

- `evaluation/run_eval.py` can run retrieval-only and full RAG evaluations.
- `evaluation/benchmark/questions.jsonl` contains 20 seed questions.
- `docs/evaluation-guidelines.md` describes target metrics.
- `docs/evaluation-phase-review.md` documents current gaps.
- `docs/evaluation-expert-questions.md` reformats the seed questions for expert
  review.

The main blocker is that the seed benchmark is not label-complete. Retrieval
mode currently has no gold PMIDs to score against, and RAG mode produces
answers for later human review but does not yet score answer quality,
faithfulness, refusal behavior, or source support.

## Success Criteria

Evaluation is sufficient for internal beta only when:

- The benchmark has at least 70 expert-reviewed questions.
- Every retrieval-scored question has gold PMIDs and/or DOIs.
- Every answer-scored question has an expected answer outline.
- Out-of-scope questions define expected refusal behavior.
- The eval runner records corpus, model, retrieval, prompt, and latency
  metadata.
- Retrieval reports include Recall@5, Recall@10, Recall@20, MRR@10, latency,
  and corpus-coverage failure tags.
- RAG reports are exportable for human scoring.
- At least two expert reviewers score a representative set of answers.
- Regression runs can compare a new report against a previous baseline.
- Failures map to remediation categories: corpus, indexing, retrieval,
  generation, citation, prompt, refusal, latency, or UI/proxy.

## Workstream 1: Benchmark Data Model

The benchmark must move from seed prompts to gold-standard evaluation records.

Add or support these fields in `evaluation/benchmark/questions.jsonl`:

```json
{
  "id": "q001",
  "question": "Question text",
  "category": "factual",
  "difficulty": "easy",
  "domain_fit": "core",
  "expected_behavior": "answer",
  "expected_pmids": ["12345678"],
  "expected_dois": ["10.xxxx/example"],
  "expected_keywords": ["DGA1", "ACC1"],
  "gold_answer_outline": "Expected answer content.",
  "supporting_snippets": [
    {
      "pmid": "12345678",
      "section": "Abstract",
      "evidence_note": "Paraphrased note linking the paper to the claim."
    }
  ],
  "requires_full_text": false,
  "expert_owner": "TBD",
  "review_status": "draft",
  "notes": ""
}
```

Allowed `expected_behavior` values:

- `answer`
- `refuse`
- `correct_false_premise`
- `partial_answer_with_gap`

Allowed `domain_fit` values:

- `core`
- `adjacent`
- `out_of_scope`
- `remove`

Recommended `review_status` values:

- `draft`
- `expert_review_needed`
- `expert_reviewed`
- `label_complete`
- `retired`

If labels become too large for `questions.jsonl`, add
`evaluation/benchmark/labels.jsonl` keyed by question id. Do not split labels
until there is a real maintenance benefit.

## Workstream 2: Expert Review Workflow

Experts should review the benchmark before scoring model answers. They should
not receive raw JSONL as the primary review surface.

Review artifacts:

- `docs/evaluation-expert-questions.md` for human-readable review.
- A future CSV or spreadsheet export for batch annotation.
- A machine-readable import path to update `questions.jsonl` after review.

Expert review should ask for:

- wording fixes;
- domain fit;
- expected behavior;
- expected answer outline;
- gold PMIDs;
- gold DOIs;
- required snippets or evidence notes;
- whether abstract-only evidence is enough;
- missing corpus areas;
- difficulty rating;
- reviewer confidence.

Minimum review process:

1. One project owner screens the seed questions.
2. One domain expert labels core factual and methodology questions.
3. A second domain expert reviews a subset for consistency.
4. Disagreements are resolved before questions are marked `label_complete`.
5. Questions without enough evidence are marked as corpus gaps or retired.

## Workstream 3: Benchmark Expansion

The current 20 questions are not enough. Expand in phases.

Minimum beta benchmark:

- 20 core factual questions.
- 10 adjacent-domain factual questions.
- 15 review or synthesis questions.
- 10 methodology questions.
- 10 out-of-scope or refusal questions.
- 5 citation-stress or false-premise questions.

Target mature benchmark:

- 150 to 200 questions.
- Coverage across major lab themes.
- Coverage across easy, medium, and hard questions.
- A mix of abstract-answerable and full-text-required questions.
- A subset tied to known lab papers or landmark domain papers.
- A subset generated from real beta-user questions.

Required topic coverage:

- `Y. lipolytica` lipid accumulation.
- TAG synthesis and storage.
- acetyl-CoA supply and central carbon metabolism.
- CRISPR and genome editing.
- fermentation conditions and process optimization.
- genome-scale metabolic models and FBA.
- carotenoid and terpenoid production.
- fatty acid and omega-3 production.
- microbial consortia and co-culture.
- sustainable protein and microbial biomass.
- biosafety, containment, and GMO regulation.
- lipid droplets and cell biology.
- out-of-scope medical, economic, and general questions.

## Workstream 4: Corpus Coverage Audit

Evaluation failures need attribution. The system must distinguish:

- the gold paper is not in the database;
- the gold paper is present but not retrieved;
- the gold paper is retrieved but not used in the answer;
- the answer uses the paper incorrectly;
- the answer lacks enough full-text evidence;
- the question is outside corpus scope.

Add a coverage audit step that checks gold PMIDs and DOIs against the
`documents` table before retrieval scoring. The report should tag missing gold
documents as corpus failures rather than retrieval failures.

This audit should also identify questions that require:

- broader PubMed query terms;
- PMC full-text ingestion;
- licensed full-text acquisition;
- separate corpora for policy, safety, or lab operations.

## Workstream 5: Evaluation Runner Upgrades

`evaluation/run_eval.py` should become a proper evaluation harness.

Required upgrades:

- Add Recall@20.
- Do not silently skip all retrieval questions without a warning.
- Add a `--fail-on-empty` option for CI or release-gate runs.
- Add run metadata to every report.
- Support retrieval mode comparison: hybrid, vector-only, lexical-only, and
  reranked when available.
- Compare returned PMIDs and DOIs with gold labels.
- Tag corpus failures separately from retrieval failures.
- Add `--cleanup-session` for RAG mode.
- Add `--limit` for quick smoke runs.
- Add `--category` and `--difficulty` filters.
- Add `--output-format json|jsonl|markdown|csv`.
- Add machine-readable error records for failed requests.
- Save exact question snapshot used for the run.

Recommended report metadata:

- timestamp;
- git commit;
- backend API URL;
- corpus manifest id;
- corpus name;
- document count;
- chunk count;
- embedding model;
- chunk size;
- chunk overlap;
- retrieval settings;
- reranker settings;
- LLM provider and model;
- prompt version;
- evaluation runner version.

## Workstream 6: Retrieval Evaluation

Retrieval evaluation should answer whether the database and retrieval stack
surface the right evidence.

Metrics:

- Recall@5.
- Recall@10.
- Recall@20.
- MRR@10.
- Precision@k when multiple gold papers are supplied.
- latency per query.
- coverage-adjusted recall, excluding questions where gold documents are
  absent from the corpus.

Comparisons:

- PubMedBERT vs MiniLM where schema allows.
- hybrid retrieval vs vector-only retrieval.
- hybrid retrieval vs lexical-only retrieval.
- reranked vs non-reranked retrieval.
- abstract-only corpus vs full-text-enhanced corpus.
- different chunk sizes and overlap values.

The result should identify whether retrieval is limited by corpus coverage,
embedding quality, chunking, lexical matching, rank fusion, top-k values, or
missing full text.

## Workstream 7: RAG Answer Evaluation

RAG evaluation should answer whether the full assistant produces useful,
grounded, well-cited responses.

Scoring dimensions:

- answer correctness;
- completeness;
- citation support;
- grounding in retrieved evidence;
- usefulness for lab researchers;
- refusal correctness;
- false-premise correction;
- clarity and structure;
- uncertainty and gap handling.

Each answer should be scored by at least one expert. A representative subset
should be scored by two experts to measure agreement and refine the rubric.

Human scoring export should include:

- question id;
- question;
- category;
- expected behavior;
- gold answer outline;
- gold PMIDs and DOIs;
- generated answer;
- returned sources;
- retrieved PMIDs;
- scoring fields;
- reviewer notes.

## Workstream 8: Citation And Faithfulness Checks

Citation quality is a central scientific safety issue.

Evaluate:

- cited sources exist in the retrieved context;
- cited PMIDs/DOIs are real;
- cited papers support the claims attached to them;
- answer does not cite sources that were not retrieved;
- answer does not overstate what abstracts support;
- answer separates retrieved findings from gaps or uncertainty.

Add checks that compare final answer citations against returned source metadata.
Automatic checks cannot prove scientific support, but they can catch obvious
failures before expert review.

## Workstream 9: Out-Of-Scope And Safety Evaluation

The assistant is internal and domain-bound. Evaluation must prove it can refuse
or redirect unsupported questions.

Out-of-scope categories:

- clinical advice;
- unrelated biomedical topics;
- economics, politics, or general trivia;
- personal data;
- requests for unsupported lab policy;
- prompts that ask the system to invent citations;
- false premises about domain facts.

Scoring should distinguish:

- correct refusal;
- safe partial answer with corpus limitation;
- unsafe hallucinated answer;
- unnecessary refusal of an in-scope question.

## Workstream 10: Performance And Load Evaluation

Scientific quality comes first, but the tool also needs usable latency.

Measure:

- retrieval latency;
- embedding latency;
- time to first token;
- total response time;
- source-return latency;
- RAG answer latency by category and difficulty;
- behavior under concurrent users;
- timeout and failure rates.

Targets should follow `docs/evaluation-guidelines.md`, then be adjusted after
real corpus and hardware measurements.

## Workstream 11: Regression And Release Gates

Evaluation should be rerun after any change that can affect answers.

Regression triggers:

- corpus query changes;
- new ingestion run;
- full-text ingestion added;
- chunk size or overlap changes;
- embedding model changes;
- vector index changes;
- retrieval logic changes;
- reranker changes;
- prompt changes;
- LLM model changes;
- citation formatting changes.

Release gates:

- no empty retrieval benchmark runs;
- no drop in coverage-adjusted Recall@10 beyond an agreed threshold;
- no citation hallucination regression;
- no out-of-scope refusal regression;
- no latency regression beyond agreed limits;
- no unreviewed benchmark labels in the release report.

## Workstream 12: Reporting And Decision Records

Evaluation output should be useful for humans, not only JSON.

Add:

- Markdown summary reports for each run.
- CSV exports for expert scoring.
- Comparison reports between two runs.
- A cumulative evaluation log.
- A decision record for every major retrieval or prompt change driven by
  evaluation results.

Every report should answer:

- what was evaluated;
- against which corpus;
- with which model and retrieval settings;
- what improved;
- what regressed;
- what the next remediation step is.

## Workstream 13: Remediation Loop

Every failure should route to an action.

Failure mapping:

- Gold paper missing: expand corpus or add full-text acquisition.
- Gold paper present but not retrieved: tune retrieval, chunking, RRF, or
  reranking.
- Retrieved evidence not used: improve prompt, context formatting, or source
  selection.
- Unsupported claim: strengthen grounding prompt and citation constraints.
- Bad citation: fix citation extraction and source formatting.
- Bad refusal: tune scope prompt and refusal examples.
- Slow response: profile embedding, database query, streaming, and LLM latency.
- Ambiguous question: revise benchmark wording with experts.

The evaluation plan is complete only if it changes engineering priorities.

## Workstream 14: Evaluation Documentation For Two Audiences

The evaluation workflow needs thorough documentation that can be read by both
biology-domain collaborators and data-science collaborators. These should be
separate documents or clearly separated sections, because they answer different
questions.

### Biology-facing guide

Audience: lab members, biology researchers, PhD students, postdocs, and expert
reviewers who may not work daily with information retrieval metrics.

Purpose:

- explain why a scientific assistant must be evaluated before trust or release;
- explain why fluent answers are not enough for literature-grounded research;
- explain retrieval, grounding, citation faithfulness, refusal behavior, and
  corpus coverage in plain language;
- show what expert reviewers are being asked to judge and why their labels
  matter;
- describe how low early scores should be interpreted as a diagnostic signal,
  not as failure of the project;
- explain how benchmark questions map to real lab use cases.

Required topics:

- what RAG is, using biology-friendly examples;
- why gold PMIDs, DOIs, answer outlines, and supporting evidence are needed;
- difference between corpus gaps, retrieval failures, citation problems, and
  hallucinations;
- how out-of-scope and false-premise questions protect researchers;
- how expert review improves the system over time;
- what evidence is strong enough for abstract-only versus full-text evaluation;
- how evaluation results become ingestion, retrieval, prompt, or UI actions.

### Data-science and mathematical guide

Audience: collaborators with machine-learning, data-science, statistics, or
software engineering background.

Purpose:

- specify the benchmark data model and assumptions;
- define each metric mathematically;
- document how retrieval and RAG reports are computed;
- make regression comparisons reproducible;
- explain caveats such as incomplete labels, corpus coverage adjustment, and
  metric instability on small benchmark sets.

Required topics:

- benchmark schema and label completeness states;
- Recall@k, MRR@k, Precision@k, latency metrics, source-match checks, refusal
  rate, and human review scores;
- coverage-adjusted interpretation when gold documents are absent from the
  corpus;
- why retrieval and generation are evaluated separately;
- how CSV/JSON/JSONL/Markdown report exports should be interpreted;
- how run metadata captures corpus, model, prompt, and retrieval configuration;
- how baseline/candidate regression comparisons should be made;
- recommended statistical caution for small sample sizes and category-level
  slices;
- thresholds for beta release and how thresholds should evolve.

Suggested artifacts:

- `docs/evaluation-rationale-for-biologists.md`
- `docs/evaluation-metrics-and-benchmarking.md`

These docs should be written before the evaluation UI is considered ready for
expert reviewer onboarding.

## Phases

### Phase 0: Lock evaluation scope

- Confirm evaluation is a release gate.
- Confirm required categories and minimum question counts.
- Confirm expert reviewers and owner.
- Freeze the seed questions for first expert review.

### Phase 1: Label the seed benchmark

- Add gold PMIDs/DOIs.
- Add expected behavior.
- Add answer outlines.
- Add full-text requirement tags.
- Add explicit refusal expectations.

### Phase 2: Upgrade the runner

- Add Recall@20.
- Add coverage audit.
- Add metadata capture.
- Add filtering and cleanup options.
- Add reviewer exports.

### Phase 3: Run first retrieval baseline

- Run after meaningful corpus ingestion.
- Measure retrieval with label-complete questions only.
- Identify corpus gaps before tuning retrieval.

### Phase 4: Run first RAG baseline

- Run RAG mode.
- Export answers for expert scoring.
- Score correctness, faithfulness, citations, and refusals.

### Phase 5: Expand benchmark

- Grow to at least 70 questions.
- Balance categories.
- Add citation-stress and adversarial items.
- Add real lab-user questions from beta testing.

### Phase 6: Establish regression process

- Compare reports across runs.
- Define thresholds.
- Add release checklist.
- Add CI smoke test for eval harness mechanics.

### Phase 7: Mature evaluation

- Grow to 150 to 200 questions.
- Add full-text-specific evaluation.
- Add lab-document evaluation.
- Add dashboards or cumulative summaries.
- Revisit thresholds after real usage data.

### Phase 8: Document and onboard reviewers

- Write the biology-facing evaluation rationale guide.
- Write the data-science metrics and benchmarking guide.
- Link both guides from the evaluation UI.
- Use the biology-facing guide during expert reviewer onboarding.
- Use the data-science guide for engineering regression and release decisions.

## Acceptance Criteria

The evaluation phase is implemented when:

- `questions.jsonl` has label-complete seed records.
- The benchmark has a documented expert-review workflow.
- Retrieval eval produces non-empty metric reports.
- RAG eval produces reviewer-ready exports.
- Reports capture corpus and model metadata.
- Coverage failures are separated from retrieval failures.
- Out-of-scope refusal behavior is scored.
- Citation faithfulness has an expert scoring path.
- Regression comparison exists.
- Evaluation results drive documented remediation decisions.
- Biology-facing and data-science-facing evaluation documentation exists and is
  linked from the reviewer/admin workflow.

## References

- Lewis et al. 2020. "Retrieval-Augmented Generation for Knowledge-Intensive
  NLP Tasks." https://arxiv.org/abs/2005.11401
- Krithara et al. 2023. "BioASQ-QA: A manually curated corpus for Biomedical
  Question Answering." https://www.nature.com/articles/s41597-023-02068-4
- Jin et al. 2019. "PubMedQA: A Dataset for Biomedical Research Question
  Answering." https://arxiv.org/abs/1909.06146
- Stuhlmann, Saxer, and Fuerst. 2025. "Efficient and Reproducible Biomedical
  Question Answering using Retrieval Augmented Generation."
  https://arxiv.org/abs/2505.07917
- "Retrieval-augmented generation salvages poor performance from large language
  models in answering microbiology-specific multiple-choice questions."
  https://pubmed.ncbi.nlm.nih.gov/39932275
