# Evaluation Guidelines — RLALab AI Research Assistant

**Version:** 1.0  
**Date:** 2026-05-04  
**Purpose:** Formal evaluation plan for retrieval quality, answer quality, and system performance. Read this before beginning frontend polish.

---

## 1. Why Evaluate Early

The GutFeeling technical assessment (source project) found that retrieval quality and citation faithfulness matter far more than UI polish for a research-facing system. For the RLA Lab domain (synthetic biology, metabolic engineering, Y. lipolytica), general-purpose embeddings may underperform because:

- Scientific terminology is highly specialised (e.g. "oleaginous", "lipid accumulation", "DHAR", "ACC1").
- Abbreviations are dense (CRISPR, CoA, FAS, TAG, FAO, OA).
- Recent publications may lag MeSH indexing.
- Abstract-only retrieval may miss key content in methods/results.

Establishing a baseline before production ensures you do not ship a system with poor retrieval masked by polished UI.

---

## 2. Evaluation Phases

### Phase 1 — Retrieval Evaluation (before LLM integration)
Test the vector index and hybrid search independently.

### Phase 2 — End-to-End RAG Evaluation (after LLM integration)
Test the full pipeline: retrieval → context assembly → generation → citations.

### Phase 3 — Regression Testing (after any index or model change)
Re-run the benchmark whenever: embedding model changes, chunking parameters change, corpus is updated, or the system prompt is modified.

---

## 3. Benchmark Question Set

The benchmark is stored in `evaluation/benchmark/questions.jsonl`.

Each entry has the schema:

```jsonb
{
  "id": "q001",
  "question": "...",
  "category": "factual|review|out_of_scope|citation_stress|methodology",
  "expected_pmids": ["12345678", ...],          // for retrieval evaluation
  "expected_keywords": ["lipid", "ACC1", ...],  // soft check for answer quality
  "difficulty": "easy|medium|hard",
  "notes": "Optional guidance for manual scoring"
}
```

### Minimum benchmark composition (70 questions)

| Category | Count | Description |
|----------|-------|-------------|
| Factual — RLA core domain | 20 | Specific facts about Y. lipolytica, lipid pathways, metabolic engineering |
| Factual — adjacent domain | 10 | Synthetic biology broadly, microbial communities, sustainable protein |
| Review / synthesis | 15 | "What are the main strategies for..." — requires multi-document synthesis |
| Methodology | 10 | "How is CRISPR applied to..." — tests methods section retrieval |
| Out-of-scope | 10 | Questions outside the corpus (clinical, human disease, irrelevant topic) |
| Citation stress | 5 | Questions where the correct answer requires citing a specific paper |

### Sample questions (illustrative — expand before evaluation)

```jsonl
{"id":"q001","question":"What are the main metabolic engineering strategies for increasing lipid accumulation in Yarrowia lipolytica?","category":"factual","difficulty":"easy","expected_keywords":["ACC1","DGA1","lipid","TAG","acetyl-CoA"]}
{"id":"q002","question":"How has CRISPR-Cas9 been applied to engineer Y. lipolytica for industrial applications?","category":"methodology","difficulty":"medium","expected_keywords":["CRISPR","genome editing","Y. lipolytica"]}
{"id":"q003","question":"What is the role of the nitrogen-to-carbon ratio in triggering lipid accumulation in oleaginous yeasts?","category":"factual","difficulty":"medium","expected_keywords":["C:N ratio","nitrogen limitation","lipid accumulation"]}
{"id":"q004","question":"Summarise the key findings on carotenoid biosynthesis engineering in non-conventional yeasts.","category":"review","difficulty":"hard","expected_keywords":["carotenoid","beta-carotene","lycopene","Y. lipolytica","S. cerevisiae"]}
{"id":"q005","question":"What are the arguments for and against using synthetic microbial consortia for industrial bioproduction?","category":"review","difficulty":"hard","expected_keywords":["consortium","division of labour","cross-feeding","stability"]}
{"id":"q006","question":"What is the recommended treatment for type 2 diabetes?","category":"out_of_scope","difficulty":"easy","notes":"Should be refused or redirected — outside corpus domain"}
{"id":"q007","question":"Which paper first demonstrated methanol utilisation in Yarrowia lipolytica?","category":"citation_stress","difficulty":"hard","notes":"Requires citing a specific seminal paper"}
```

