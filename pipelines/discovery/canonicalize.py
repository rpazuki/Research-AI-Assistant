"""Turn many sources' records into one candidate per paper.

Three distinct jobs, in order:

1. **Identity.** Match records only on a *strong identifier* they share: DOI,
   PMID or PMCID. Never on title. A title is a string a publisher chose, and
   matching on it merged four separate peer-review reports into one row, two
   different book front-matter sections into another, and papers with their
   figshare/Zenodo data deposits — after which the row could carry the deposit's
   DOI as its identity. Owner decision (2026-07-30): ingesting a preprint and its
   published version twice is strictly better than merging two distinct works
   once, because a duplicate that cites itself correctly is harmless and a wrong
   merge is not.
2. **Merge.** Field by field, take the first non-empty value in source-trust order
   (`SOURCE_PRIORITY`): curated sources for journal and abstract, aggregators for
   OA status and retraction. Every contributing source is recorded in `found_in`,
   so a curator can see that a paper came only from Crossref.
3. **Preprint collapse.** A preprint is merged into its version of record only when
   an *authoritative* link says so — bioRxiv's `pubs` endpoint or a Crossref
   `relation`. Without a link the two rows both survive.
4. **Duplicate suspicion, recorded not acted on.** Candidates sharing a normalised
   title are flagged for a human (`possible_duplicate_of`) and left alone.

The measured target this exists to serve: the curated Yarrowia set is 723 rows over
706 unique DOIs — 10 of the rows are accidental re-curations of a DOI already
present, and step 1 must collapse exactly those.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field, replace

from pipelines.discovery.sources.base import (
    SOURCE_PRIORITY,
    SourceRecord,
    normalise_doi,
    normalise_title,
)

logger = logging.getLogger(__name__)

# A row's identity must be the work itself, never one of its attachments. These
# prefixes are data deposits and repository copies that carry the paper's title and
# arrive through OpenAlex (they are not in Crossref at all), so before the identity
# rule was tightened one of them could end up as a candidate's DOI.
DATA_DOI_PREFIXES = frozenset(
    {"10.6084", "10.5281", "10.17632", "10.5061", "10.6019", "10.25493", "10.24435"}
)
REPOSITORY_DOI_PREFIXES = frozenset(
    {"10.22028", "10.5445", "10.18419", "10.11588", "10.4233", "10.7302", "10.17169"}
)
PREPRINT_DOI_PREFIXES = frozenset(
    {
        "10.1101",   # bioRxiv / medRxiv
        "10.2139",   # SSRN
        "10.21203",  # Research Square
        "10.20944",  # Preprints.org
        "10.26434",  # ChemRxiv
        "10.31219",  # OSF
        "10.22541",  # Authorea
        "10.32388",  # Qeios
        "10.31235",  # SocArXiv
        "10.26226",  # Morressier
    }
)

# Lower sorts first, i.e. is preferred as the row's identity.
_DOI_CLASS_RANK = {"journal": 0, "preprint": 1, "repository": 2, "dataset": 3}


def doi_class(doi: str | None) -> str:
    """Classify a DOI by what kind of object it identifies."""
    if not doi:
        return "journal"
    prefix = doi.split("/", 1)[0]
    if prefix in DATA_DOI_PREFIXES:
        return "dataset"
    if prefix in REPOSITORY_DOI_PREFIXES:
        return "repository"
    if prefix in PREPRINT_DOI_PREFIXES:
        return "preprint"
    return "journal"


# Fields merged by "first non-empty in source-trust order".
_SCALAR_FIELDS = (
    "doi",
    "pmid",
    "pmc_id",
    "title",
    "abstract",
    "journal",
    "publisher",
    "year",
    "published_date",
    "oa_status",
    "license",
    "url",
    "version_of_record_doi",
    "preprint_doi",
)
_UNION_FIELDS = ("types", "mesh_terms", "keywords")


@dataclass
class Candidate:
    """One paper, as assembled from every source that returned it."""

    doi: str | None = None
    pmid: str | None = None
    pmc_id: str | None = None
    title: str | None = None
    abstract: str | None = None
    journal: str | None = None
    publisher: str | None = None
    year: int | None = None
    published_date: str | None = None
    types: tuple[str, ...] = ()
    mesh_terms: tuple[str, ...] = ()
    keywords: tuple[str, ...] = ()
    oa_status: str | None = None
    license: str | None = None
    url: str | None = None
    is_preprint: bool = False
    preprint_doi: str | None = None
    version_of_record_doi: str | None = None
    is_retracted: bool = False
    retraction_note: str | None = None
    found_in: tuple[str, ...] = ()
    dedupe_group: str | None = None
    merged_identifiers: tuple[str, ...] = ()
    # Filled by doctype.py / relevance.py, which run after canonicalisation.
    doc_type: str | None = None
    is_review: bool = False
    relevance: str = "unknown"
    relevance_reason: str | None = None
    # Suspicion only. Set by `flag_possible_duplicates`, never acted on: a human
    # decides whether two rows are the same work.
    possible_duplicate_of: tuple[str, ...] = ()
    duplicate_evidence: str | None = None
    extra: dict = field(default_factory=dict)

    @property
    def searchable_text(self) -> str:
        return " ".join(part for part in (self.title, self.abstract) if part)


def _source_rank(source: str) -> int:
    try:
        return SOURCE_PRIORITY.index(source)
    except ValueError:
        return len(SOURCE_PRIORITY)


def _identity_keys(record: SourceRecord) -> list[str]:
    """Every strong identifier this record can be matched on, strongest first.

    Strong means assigned by a registrar: DOI, PMID, PMCID. Titles are excluded on
    purpose — see the module docstring. A record with no strong identifier is its
    own candidate rather than being guessed into someone else's.
    """
    keys: list[str] = []
    if record.doi:
        keys.append(f"doi:{record.doi}")
    if record.pmid:
        keys.append(f"pmid:{record.pmid}")
    if record.pmc_id:
        keys.append(f"pmcid:{record.pmc_id}")
    return keys


def merge_records(records: list[SourceRecord]) -> Candidate:
    """Merge records already known to describe the same paper."""
    ordered = sorted(records, key=lambda record: _source_rank(record.source))
    candidate = Candidate()

    for name in _SCALAR_FIELDS:
        for record in ordered:
            value = getattr(record, name)
            if value not in (None, ""):
                setattr(candidate, name, value)
                break

    # The DOI is the row's identity and its citation, so it is chosen by what the
    # DOI *identifies* first and source trust second. Records only reach here by
    # sharing an identifier, so this is a tie-break between spellings of the same
    # work — never a guess about which work it is.
    candidate_dois = [record.doi for record in ordered if record.doi]
    if candidate_dois:
        candidate.doi = min(
            candidate_dois,
            key=lambda value: (
                _DOI_CLASS_RANK.get(doi_class(value), len(_DOI_CLASS_RANK)),
                candidate_dois.index(value),
            ),
        )

    for name in _UNION_FIELDS:
        merged: list[str] = []
        seen: set[str] = set()
        for record in ordered:
            for value in getattr(record, name) or ():
                key = str(value).casefold()
                if value and key not in seen:
                    seen.add(key)
                    merged.append(str(value))
        setattr(candidate, name, tuple(merged))

    # A retraction claimed by any source is kept: a false negative here puts a
    # retracted paper into the datasheet, which is worse than a spurious flag a
    # curator can clear.
    for record in ordered:
        if record.is_retracted:
            candidate.is_retracted = True
            candidate.retraction_note = record.retraction_note or candidate.retraction_note
            break

    # Preprint status is a property of the record, not of the paper: if any source
    # has it as a journal article, it is one.
    candidate.is_preprint = all(record.is_preprint for record in ordered)
    if not candidate.is_preprint:
        for record in ordered:
            if record.is_preprint and record.doi:
                candidate.preprint_doi = candidate.preprint_doi or record.doi
                break

    candidate.found_in = tuple(
        dict.fromkeys(record.source for record in ordered)  # preserves trust order
    )
    candidate.extra = {
        record.source: record.extra for record in ordered if record.extra
    }
    return candidate


def group_records(records: list[SourceRecord]) -> list[list[SourceRecord]]:
    """Group records by paper identity, transitively.

    Transitivity matters: Crossref may supply only a DOI and PubMed only a PMID for
    the same paper, joined by a third record carrying both. A naive
    group-by-strongest-key would leave those as two candidates.
    """
    groups: list[list[SourceRecord]] = []
    key_to_group: dict[str, int] = {}

    for record in records:
        keys = _identity_keys(record)
        if not keys:
            groups.append([record])
            continue

        existing = sorted({key_to_group[key] for key in keys if key in key_to_group})
        if not existing:
            index = len(groups)
            groups.append([record])
        else:
            index = existing[0]
            groups[index].append(record)
            # Fold any other groups this record links into the first one.
            for other in existing[1:]:
                groups[index].extend(groups[other])
                groups[other] = []
                for mapped_key, mapped_index in key_to_group.items():
                    if mapped_index == other:
                        key_to_group[mapped_key] = index

        for key in keys:
            key_to_group[key] = index

    return [group for group in groups if group]


def canonicalise(records: list[SourceRecord]) -> list[Candidate]:
    """Group, merge, and label each candidate with its dedupe group."""
    candidates: list[Candidate] = []
    for group in group_records(records):
        candidate = merge_records(group)
        keys = sorted({key for record in group for key in _identity_keys(record)})
        candidate.dedupe_group = keys[0] if keys else None
        candidate.merged_identifiers = tuple(keys)
        candidates.append(candidate)

    logger.info(
        "canonicalise: %d source records -> %d candidates", len(records), len(candidates)
    )
    return candidates


def collapse_preprints(
    candidates: list[Candidate],
    *,
    resolve_version_of_record=None,
) -> list[Candidate]:
    """Merge preprints into their version of record.

    `resolve_version_of_record(doi) -> dict | None` is injected (normally
    ``sources.biorxiv.fetch_version_of_record``) so this stays pure and testable;
    it is only consulted for preprint candidates that do not already carry a VoR
    link from Crossref.
    """
    by_doi = {candidate.doi: candidate for candidate in candidates if candidate.doi}
    survivors: list[Candidate] = []
    collapsed = 0

    for candidate in candidates:
        vor_doi = candidate.version_of_record_doi
        if candidate.is_preprint and not vor_doi and resolve_version_of_record and candidate.doi:
            found = resolve_version_of_record(candidate.doi)
            vor_doi = normalise_doi((found or {}).get("published_doi"))

        target = by_doi.get(vor_doi) if vor_doi else None
        if candidate.is_preprint and target is not None and target is not candidate:
            # Keep the preprint's identifiers and full text route on the VoR row.
            target.preprint_doi = target.preprint_doi or candidate.doi
            target.found_in = tuple(dict.fromkeys(target.found_in + candidate.found_in))
            target.merged_identifiers = tuple(
                sorted(set(target.merged_identifiers) | set(candidate.merged_identifiers))
            )
            target.abstract = target.abstract or candidate.abstract
            target.is_retracted = target.is_retracted or candidate.is_retracted
            collapsed += 1
            continue

        if candidate.is_preprint and vor_doi and target is None:
            # The VoR was not discovered; record the link so a refresh can promote it.
            candidate.version_of_record_doi = vor_doi

        survivors.append(candidate)

    if collapsed:
        logger.info("collapse_preprints: merged %d preprints into their published version", collapsed)
    return survivors




# Titles that identify a class of object rather than a work. A title match on one of
# these means nothing, so flagging it would only train a curator to ignore the flag.
_GENERIC_TITLE_PATTERNS = (
    "front matter",
    "back matter",
    "editorial board",
    "table of contents",
    "issue information",
    "author index",
    "subject index",
    "acknowledgement to reviewers",
)


def flag_possible_duplicates(candidates: list[Candidate]) -> int:
    """Mark candidates that *might* be the same work. Never merges them.

    Two rows sharing a normalised title are the interesting case: a preprint and
    its published version whose link no registry recorded, a translation pair, or
    two genuinely different papers that happen to share a title. The pipeline
    cannot tell which, so it records the suspicion with its evidence and leaves the
    decision to a human — the whole reason title matching was removed from
    identity.

    Skips candidates already classified `other` (front matter, peer-review reports,
    datasets): those collide by the dozen and a flag on them is noise, not signal.
    """
    from pipelines.discovery import doctype  # local import: doctype imports nothing here

    groups: dict[str, list[Candidate]] = {}
    for candidate in candidates:
        if candidate.doc_type == doctype.OTHER:
            continue
        title = normalise_title(candidate.title)
        if not title or len(title) < 25 or any(
            pattern in title for pattern in _GENERIC_TITLE_PATTERNS
        ):
            continue
        groups.setdefault(title, []).append(candidate)

    flagged = 0
    for group in groups.values():
        if len(group) < 2:
            continue
        for candidate in group:
            others = [
                other.doi or other.pmid or "unidentified"
                for other in group
                if other is not candidate
            ]
            if not others:
                continue
            candidate.possible_duplicate_of = tuple(sorted(set(others)))
            years = {other.year for other in group if other.year}
            candidate.duplicate_evidence = (
                "same normalised title as "
                + ", ".join(candidate.possible_duplicate_of)
                + (f" (years {sorted(years)})" if len(years) > 1 else "")
            )
            flagged += 1

    if flagged:
        logger.info(
            "flag_possible_duplicates: %d candidates share a title with another; "
            "left unmerged for review",
            flagged,
        )
    return flagged



def candidate_with(candidate: Candidate, **updates) -> Candidate:
    """Copy with fields replaced — for callers that prefer not to mutate."""
    return replace(candidate, **updates)
