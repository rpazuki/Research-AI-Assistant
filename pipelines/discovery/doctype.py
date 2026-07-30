"""Classify a candidate as primary research, review, or other.

Reviews matter because the datasheet records *measured* results — a review
reporting someone else's 488.7 mg/L would be attributed to the review's authors.
They are flagged rather than dropped: a review is a useful pointer to primary work,
and the curator decides.

Why this is not just a field lookup: Crossref types 702 and 704 (review-article
and book-review in its schema) are frequently deposited as plain
`journal-article`, so a type check alone misses a large share of reviews. Title
and abstract phrasing is the fallback, and it is checked in a defined order so the
reason is always the strongest evidence available.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

PRIMARY = "primary"
REVIEW = "review"
OTHER = "other"

# Source-declared types that settle the question on their own.
_REVIEW_TYPES = frozenset(
    {
        "review",
        "review-article",
        "book-review",
        "systematic review",
        "meta-analysis",
        "scoping review",
        "review literature as topic",
    }
)
_OTHER_TYPES = frozenset(
    {
        "editorial",
        "comment",
        "letter",
        "news",
        "published erratum",
        "erratum",
        "correction",
        "retraction of publication",
        "retraction",
        "preface",
        "paratext",
        "peer-review",
        "biography",
        "obituary",
        "congress",
        "abstract",
        "conference-abstract",
        "grant",
        "book",
        "book-chapter",
        "component",
        "dataset",
        "collection",
        "software",
        "physical-object",
        "image",
        "audiovisual",
        "report-component",
        "patent",
    }
)

# Title/abstract phrasing, ordered strongest first. Anchored to the front of the
# title where a bare word would over-match ("a review of the literature" in an
# abstract is weaker evidence than a title beginning "Review of").
_TITLE_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("title says systematic review", re.compile(r"\bsystematic (literature )?review\b", re.I)),
    ("title says meta-analysis", re.compile(r"\bmeta[- ]analys[ie]s\b", re.I)),
    ("title starts with review", re.compile(r"^\s*(a |an |the )?(mini[- ])?review\b", re.I)),
    ("title says review", re.compile(r"\b(review|overview)\s*(:|of|on)\b", re.I)),
    ("title says perspective", re.compile(r"^\s*(perspectives?|outlook|opinion|commentary)\b", re.I)),
    ("title says recent advances", re.compile(r"\b(recent (advances|progress|developments)|state of the art)\b", re.I)),
)
_ABSTRACT_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("abstract describes a review", re.compile(r"\b(this|the present) (review|paper reviews)\b", re.I)),
    ("abstract summarises literature", re.compile(r"\bwe (review|summari[sz]e) (the )?(recent |current )?(literature|advances|progress)\b", re.I)),
    ("abstract reports a search protocol", re.compile(r"\b(PRISMA|databases were searched|literature search was)\b", re.I)),
)


@dataclass(frozen=True)
class DocTypeVerdict:
    doc_type: str
    is_review: bool
    reason: str


def classify(
    *, types: tuple[str, ...] | list[str] = (), title: str | None = None, abstract: str | None = None
) -> DocTypeVerdict:
    lowered = {str(value).strip().casefold() for value in types if value}

    for value in lowered:
        if value in _REVIEW_TYPES:
            return DocTypeVerdict(REVIEW, True, f"source type '{value}'")
    for value in lowered:
        if value in _OTHER_TYPES:
            return DocTypeVerdict(OTHER, False, f"source type '{value}'")

    for reason, pattern in _TITLE_PATTERNS:
        if title and pattern.search(title):
            return DocTypeVerdict(REVIEW, True, reason)
    for reason, pattern in _ABSTRACT_PATTERNS:
        if abstract and pattern.search(abstract):
            return DocTypeVerdict(REVIEW, True, reason)

    return DocTypeVerdict(PRIMARY, False, "no review or non-article signal")
