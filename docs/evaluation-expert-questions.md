# Evaluation Questions For Expert Review

**Date:** 2026-05-23  
**Source file:** `evaluation/benchmark/questions.jsonl`  
**Purpose:** Human-readable review pack for lab experts before these questions
are used as a formal evaluation benchmark.

## How Experts Should Use This Document

The current question set is a seed benchmark, not a finished gold standard.
Please review each question before it is used for scoring.

For each question, experts should add:

- whether the question is core, adjacent, out of scope, or should be removed;
- better wording if needed;
- expected answer outline;
- gold PMIDs and/or DOIs;
- key papers that must be retrieved;
- whether abstract-only evidence is enough or full text is required;
- expected refusal behavior for out-of-scope questions;
- any notes about false premises, controversy, or missing corpus coverage.

## Current Coverage

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

Main gap: no current question has gold PMIDs, gold DOIs, or supporting snippets.
Retrieval metrics cannot be trusted until those labels are added.

## Review Template For Future Questions

Use this template when adding new questions.

```text
Question ID:
Question:
Category: factual | methodology | review | out_of_scope | citation_stress
Difficulty: easy | medium | hard
Domain fit: core | adjacent | out_of_scope | remove
Expected behavior: answer | refuse | correct_false_premise
Expected answer outline:
Gold PMIDs:
Gold DOIs:
Key supporting snippets or evidence notes:
Expected keywords:
Requires full text: yes | no | unknown
Expert reviewer:
Reviewer notes:
```

Machine-readable JSONL shape:

```json
{
  "id": "q021",
  "question": "Question text",
  "category": "factual",
  "difficulty": "medium",
  "expected_keywords": [],
  "expected_pmids": [],
  "expected_dois": [],
  "gold_answer_outline": "",
  "requires_full_text": false,
  "expected_behavior": "answer",
  "notes": ""
}
```

## Current Questions

### q001

**Question:** What are the main metabolic engineering strategies for increasing
lipid accumulation in Yarrowia lipolytica?

**Category:** factual  
**Difficulty:** easy  
**Expected keywords:** ACC1, DGA1, lipid, TAG, acetyl-CoA, oleaginous  
**Current notes:** Core domain. Should be answered well with abstract-only
corpus.

**Pre-review comment:** Strong core question. Experts should add gold PMIDs for
classic and recent strategies, especially papers on DGA1, ACC1, TAG assembly,
beta-oxidation, and acetyl-CoA supply.

**Expert fields to complete:**

- Domain fit:
- Expected behavior:
- Expected answer outline:
- Gold PMIDs/DOIs:
- Requires full text:
- Reviewer notes:

### q002

**Question:** How has CRISPR-Cas9 been applied to engineer Yarrowia lipolytica
for industrial bioproduction?

**Category:** methodology  
**Difficulty:** medium  
**Expected keywords:** CRISPR, genome editing, Y. lipolytica, knockout,
insertion  
**Current notes:** Tests methods-section retrieval.

**Pre-review comment:** Good methodology question, but it may require full-text
methods for precise details. Experts should identify papers covering knockout,
integration, multiplex editing, markerless editing, and industrial product
examples.

**Expert fields to complete:**

- Domain fit:
- Expected behavior:
- Expected answer outline:
- Gold PMIDs/DOIs:
- Requires full text:
- Reviewer notes:

### q003

**Question:** What is the role of the carbon-to-nitrogen ratio in triggering
lipid accumulation in oleaginous yeasts?

**Category:** factual  
**Difficulty:** medium  
**Expected keywords:** C:N ratio, nitrogen limitation, lipid accumulation,
citrate, AMP deaminase  
**Current notes:** None.

**Pre-review comment:** Strong conceptual question. Experts should label papers
that explain nitrogen limitation, citrate export, acetyl-CoA generation, and
lipid storage physiology.

**Expert fields to complete:**

- Domain fit:
- Expected behavior:
- Expected answer outline:
- Gold PMIDs/DOIs:
- Requires full text:
- Reviewer notes:

### q004

**Question:** Summarise the current state of carotenoid biosynthesis engineering
in non-conventional yeasts.

**Category:** review  
**Difficulty:** hard  
**Expected keywords:** carotenoid, beta-carotene, lycopene, Y. lipolytica,
Rhodotorula  
**Current notes:** Multi-document synthesis required.

**Pre-review comment:** Useful synthesis question. Experts should decide whether
the scope should include only engineered non-conventional yeasts or also native
carotenogenic yeasts.

**Expert fields to complete:**

- Domain fit:
- Expected behavior:
- Expected answer outline:
- Gold PMIDs/DOIs:
- Requires full text:
- Reviewer notes:

### q005

**Question:** What are the key advantages and challenges of using synthetic
microbial consortia for industrial bioproduction?

**Category:** review  
**Difficulty:** hard  
**Expected keywords:** consortium, division of labour, cross-feeding, stability,
co-culture  
**Current notes:** None.

**Pre-review comment:** Good adjacent-domain synthesis question. Experts should
specify whether the desired answer should focus on engineered consortia,
natural microbial communities, or both.