---

## 4. Retrieval Metrics

Run `evaluation/run_eval.py --mode retrieval` to compute these metrics.

### 4.1 Recall@k

For questions with `expected_pmids`, check whether the expected document appears in the top-k retrieved chunks.

| k | Threshold |
|---|-----------|
| Recall@5  | ≥ 0.55 (acceptable), ≥ 0.70 (good) |
| Recall@10 | ≥ 0.65 (acceptable), ≥ 0.80 (good) |
| Recall@20 | ≥ 0.75 (acceptable), ≥ 0.85 (good) |

### 4.2 Mean Reciprocal Rank (MRR)

MRR@10: average of 1/rank for the first relevant result in the top 10.

Target: MRR@10 ≥ 0.45

### 4.3 Embedding model comparison

Run retrieval evaluation for each embedding model:

| Model | Recall@5 | Recall@10 | MRR@10 | Latency (query) |
|-------|----------|-----------|--------|-----------------|
| PubMedBERT (primary) | TBD | TBD | TBD | TBD |
| MiniLM-L6-v2 (baseline) | TBD | TBD | TBD | TBD |

Complete the table during evaluation and commit results to `evaluation/reports/`.

### 4.4 Hybrid vs. vector-only vs. lexical-only

Compare the three retrieval modes on the benchmark:

| Mode | Recall@5 | Notes |
|------|----------|-------|
| Vector only | TBD | |
| Lexical (FTS) only | TBD | Strong for exact species names |
| Hybrid (RRF) | TBD | Should outperform both |

If hybrid does not outperform at Recall@5, adjust the RRF k constant or the top_k values per mode.

---

## 5. Answer Quality Metrics

### 5.1 Citation faithfulness

For 20 randomly selected questions from the factual and review categories:

1. Run the full RAG pipeline.
2. Manually check each cited PMID.
3. Score: Does the cited paper actually support the claim it is cited for?

**Target:** ≥ 85% of citations are valid (paper exists and supports the claim).

**Red flag:** If the model cites PMIDs that were not retrieved, there is hallucination in citation generation. Fix the prompt to enforce citation from context only.

### 5.2 Answer relevance (human rating)

Two lab members rate each answer on a 1–5 scale:

| Score | Meaning |
|-------|---------|
| 5 | Accurate, complete, well-structured, correctly cited |
| 4 | Mostly correct, minor omissions or one bad citation |
| 3 | Partially correct, some missing information |
| 2 | Mostly incorrect or hallucinated |
| 1 | Wrong, unhelpful, or refused a valid question |

**Target:** Mean score ≥ 3.8 across factual and review questions.

### 5.3 Out-of-scope refusal rate

For the 10 out-of-scope questions:

- Count how many are correctly refused or redirected (score: 1 point).
- Count how many are answered with hallucinated content (score: 0 points).

**Target:** ≥ 8/10 correct refusals.

### 5.4 No-hallucination rate

For all answered questions: manually flag any answer that contains a claim **not** supported by the retrieved context.

**Target:** < 5% of answers contain hallucinated claims.

---

## 6. Performance Metrics

Measure these using the evaluation runner or a load test tool (locust):

| Metric | Target |
|--------|--------|
| Time to first token (P50) | ≤ 2 seconds |
| Time to first token (P95) | ≤ 5 seconds |
| Total response time P50 (short answer) | ≤ 8 seconds |
| Total response time P95 (long answer) | ≤ 20 seconds |
| Embedding latency per query (CPU) | ≤ 200 ms |
| Vector search latency (P50, 100k chunks) | ≤ 50 ms |
| Concurrent users (no degradation) | ≥ 10 |

