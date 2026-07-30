"""Does this candidate *study* the seed, or merely mention it?

Crossref's fuzzy search is what makes this necessary: a bibliographic query for
"Yarrowia lipolytica" returns papers that cite it in one sentence, papers about
other yeasts that used a *Y. lipolytica* lipase as a reagent, and — because the
match is fuzzy — papers with no mention at all.

Three outcomes, plus an explicit ambiguous tail:

* `studies` — the seed is what the paper is about. Term in title, or repeated in
  the abstract, or present with the organism in a MeSH heading.
* `mentions` — present but peripheral: one abstract occurrence, no title hit.
* `off_topic` — no occurrence in any indexed text.
* `unknown` — text too thin to judge (no abstract *and* no title hit). These are
  the rows the LLM adjudicates (`relevance_judge` in the backend); a rule that
  guessed here would silently drop paywalled papers whose abstract nobody has.

Where a term appears is the signal, so positions are tracked rather than a bare
substring test. Every verdict carries a reason string that goes into the manifest
CSV — a filter a curator cannot audit is a filter they cannot trust.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

STUDIES = "studies"
MENTIONS = "mentions"
OFF_TOPIC = "off_topic"
UNKNOWN = "unknown"

# An abstract with at least this many organism occurrences is about the organism
# even without a title hit — chosen because a passing citation is typically one.
_REPEAT_THRESHOLD = 2


@dataclass(frozen=True)
class RelevanceVerdict:
    relevance: str
    reason: str
    title_hits: int = 0
    abstract_hits: int = 0
    matched_terms: tuple[str, ...] = ()
    needs_adjudication: bool = False


def _term_pattern(term: str) -> re.Pattern[str]:
    """Match a phrase tolerantly: any whitespace run, and an abbreviated genus.

    Papers write `Y. lipolytica` far more often than the full binomial after first
    use, so a binomial term also matches its abbreviated form. Without this, an
    abstract that names the organism once in full and six times abbreviated scores
    as a single passing mention.
    """
    words = [re.escape(word) for word in term.split() if word]
    if not words:
        return re.compile(r"(?!)")

    alternatives = [r"\s+".join(words)]
    if len(words) >= 2 and len(term.split()[0]) > 2:
        genus = term.split()[0]
        rest = r"\s+".join(words[1:])
        alternatives.append(rf"{re.escape(genus[0])}\.?\s*{rest}")

    return re.compile(r"(?<![a-z0-9])(?:" + "|".join(alternatives) + r")", re.IGNORECASE)


def count_hits(text: str | None, terms: tuple[str, ...] | list[str]) -> tuple[int, tuple[str, ...]]:
    if not text:
        return (0, ())
    total = 0
    matched: list[str] = []
    for term in terms:
        found = len(_term_pattern(term).findall(text))
        if found:
            total += found
            matched.append(term)
    return (total, tuple(matched))


def judge(
    *,
    title: str | None,
    abstract: str | None,
    organism_terms: tuple[str, ...] | list[str] = (),
    product_terms: tuple[str, ...] | list[str] = (),
    mesh_terms: tuple[str, ...] | list[str] = (),
    keywords: tuple[str, ...] | list[str] = (),
) -> RelevanceVerdict:
    """Rule verdict for one candidate.

    The organism decides the outcome; product terms can only promote a `mentions`
    to `studies`, never rescue an off-topic paper. A paper that does not mention
    the organism is not about the organism whatever else it contains.
    """
    primary_terms = tuple(organism_terms) or tuple(product_terms)
    if not primary_terms:
        return RelevanceVerdict(UNKNOWN, "no seed terms supplied", needs_adjudication=True)

    title_hits, title_matched = count_hits(title, primary_terms)
    abstract_hits, abstract_matched = count_hits(abstract, primary_terms)
    metadata_text = " ; ".join(list(mesh_terms) + list(keywords))
    metadata_hits, metadata_matched = count_hits(metadata_text, primary_terms)
    matched = tuple(dict.fromkeys(title_matched + abstract_matched + metadata_matched))

    product_hits = 0
    if product_terms:
        in_title, _ = count_hits(title, product_terms)
        in_abstract, _ = count_hits(abstract, product_terms)
        in_metadata, _ = count_hits(metadata_text, product_terms)
        product_hits = in_title + in_abstract + in_metadata

    if title_hits:
        reason = f"seed term in title ({title_hits} hit{'s' if title_hits > 1 else ''})"
        if product_hits:
            reason += f"; product term present ({product_hits})"
        return RelevanceVerdict(STUDIES, reason, title_hits, abstract_hits, matched)

    if metadata_hits and not abstract:
        return RelevanceVerdict(
            STUDIES,
            f"seed term in MeSH/keywords ({metadata_hits}); no abstract available",
            title_hits,
            abstract_hits,
            matched,
        )

    if abstract_hits >= _REPEAT_THRESHOLD:
        reason = f"seed term repeated in abstract ({abstract_hits} hits)"
        if product_hits:
            reason += f"; product term present ({product_hits})"
        return RelevanceVerdict(STUDIES, reason, title_hits, abstract_hits, matched)

    if abstract_hits == 1:
        if product_hits:
            return RelevanceVerdict(
                STUDIES,
                f"single abstract mention with product term present ({product_hits})",
                title_hits,
                abstract_hits,
                matched,
            )
        return RelevanceVerdict(
            MENTIONS,
            "single abstract mention, not in title",
            title_hits,
            abstract_hits,
            matched,
        )

    if metadata_hits:
        return RelevanceVerdict(
            MENTIONS,
            f"seed term only in MeSH/keywords ({metadata_hits})",
            title_hits,
            abstract_hits,
            matched,
        )

    if not abstract:
        # No abstract and no title hit: there is nothing to judge on. Calling this
        # off-topic would silently drop the paywalled tail, which is exactly the
        # literature multi-source discovery exists to reach.
        return RelevanceVerdict(
            UNKNOWN,
            "no abstract and no title match — needs adjudication",
            title_hits,
            abstract_hits,
            matched,
            needs_adjudication=True,
        )

    return RelevanceVerdict(
        OFF_TOPIC, "no seed term in title, abstract, MeSH or keywords", title_hits, abstract_hits
    )


def is_included(relevance: str, *, include_mentions: bool = False) -> bool:
    """Whether a verdict should proceed to acquisition."""
    if relevance == STUDIES:
        return True
    if relevance == UNKNOWN:
        # Kept: an unjudgeable paper is a candidate until something judges it.
        return True
    if relevance == MENTIONS:
        return include_mentions
    return False