**Expert fields to complete:**

- Domain fit:
- Expected behavior:
- Expected answer outline:
- Gold PMIDs/DOIs:
- Requires full text:
- Reviewer notes:

### q006

**Question:** How is Yarrowia lipolytica engineered to utilise alternative carbon
sources such as methanol or glycerol?

**Category:** methodology  
**Difficulty:** medium  
**Expected keywords:** methanol, glycerol, carbon source, metabolic engineering,
heterologous  
**Current notes:** None.

**Pre-review comment:** Potentially valuable but should be checked carefully.
Methanol use may be sparse or recently developed compared with glycerol. Experts
should decide whether this should be split into separate methanol and glycerol
questions.

**Expert fields to complete:**

- Domain fit:
- Expected behavior:
- Expected answer outline:
- Gold PMIDs/DOIs:
- Requires full text:
- Reviewer notes:

### q007

**Question:** What are the main strategies for improving fatty acid production
in Saccharomyces cerevisiae?

**Category:** factual  
**Difficulty:** medium  
**Expected keywords:** fatty acid, S. cerevisiae, FAS, ACC1, overexpression  
**Current notes:** Adjacent organism. Tests breadth of corpus.

**Pre-review comment:** Good adjacent-organism probe. Experts should confirm
whether Saccharomyces should stay in the benchmark or be limited to contrastive
questions against Yarrowia.

**Expert fields to complete:**

- Domain fit:
- Expected behavior:
- Expected answer outline:
- Gold PMIDs/DOIs:
- Requires full text:
- Reviewer notes:

### q008

**Question:** What metabolic interventions have been used to increase omega-3
fatty acid production in microorganisms?

**Category:** review  
**Difficulty:** hard  
**Expected keywords:** omega-3, DHA, EPA, fatty acid, desaturase, elongase  
**Current notes:** None.

**Pre-review comment:** Useful review question but broad across organisms.
Experts should define whether the expected answer should prioritize yeasts,
algae, bacteria, or general microbial systems.

**Expert fields to complete:**

- Domain fit:
- Expected behavior:
- Expected answer outline:
- Gold PMIDs/DOIs:
- Requires full text:
- Reviewer notes:

### q009

**Question:** How do researchers validate genome-scale metabolic models for
oleaginous yeasts?

**Category:** methodology  
**Difficulty:** hard  
**Expected keywords:** genome-scale model, GEM, flux balance analysis, FBA,
validation  
**Current notes:** None.

**Pre-review comment:** Strong methodology question. Experts should provide
gold examples that include experimental validation, growth phenotype checks,
flux data, lipid production predictions, or omics integration.

**Expert fields to complete:**

- Domain fit:
- Expected behavior:
- Expected answer outline:
- Gold PMIDs/DOIs:
- Requires full text:
- Reviewer notes:

### q010

**Question:** What are the biosafety and regulatory considerations for releasing
engineered microorganisms for bioproduction?

**Category:** review  
**Difficulty:** medium  
**Expected keywords:** biosafety, containment, regulation, GMO, risk assessment  
**Current notes:** Tests breadth of corpus. May have limited coverage.

**Pre-review comment:** Important but may sit outside the current PubMed query.
Experts should decide whether it belongs in the main benchmark, an admin/policy
benchmark, or an out-of-scope/referral category.

**Expert fields to complete:**

- Domain fit:
- Expected behavior:
- Expected answer outline:
- Gold PMIDs/DOIs:
- Requires full text:
- Reviewer notes:

### q011

**Question:** What fermentation conditions optimise lipid accumulation in Y.
lipolytica batch and fed-batch cultures?

**Category:** factual  
**Difficulty:** medium  
**Expected keywords:** fermentation, batch, fed-batch, dissolved oxygen,
glucose, lipid  
**Current notes:** None.

**Pre-review comment:** Strong lab-relevant question. Experts should identify
whether key details are in abstracts or require full-text methods, tables, and
supplementary material.

**Expert fields to complete:**

- Domain fit:
- Expected behavior:
- Expected answer outline:
- Gold PMIDs/DOIs:
- Requires full text:
- Reviewer notes:

### q012

**Question:** How has synthetic biology been used to redesign central carbon
metabolism in oleaginous organisms?

**Category:** review  
**Difficulty:** hard  
**Expected keywords:** central carbon metabolism, synthetic biology, rewiring,
flux, oleaginous  
**Current notes:** None.

**Pre-review comment:** Good synthesis question. Experts should add an answer
outline that separates pathway rewiring, cofactor balancing, acetyl-CoA supply,
and product-specific engineering.

**Expert fields to complete:**

- Domain fit:
- Expected behavior:
- Expected answer outline:
- Gold PMIDs/DOIs:
- Requires full text:
- Reviewer notes:

### q013

**Question:** What is the recommended treatment for type 2 diabetes?

**Category:** out_of_scope  
**Difficulty:** easy  
**Expected keywords:** None  
**Current notes:** Should be refused or redirected. Completely outside corpus
domain.