Latency measurements should be logged via the `latency_ms` field in `chat_messages` and surfaced in analytics or a simple dashboard.

---

## 7. Evaluation Runner

`evaluation/run_eval.py` is a CLI tool that:

1. Reads questions from `evaluation/benchmark/questions.jsonl`.
2. For retrieval evaluation: calls `POST /api/v1/search` directly.
3. For RAG evaluation: calls `POST /api/v1/chat/sessions/{id}/messages`.
4. Computes and prints recall@k, MRR, and latency.
5. Saves full results to `evaluation/reports/eval_{timestamp}.jsonl`.

Usage:
```bash
# Retrieval only (fast, no LLM calls)
python evaluation/run_eval.py --mode retrieval --api-url http://localhost:8000 --token <jwt>

# Full RAG evaluation (uses LLM, costs tokens)
python evaluation/run_eval.py --mode rag --api-url http://localhost:8000 --token <jwt>

# Single question test
python evaluation/run_eval.py --mode rag --question-id q001 --api-url http://localhost:8000 --token <jwt>
```

---

## 8. Evaluation Iteration Protocol

If retrieval metrics fall below thresholds, try the following in order:

1. **Check chunk size/overlap.** If answers need more context, increase chunk_size from 512 to 1024. Re-embed and re-index.
2. **Check top_k.** Increase RETRIEVAL_FINAL_TOP_K from 5 to 8 and re-run.
3. **Try embedding model comparison.** If PubMedBERT underperforms MiniLM on RRF, reconsider. (This would be surprising but possible for your specific query distribution.)
4. **Add reranking.** Set `RERANKER_ENABLED=true` with `cross-encoder/ms-marco-MiniLM-L-6-v2`. Reranking typically adds 5–15 points to Recall@5.
5. **Expand corpus query.** If many relevant papers are missing, broaden the PubMed query.
6. **Add full text.** If abstract-only retrieval misses methods/results content, run PMC full-text ingestion for the most cited papers in the benchmark.

---

## 9. Regression Test Protocol

Run the benchmark after:
- Any change to embedding model or dimension
- Any change to chunk_size or chunk_overlap
- Any corpus update (new ingestion run)
- Any change to the system prompt
- Any change to retrieval parameters (top_k, RRF constants)
- LLM model upgrade (e.g. claude-sonnet-4-6 → next version)

Store each evaluation run report in `evaluation/reports/` with a timestamp and commit the summary table to `evaluation/README.md`.

---

## 10. Benchmark Expansion Recommendations

For a mature system serving 50–100 lab members, expand the benchmark to:

- 150–200 questions covering all major research threads in the lab (lipid engineering, carotenoids, sustainable protein, microbial consortia, non-conventional organisms).
- Include questions from published papers where the answer is explicitly in the paper — these give ground truth for citation faithfulness.
- Include questions submitted by actual lab members (collect during beta phase via a feedback form or Slack).
- Include adversarial questions: plausible-sounding but incorrect claims presented as questions ("Isn't it true that Y. lipolytica cannot grow on methanol?") — test whether the system corrects false premises.

---

## 11. Checklist Before Production

- [ ] Retrieval Recall@5 ≥ 0.55 on benchmark questions with expected_pmids
- [ ] No-hallucination rate < 5%
- [ ] Citation faithfulness ≥ 85%
- [ ] Out-of-scope refusal ≥ 8/10
- [ ] Mean answer quality score ≥ 3.8 (human rating by ≥ 2 lab members)
- [ ] Time to first token P95 ≤ 5 seconds
- [ ] Concurrent user test passed (≥ 10 users)
- [ ] Feedback mechanism working (thumbs up/down stored in DB)
- [ ] All evaluation results committed to evaluation/reports/
- [ ] Summary table added to evaluation/README.md
