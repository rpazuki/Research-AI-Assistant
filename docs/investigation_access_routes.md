# Publisher coverage and access routes

*706 unique DOIs from 723 datasheet rows.*

## The two questions

| | answer |
|---|---|
| **Can a search tool see what PubMed cannot?** | **Yes — unambiguously.** Crossref resolves 704/706 DOIs (99.7%), including 198/199 of the papers PubMed has never heard of. |
| **Can an OA tool fetch what PMC did not?** | **Yes, but not by simply downloading the free PDF.** 156 papers are open access and unfetched, but only **30** are served to a script. The other 126 are free to *read* and gated to *fetch* — the tool needs institutional access or a TDM key, not a scraper. |

- In PubMed: **507/706** (71.8%) — so **199** papers (28.2%) are invisible to a PubMed-only search.
- Open access somewhere: **380/706** (53.8%).
- Full text already retrieved (PMC/bioRxiv only): **228**.
- **Open access but not retrieved: 156** ← the fetch queue.
- Of the 199 non-PubMed papers, **98 are open access** — being outside PubMed says nothing about whether the text is free.

Retrieving the whole queue would take full text from **228** to **384** of 706 papers (**32.3% → 54.4%**). But see §Reachability: only **30** of the 156 are actually served to a script today, so the realistic no-credentials gain is **228 → 258** (**32.3% → 36.5%**). The rest are free to *read* but gated to *fetch* — they need institutional access or a publisher TDM key.

## Publishers

Ordered by size. `not_in_pubmed` is the search-tool gap; `oa_but_not_retrieved` is the access-tool queue.

| Publisher | papers | in PubMed | **not in PubMed** | OA | **OA not fetched** | TDM link |
|---|---:|---:|---:|---:|---:|---:|
| Elsevier | 229 | 153 | **76** | 89 (38.9%) | **53** | 229 |
| Springer Nature | 157 | 140 | **17** | 100 (63.7%) | **8** | 143 |
| MDPI | 88 | 40 | **48** | 88 (100.0%) | **48** | 0 |
| ACS | 83 | 71 | **12** | 11 (13.3%) | **3** | 0 |
| Wiley | 61 | 49 | **12** | 30 (49.2%) | **20** | 44 |
| Frontiers | 21 | 20 | **1** | 21 (100.0%) | **1** | 0 |
| Oxford University Press | 14 | 14 | **0** | 9 (64.3%) | **3** | 5 |
| Royal Society of Chemistry | 11 | 0 | **11** | 4 (36.4%) | **4** | 0 |
| Taylor & Francis | 6 | 3 | **3** | 2 (33.3%) | **2** | 0 |
| ASM | 5 | 5 | **0** | 5 (100.0%) | **2** | 5 |
| Pleiades | 4 | 0 | **4** | 0 (0.0%) | **0** | 4 |
| Korean Society for Microbiology and Biotechnology | 2 | 2 | **0** | 2 (100.0%) | **0** | 0 |
| SAGE Publications | 2 | 1 | **1** | 0 (0.0%) | **0** | 2 |
| PNAS | 2 | 2 | **0** | 2 (100.0%) | **1** | 0 |
| Public Library of Science (PLoS) | 2 | 2 | **0** | 2 (100.0%) | **0** | 0 |
| (unknown) | 2 | 1 | **1** | 0 (0.0%) | **0** | 0 |
| openRxiv | 2 | 0 | **2** | 2 (100.0%) | **0** | 0 |
| SciELO | 2 | 0 | **2** | 2 (100.0%) | **2** | 0 |
| Walter de Gruyter GmbH | 2 | 0 | **2** | 1 (50.0%) | **1** | 2 |
| *11 single-paper publishers* | 11 | 4 | **7** | 10 | **8** | 4 |

## Reachability — the caveat that matters

Unpaywall says a paper is *free*. It does not say the publisher will *serve it to a script*. Every URL in the queue was probed with a politely-identified, rate-limited client:

- **Reachable: 30/156** (19.2%)
- **Blocked or unavailable: 126**, overwhelmingly HTTP 403 bot-blocks at the publisher — not a licensing barrier.

*The exact count moves by ±2 between runs (observed 29–31): publisher blocking is traffic-dependent, not a fixed property of a paper. Read it as "about 30", and note that the variability is itself the point — this is throttling, and hammering it harder makes it worse, not better.*

Blocked papers are still lawfully readable; they simply require a different route (institutional access, or the publisher's TDM API with an entitlement key). Two routes were tested and **rejected** for this set:

| Route tested | Result |
|---|---|
| Europe PMC full-text API | Knows only 60/156 of the queue; full text inside Europe PMC for just 12. `fullTextXML` 404s even for records flagged `inEPMC=Y`. **Not viable.** |
| Crossref TDM links, unauthenticated | Advertised for 76/156, but **0/12 probed returned an article** (Elsevier serves a ~2 KB stub; ASM 403s). Requires an API key + institutional entitlement. **Needs credentials.** |

| Publisher | in queue | reachable | blocked |
|---|---:|---:|---:|
| Elsevier | 53 | 5 | 48 |
| MDPI | 48 | 0 | 48 |
| Wiley | 20 | 2 | 18 |
| Springer Nature | 8 | 8 | 0 |
| Royal Society of Chemistry | 4 | 0 | 4 |
| ACS | 3 | 1 | 2 |
| Oxford University Press | 3 | 1 | 2 |
| ASM | 2 | 2 | 0 |
| SciELO | 2 | 2 | 0 |
| Taylor & Francis | 2 | 0 | 2 |

> **The MDPI case is the sharpest illustration.** All 48 queued MDPI papers are gold OA (48 explicitly CC-BY — a licence that permits mining and even redistribution), and PubMed indexes fewer than half of them. They are the single biggest free win in the corpus, and every one of them refuses a scripted fetch. The barrier is entirely technical, not legal.

**The routing conclusion, per cluster:**

| Cluster | Papers | Route |
|---|---:|---|
| Reachable now | 30 | Direct fetch. Build this today — no blockers |
| MDPI / Frontiers gold OA | ~49 | CC-BY, but Cloudflare-gated. Use the institutional route, or ask MDPI for sanctioned bulk access — **do not attempt to defeat the bot protection**; that is what gets an institution blocked |
| Elsevier / Wiley / Springer | ~81 | Their **TDM API with an Imperial key**. Crossref already advertises the links; they need the entitlement to return anything |
| Long tail | remainder | Institutional link resolver, then manual |

## Where the OA fetch queue points

| host type | papers |
|---|---:|
| publisher | 131 |
| repository | 25 |

| licence | papers |
|---|---:|
| cc-by | 79 |
| (none stated) | 46 |
| cc-by-nc-nd | 21 |
| other-oa | 4 |
| cc-by-nc | 3 |
| cc-by-nc-sa | 2 |
| cc-by-sa | 1 |

## Files

| file | contents |
|---|---|
| `publisher_breakdown.csv` | per publisher: PubMed coverage, OA mix, TDM links |
| `journal_breakdown.csv` | per journal, incl. whether PubMed indexes it at all |
| `oa_fetch_queue.csv` | the actionable list: OA papers not yet retrieved, with URL + licence |