**Pre-review comment:** Useful refusal probe. Expected behavior should be
explicitly marked as refusal or safe redirection.

**Expert fields to complete:**

- Domain fit:
- Expected behavior:
- Expected refusal wording:
- Gold PMIDs/DOIs:
- Requires full text:
- Reviewer notes:

### q014

**Question:** How do mRNA vaccines work and what are their side effects?

**Category:** out_of_scope  
**Difficulty:** easy  
**Expected keywords:** None  
**Current notes:** Out of scope. Medical/clinical, not biotechnology.

**Pre-review comment:** Useful refusal probe. It is biomedical but not RLA Lab
corpus scope, so experts should define whether the assistant should refuse,
redirect, or provide only a scope explanation.

**Expert fields to complete:**

- Domain fit:
- Expected behavior:
- Expected refusal wording:
- Gold PMIDs/DOIs:
- Requires full text:
- Reviewer notes:

### q015

**Question:** What is the GDP of the United Kingdom?

**Category:** out_of_scope  
**Difficulty:** easy  
**Expected keywords:** None  
**Current notes:** Clearly out of scope. Economics.

**Pre-review comment:** Good obvious refusal probe.

**Expert fields to complete:**

- Domain fit:
- Expected behavior:
- Expected refusal wording:
- Gold PMIDs/DOIs:
- Requires full text:
- Reviewer notes:

### q016

**Question:** Isn't it true that Y. lipolytica cannot accumulate more than 20%
of its dry cell weight as lipids?

**Category:** citation_stress  
**Difficulty:** hard  
**Expected keywords:** lipid content, dry cell weight, Y. lipolytica  
**Current notes:** False premise. System should correct this; high lipid strains
exceed 60% DCW.

**Pre-review comment:** Valuable adversarial question. Experts must add gold
papers that support the correction and expected wording for correcting the
false premise.

**Expert fields to complete:**

- Domain fit:
- Expected behavior:
- Expected correction:
- Gold PMIDs/DOIs:
- Requires full text:
- Reviewer notes:

### q017

**Question:** Which gene is most commonly overexpressed to increase lipid
accumulation in Y. lipolytica?

**Category:** factual  
**Difficulty:** easy  
**Expected keywords:** DGA1, ACC1, overexpression, lipid  
**Current notes:** None.

**Pre-review comment:** Good citation-stress candidate as well as factual
question. Experts should decide whether the expected answer is DGA1 alone or a
ranked answer including ACC1 and other interventions.

**Expert fields to complete:**

- Domain fit:
- Expected behavior:
- Expected answer outline:
- Gold PMIDs/DOIs:
- Requires full text:
- Reviewer notes:

### q018

**Question:** What are the current approaches for producing sustainable protein
from microbial fermentation?

**Category:** review  
**Difficulty:** medium  
**Expected keywords:** single cell protein, sustainable protein, fermentation,
mycoprotein, biomass  
**Current notes:** Aligned with Bezos Centre / Microbial Food Hub mission.

**Pre-review comment:** Mission-aligned, but broad. Experts should define
whether the answer should include bacteria, yeasts, filamentous fungi, algae,
gas fermentation, waste feedstocks, or only lab-relevant organisms.

**Expert fields to complete:**

- Domain fit:
- Expected behavior:
- Expected answer outline:
- Gold PMIDs/DOIs:
- Requires full text:
- Reviewer notes:

### q019

**Question:** How do researchers use flux balance analysis to identify metabolic
bottlenecks in lipid-producing yeasts?

**Category:** methodology  
**Difficulty:** hard  
**Expected keywords:** flux balance analysis, FBA, metabolic bottleneck,
constraint-based, lipid  
**Current notes:** None.

**Pre-review comment:** Good method-focused question. Experts should add papers
where model predictions were experimentally tested or used to guide strain
engineering.

**Expert fields to complete:**

- Domain fit:
- Expected behavior:
- Expected answer outline:
- Gold PMIDs/DOIs:
- Requires full text:
- Reviewer notes:

### q020

**Question:** What role do lipid droplets play in the cell biology of Y.
lipolytica and how is their biogenesis regulated?

**Category:** factual  
**Difficulty:** medium  
**Expected keywords:** lipid droplet, LD, biogenesis, Y. lipolytica, TAG,
storage  
**Current notes:** None.

**Pre-review comment:** Strong biological question. Experts should add gold
papers covering lipid droplet formation, TAG storage, organelle interactions,
and regulation under nitrogen or carbon stress.

**Expert fields to complete:**

- Domain fit:
- Expected behavior:
- Expected answer outline:
- Gold PMIDs/DOIs:
- Requires full text:
- Reviewer notes:

## Suggested Future Questions To Add

These are placeholders for expert-generated additions.

### Future question slot

**Question:** TBD  
**Category:** TBD  
**Difficulty:** TBD  
**Expected keywords:** TBD  
**Current notes:** TBD

**Expert fields to complete:**

- Domain fit:
- Expected behavior:
- Expected answer outline:
- Gold PMIDs/DOIs:
- Requires full text:
- Reviewer notes:

