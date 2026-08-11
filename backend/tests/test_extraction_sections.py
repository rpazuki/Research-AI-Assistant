"""Section selection and budgeting — the precision guard in front of extraction.

What is asserted here is mostly what is *not* sent: Introduction and Discussion
describe other groups' work, and a number lifted from them is attributed to the
wrong paper in a way nothing downstream can detect.
"""

from pipelines.extraction.sections import (
    DEFAULT_MAX_SECTION_TOKENS,
    estimate_tokens,
    remaining_sections,
    select_sections,
)

PAYLOAD = {
    "source_format": "xml",
    "title": "Engineering Yarrowia lipolytica for lupeol production",
    "abstract": "We engineered Po1g-Δku70 and reached 488.7 mg/L.",
    "warnings": [],
    "sections": [
        {"label": "introduction", "heading": "Introduction", "text": "Previous work reported 400 mg/L lupeol."},
        {"label": "methods", "heading": "Materials and Methods", "text": "Strains were grown in YPD at 28 C."},
        {"label": "results", "heading": "Results", "text": "Titre reached 488.7 mg/L after 96 h."},
        {"label": "discussion", "heading": "Discussion", "text": "Compared with Zhang et al's 400 mg/L."},
        {"label": "supplementary", "heading": "Supplementary", "text": "Table S1 lists all strains."},
    ],
}


def test_selects_title_abstract_methods_results_and_si() -> None:
    result = select_sections(PAYLOAD)

    assert result.labels == ["title", "abstract", "methods", "results", "supplementary"]
    assert "Titre reached 488.7 mg/L" in result.text


def test_introduction_and_discussion_are_never_sent() -> None:
    """They describe *other* groups' results. A number taken from them is real and
    attributed to the wrong paper — invisible in the output."""
    result = select_sections(PAYLOAD)

    assert "Previous work reported 400 mg/L" not in result.text
    assert "Zhang et al" not in result.text
    assert "introduction" in result.omitted_labels
    assert "discussion" in result.omitted_labels


def test_each_block_is_labelled_so_evidence_section_is_not_a_guess() -> None:
    result = select_sections(PAYLOAD)

    assert "[methods]" in result.text
    assert "[results]" in result.text


def test_source_tier_reports_how_much_of_the_paper_was_read() -> None:
    assert select_sections(PAYLOAD).source_tier == "fulltext"

    abstract_only = {"title": "T", "abstract": "A", "sections": []}
    assert select_sections(abstract_only).source_tier == "abstract"

    title_only = {"title": "T", "abstract": "", "sections": []}
    assert select_sections(title_only).source_tier == "metadata"

    assert select_sections({"sections": []}).source_tier == "none"


def test_budget_drops_whole_sections_rather_than_truncating_mid_sentence() -> None:
    """Half a Methods section reads as a complete one to the model."""
    long_payload = {
        **PAYLOAD,
        "sections": [
            {"label": "methods", "heading": "Methods", "text": "word " * 4000},
            {"label": "results", "heading": "Results", "text": "Titre reached 488.7 mg/L."},
        ],
    }

    result = select_sections(long_payload, max_tokens=200)

    assert result.truncated is True
    # The oversized section goes entire; a later one that still fits is kept
    # rather than the walk stopping at the first overflow.
    assert result.dropped_for_budget == ["methods"]
    assert "word word" not in result.text
    assert "Titre reached 488.7 mg/L" in result.text


def test_a_single_oversized_section_is_still_sent() -> None:
    """Sending nothing is strictly worse than sending one long section; the
    overrun is reported instead."""
    payload = {"title": "", "abstract": "", "sections": [{"label": "methods", "text": "word " * 5000}]}

    result = select_sections(payload, max_tokens=100)

    assert result.labels == ["methods"]
    assert result.tokens > 100


def test_cap_does_not_engage_on_a_normal_paper() -> None:
    """S4 measured a median of 8,350 tokens of selected sections; the 24k cap is an
    outlier backstop, not the normal path."""
    result = select_sections(PAYLOAD, max_tokens=DEFAULT_MAX_SECTION_TOKENS)

    assert result.truncated is False


def test_provider_token_counter_is_used_when_supplied() -> None:
    calls: list[str] = []

    def counter(text: str) -> int:
        calls.append(text)
        return 7

    result = select_sections(PAYLOAD, count_tokens=counter, token_method="provider")

    assert result.token_method == "provider"
    assert result.tokens == 7 * len(result.included)
    assert calls


def test_estimate_is_flagged_as_an_estimate() -> None:
    assert select_sections(PAYLOAD).token_method == "estimated_from_chars"
    assert estimate_tokens("") == 0
    assert estimate_tokens("a" * 380) > 0


def test_remaining_sections_lists_what_a_second_pass_would_cover() -> None:
    result = select_sections(PAYLOAD)

    assert remaining_sections(PAYLOAD, result) == ["introduction", "discussion"]


def test_empty_sections_are_skipped() -> None:
    payload = {"title": "T", "abstract": "", "sections": [{"label": "methods", "text": "   "}]}

    assert select_sections(payload).labels == ["title"]
