"""
pipelines/extraction/sections.py
--------------------------------
Choose and budget the text of one paper for a single extraction call.

Two decisions are encoded here, both recorded in docs/DATASHEET_FEATURE_PLAN.md
§7.0 because a later implementer would plausibly reverse them.

**Section restriction is a precision guard, not a budget trick.** Introduction and
Discussion describe *other groups'* results ("previous work reported 400 mg/L
lupeol"), and reference lists are dense with compound names, strain names and
yields. Feeding either risks attributing another paper's numbers to this one — a
fabrication that is invisible in the output, because the number is real and only
the attribution is wrong. Selection is rule-based on section labels, so it is
deterministic and auditable rather than embedding-dependent.

**The token cap is an outlier backstop.** S4 measured a median of 8,350 tokens of
selected sections per paper, so a 24,000-token cap does not engage on the normal
path — only on reviews and unusually long papers. When it does engage, what was
dropped is reported rather than silently truncated, so a second pass can cover the
remaining sections for the cells the first pass left empty.

Pure: no database, no provider, no network. The token counter is injected so the
same code can run against the provider's tokeniser or a character estimate.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

# Canonical labels, mirroring pipelines/acquisition/extract_text.py. Kept as plain
# strings rather than imported so this module stays independent of the acquisition
# half of the pipeline.
SECTION_TITLE = "title"
SECTION_ABSTRACT = "abstract"
SECTION_METHODS = "methods"
SECTION_RESULTS = "results"
SECTION_SUPPLEMENTARY = "supplementary"

# Order matters twice over: it is the order the model reads, and it is the order
# sections are dropped in reverse when the cap engages. Title and abstract are
# first because they are small and orient everything after them.
DEFAULT_SECTIONS: tuple[str, ...] = (
    SECTION_TITLE,
    SECTION_ABSTRACT,
    SECTION_METHODS,
    SECTION_RESULTS,
    SECTION_SUPPLEMENTARY,
)

DEFAULT_MAX_SECTION_TOKENS = 24_000

# Only used when no provider tokeniser is supplied. Deliberately an underestimate
# of characters-per-token for scientific prose, so the fallback errs toward
# reporting a *higher* token count than the truth rather than overrunning a budget.
CHARS_PER_TOKEN_FALLBACK = 3.8

TokenCounter = Callable[[str], int]


def estimate_tokens(text: str) -> int:
    """Character-ratio token estimate, for when no provider tokeniser is available."""
    return int(len(text) / CHARS_PER_TOKEN_FALLBACK) if text else 0


@dataclass(frozen=True)
class SelectedSection:
    label: str
    heading: str | None
    text: str
    tokens: int


@dataclass
class SelectionResult:
    """What one extraction call will be given, and what it had to leave out."""

    text: str
    tokens: int
    included: list[SelectedSection] = field(default_factory=list)
    # Sections present in the document but not sent: either not in the selected
    # set, or dropped because the budget ran out.
    omitted_labels: list[str] = field(default_factory=list)
    dropped_for_budget: list[str] = field(default_factory=list)
    token_method: str = "estimated_from_chars"

    @property
    def truncated(self) -> bool:
        """True when the cap engaged. The caller decides whether a second pass over
        the dropped sections is worth it for the cells still empty."""
        return bool(self.dropped_for_budget)

    @property
    def labels(self) -> list[str]:
        return [section.label for section in self.included]

    @property
    def source_tier(self) -> str:
        """The strongest tier this text actually supports.

        A row built from an abstract is not a weaker full-text row, it is a
        different claim about how much the paper was read — and the datasheet
        reports it per row so a thin row is visibly thin.
        """
        body = {SECTION_METHODS, SECTION_RESULTS, SECTION_SUPPLEMENTARY}
        labels = set(self.labels)
        if labels & body:
            return "fulltext"
        if SECTION_ABSTRACT in labels:
            return "abstract"
        if SECTION_TITLE in labels:
            return "metadata"
        return "none"


def _section_block(label: str, heading: str | None, text: str) -> str:
    """Label every block explicitly.

    The model is told which section a fact came from and must echo that back as
    `evidence_section`; unlabelled prose would make that field a guess.
    """
    title = heading or label.capitalize()
    return f"## {title} [{label}]\n{text.strip()}"


def select_sections(
    payload: dict,
    *,
    sections: tuple[str, ...] = DEFAULT_SECTIONS,
    max_tokens: int = DEFAULT_MAX_SECTION_TOKENS,
    count_tokens: TokenCounter | None = None,
    token_method: str = "estimated_from_chars",
) -> SelectionResult:
    """Build the text for one extraction call from a stored full-text payload.

    `payload` is the JSON the acquisition ladder wrote to
    `<run>/fulltext/<stem>.json`: `{source_format, title, abstract, warnings,
    sections: [{label, heading, text}]}`.
    """
    counter = count_tokens or estimate_tokens
    wanted = tuple(sections)

    candidates: list[tuple[str, str | None, str]] = []
    if SECTION_TITLE in wanted and (payload.get("title") or "").strip():
        candidates.append((SECTION_TITLE, "Title", payload["title"].strip()))
    if SECTION_ABSTRACT in wanted and (payload.get("abstract") or "").strip():
        candidates.append((SECTION_ABSTRACT, "Abstract", payload["abstract"].strip()))

    available_labels: list[str] = []
    for section in payload.get("sections") or []:
        label = section.get("label") or "other"
        text = (section.get("text") or "").strip()
        if not text:
            continue
        available_labels.append(label)
        if label in wanted:
            candidates.append((label, section.get("heading"), text))

    included: list[SelectedSection] = []
    dropped: list[str] = []
    used = 0
    for label, heading, text in candidates:
        block = _section_block(label, heading, text)
        tokens = counter(block)
        if used + tokens > max_tokens and included:
            # Budget exhausted. Stop rather than truncating mid-sentence: half a
            # Methods section reads as a complete one to the model.
            dropped.append(label)
            continue
        if used + tokens > max_tokens and not included:
            # A single section larger than the whole budget. Take it anyway —
            # sending nothing is strictly worse — and report the overrun.
            included.append(SelectedSection(label, heading, block, tokens))
            used += tokens
            continue
        included.append(SelectedSection(label, heading, block, tokens))
        used += tokens

    omitted = sorted(
        {label for label in available_labels if label not in wanted}
        | {label for label in dropped}
    )

    return SelectionResult(
        text="\n\n".join(section.text for section in included),
        tokens=used,
        included=included,
        omitted_labels=omitted,
        dropped_for_budget=dropped,
        token_method=token_method if count_tokens else "estimated_from_chars",
    )


def remaining_sections(payload: dict, result: SelectionResult) -> list[str]:
    """Labels present in the document that the first pass did not send.

    This is the input to the escalation pass described in §7.0: a paper whose
    Methods and Results alone overflow the cap gets a second call covering what
    was left, scoped to the cells that came back empty.
    """
    sent = set(result.labels)
    present = [
        section.get("label") or "other"
        for section in (payload.get("sections") or [])
        if (section.get("text") or "").strip()
    ]
    ordered: list[str] = []
    for label in present:
        if label not in sent and label not in ordered:
            ordered.append(label)
    return ordered
