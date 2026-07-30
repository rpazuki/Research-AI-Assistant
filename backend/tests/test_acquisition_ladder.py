"""Tests for S3: rate limiting, the acquisition ladder, and text extraction.

Offline. The policies under test are the ones that protect other people — never
retrying a 403, breaking the circuit after three, honouring `Retry-After` — so
they are tested by counting requests, not by trusting the code reads right.
"""

from __future__ import annotations

import httpx
import pytest

from pipelines.acquisition import clients, extract_text
from pipelines.acquisition.ladder import (
    STATUS_ASSISTED,
    STATUS_FAILED,
    STATUS_FETCHED,
    AcquisitionTarget,
    LadderConfig,
    acquire,
    resolver_url,
)
from pipelines.acquisition.ratelimit import (
    MAX_CONSECUTIVE_BLOCKS,
    Outcome,
    RateLimiter,
)

JATS = b"""<?xml version="1.0"?>
<article>
  <front><article-meta><title-group>
    <article-title>Engineering <italic>Yarrowia lipolytica</italic> Po1g-&#916;ku70</article-title>
  </title-group>
  <abstract><p>Titre reached 488.7 mg/L.</p></abstract>
  </article-meta></front>
  <body>
    <sec><title>Introduction</title><p>Others reported 1200 mg/L in S. cerevisiae.</p></sec>
    <sec><title>Materials and Methods</title><p>Strain Po1g-&#916;ku70 was grown at 28 &#176;C.</p></sec>
    <sec><title>Results and Discussion</title><p>We obtained 488.7 mg/L hesperetin.</p></sec>
  </body>
</article>
"""


def limiter(**kwargs) -> RateLimiter:
    """A limiter whose sleeps are free, so tests measure policy not wall time."""
    kwargs.setdefault("respect_robots", False)
    kwargs.setdefault("sleep", lambda _seconds: None)
    return RateLimiter(**kwargs)


def transport(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


# ── Rate limiter policy ───────────────────────────────────────────────────────


def test_a_403_is_never_retried() -> None:
    """Measured: publisher 403s arrive on the *first* request — fingerprinting, not
    throughput. Retrying turns a per-request block into an IP-range block that
    affects colleagues."""
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(403, text="Access denied")

    with transport(handler) as client:
        result = limiter().fetch("https://publisher.example/article.pdf", client=client)

    assert len(calls) == 1
    assert result.outcome is Outcome.BLOCKED


def test_a_server_error_is_retried_once() -> None:
    calls: list[int] = []

    def handler(_request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(503)

    with transport(handler) as client:
        result = limiter().fetch("https://api.example/x", client=client)

    assert len(calls) == 2  # MAX_ATTEMPTS
    assert result.outcome is Outcome.ERROR


def test_retry_after_is_honoured_rather_than_a_fixed_backoff() -> None:
    """The server said how long to wait; exponential backoff would ignore it."""
    slept: list[float] = []

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, headers={"Retry-After": "7"})

    with transport(handler) as client:
        RateLimiter(respect_robots=False, sleep=slept.append).fetch(
            "https://api.example/x", client=client
        )

    assert 7.0 in slept


def test_an_absurd_retry_after_is_capped() -> None:
    slept: list[float] = []

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, headers={"Retry-After": "86400"})

    with transport(handler) as client:
        RateLimiter(respect_robots=False, sleep=slept.append).fetch(
            "https://api.example/x", client=client
        )

    assert max(slept) <= 120.0


def test_three_consecutive_blocks_open_the_circuit() -> None:
    """This is what stops 48 MDPI papers producing 48 × 403."""
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(403)

    active = limiter()
    with transport(handler) as client:
        for index in range(6):
            active.fetch(f"https://mdpi.example/paper{index}.pdf", client=client)

    assert len(calls) == MAX_CONSECUTIVE_BLOCKS
    tally = active.tally_for("mdpi.example")
    assert tally.circuit_open
    assert tally.blocked == MAX_CONSECUTIVE_BLOCKS


def test_a_success_resets_the_block_streak() -> None:
    responses = iter([403, 403, 200, 403])

    def handler(_request: httpx.Request) -> httpx.Response:
        status = next(responses)
        return httpx.Response(status, content=b"%PDF-1.4 ok" if status == 200 else b"")

    active = limiter()
    with transport(handler) as client:
        for _ in range(4):
            active.fetch("https://publisher.example/x", client=client)

    assert not active.tally_for("publisher.example").circuit_open


def test_each_host_has_its_own_circuit() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403 if "blocked" in str(request.url) else 200, content=b"data")

    active = limiter()
    with transport(handler) as client:
        for _ in range(MAX_CONSECUTIVE_BLOCKS):
            active.fetch("https://blocked.example/x", client=client)
        ok = active.fetch("https://open.example/x", client=client)

    assert active.tally_for("blocked.example").circuit_open
    assert not active.tally_for("open.example").circuit_open
    assert ok.outcome is Outcome.SUCCESS


def test_a_per_host_request_budget_stops_a_runaway() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"data")

    active = limiter(max_requests_per_host=3)
    with transport(handler) as client:
        outcomes = [
            active.fetch("https://api.example/x", client=client).outcome for _ in range(5)
        ]

    assert outcomes.count(Outcome.SUCCESS) == 3
    assert outcomes.count(Outcome.OVER_BUDGET) == 2


def test_cancelling_stops_further_requests() -> None:
    active = limiter()
    active.cancel()
    with transport(lambda _r: httpx.Response(200)) as client:
        assert active.fetch("https://api.example/x", client=client).outcome is Outcome.OVER_BUDGET


def test_publisher_hosts_get_the_slowest_interval() -> None:
    """Documented quotas are honourable; an unknown host is a publisher until
    proven otherwise."""
    active = limiter()
    assert active.min_interval_for("api.crossref.org") == 0.05
    assert active.min_interval_for("some-publisher.example") == 3.0
    assert active.min_interval_for("eutils.ncbi.nlm.nih.gov", url="?api_key=k") == 0.10


def test_robots_disallow_is_respected() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nDisallow: /pdf/")
        return httpx.Response(200, content=b"%PDF-")

    active = RateLimiter(respect_robots=True, sleep=lambda _s: None)
    with transport(handler) as client:
        blocked = active.fetch("https://host.example/pdf/a.pdf", client=client)
        allowed = active.fetch("https://host.example/xml/a.xml", client=client)

    assert blocked.outcome is Outcome.DISALLOWED
    assert allowed.outcome is Outcome.SUCCESS


def test_an_unreadable_robots_txt_does_not_block_open_access_content() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(500)
        return httpx.Response(200, content=b"data")

    active = RateLimiter(respect_robots=True, sleep=lambda _s: None)
    with transport(handler) as client:
        assert active.fetch("https://host.example/a.xml", client=client).outcome is Outcome.SUCCESS


def test_tallies_make_blocks_visible() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403 if "wiley" in str(request.url) else 200, content=b"data")

    active = limiter()
    with transport(handler) as client:
        active.fetch("https://wiley.example/a.pdf", client=client)
        active.fetch("https://europepmc.example/a.xml", client=client)

    tallies = {row["host"]: row for row in active.tallies()}
    assert tallies["wiley.example"]["blocked"] == 1
    assert tallies["europepmc.example"]["successes"] == 1


# ── Ladder ────────────────────────────────────────────────────────────────────


def ladder_config(**kwargs) -> LadderConfig:
    kwargs.setdefault("unpaywall_email", "lab@example.ac.uk")
    return LadderConfig(**kwargs)


def test_the_ladder_stops_at_the_first_success() -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(200, content=JATS, headers={"content-type": "application/xml"})

    with transport(handler) as client:
        outcome = acquire(
            AcquisitionTarget(doi="10.1/x", pmc_id="PMC1"),
            config=ladder_config(),
            limiter=limiter(),
            client=client,
        )

    assert outcome.status == STATUS_FETCHED
    assert outcome.route == "pmc_oa"
    assert outcome.content_format == "xml"
    assert len(calls) == 1  # nothing below the first rung was touched


def test_a_paywalled_paper_becomes_assisted_not_failed() -> None:
    """Most of a 46%-paywalled corpus lands here. A failure looks like a bug to
    fix; an assisted row looks like work to do, and only one of those is true."""

    def handler(request: httpx.Request) -> httpx.Response:
        if "unpaywall" in str(request.url):
            return httpx.Response(200, json={"best_oa_location": None, "oa_locations": []})
        return httpx.Response(404)

    with transport(handler) as client:
        outcome = acquire(
            AcquisitionTarget(doi="10.1016/paywalled"),
            config=ladder_config(resolver_url_template="https://libkey.io/libraries/1/{doi}"),
            limiter=limiter(),
            client=client,
        )

    assert outcome.status == STATUS_ASSISTED
    assert outcome.resolver_url == "https://libkey.io/libraries/1/10.1016/paywalled"
    assert outcome.attempts  # every rung tried is recorded


def test_a_blocked_paper_says_so_in_its_reason() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if "unpaywall.org" in str(request.url):
            return httpx.Response(200, json={"best_oa_location": {"url_for_pdf": "https://mdpi.example/a.pdf"}})
        if "mdpi.example" in str(request.url):
            return httpx.Response(403)
        return httpx.Response(404)

    with transport(handler) as client:
        outcome = acquire(
            AcquisitionTarget(doi="10.3390/blocked"),
            config=ladder_config(),
            limiter=limiter(),
            client=client,
        )

    assert outcome.status == STATUS_ASSISTED
    assert "blocked by publisher protection" in outcome.detail


def test_a_candidate_without_a_doi_cannot_be_assisted() -> None:
    """No DOI means no resolver link, so there is nothing a human could open."""
    with transport(lambda _r: httpx.Response(404)) as client:
        outcome = acquire(
            AcquisitionTarget(pmid="123"),
            config=ladder_config(),
            limiter=limiter(),
            client=client,
        )
    assert outcome.status == STATUS_FAILED


def test_a_cached_asset_is_never_re_requested() -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(200, content=JATS)

    with transport(handler) as client:
        outcome = acquire(
            AcquisitionTarget(doi="10.1/x", pmc_id="PMC1"),
            config=ladder_config(),
            limiter=limiter(),
            client=client,
            cached_asset=lambda _target: (JATS, "xml", "pmc_oa"),
        )

    assert calls == []
    assert outcome.status == STATUS_FETCHED
    assert "already cached" in outcome.detail


def test_the_preprint_rung_reaches_a_paywalled_papers_free_text() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if "biorxiv.org" in str(request.url):
            return httpx.Response(200, content=JATS, headers={"content-type": "application/xml"})
        return httpx.Response(404)

    with transport(handler) as client:
        outcome = acquire(
            AcquisitionTarget(doi="10.1016/vor", preprint_doi="10.1101/2025.01.01.000001"),
            config=ladder_config(),
            limiter=limiter(),
            client=client,
        )

    assert outcome.status == STATUS_FETCHED
    assert outcome.route == "biorxiv"


def test_publisher_tdm_is_inert_without_a_key() -> None:
    attempt = clients.fetch_publisher_tdm(
        doi="10.1016/x", api_key=None, limiter=limiter(), client=None
    )
    assert attempt.outcome is Outcome.BLOCKED
    assert "blocked_needs_entitlement" in attempt.detail


def test_a_tdm_stub_response_is_not_treated_as_full_text() -> None:
    """Measured: Elsevier serves a ~2 KB stub to an unentitled caller, with 200."""

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"<full-text-retrieval-response/>")

    with transport(handler) as client:
        attempt = clients.fetch_publisher_tdm(
            doi="10.1016/x", api_key="key", limiter=limiter(), client=client
        )

    assert attempt.outcome is Outcome.BLOCKED
    assert "stub" in attempt.detail


def test_a_pmc_record_without_a_body_is_a_miss_not_a_success() -> None:
    """Ingesting it would put an empty document in the corpus."""

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"<pmc-articleset><article><front/></article></pmc-articleset>")

    with transport(handler) as client:
        attempt = clients.fetch_pmc_oa(pmc_id="PMC1", limiter=limiter(), client=client)

    assert attempt.outcome is Outcome.NOT_FOUND


def test_an_html_landing_page_is_not_accepted_as_full_text() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if "unpaywall.org" in str(request.url):
            return httpx.Response(200, json={"best_oa_location": {"url": "https://pub.example/landing"}})
        return httpx.Response(
            200, content=b"<!doctype html><html>Buy this article</html>",
            headers={"content-type": "text/html"},
        )

    with transport(handler) as client:
        attempt = clients.fetch_unpaywall(
            doi="10.1/x", email="a@b.c", limiter=limiter(), client=client
        )

    assert attempt.outcome is Outcome.NOT_FOUND
    assert "not a document" in attempt.detail


def test_the_resolver_falls_back_to_doi_org_without_a_template() -> None:
    """Open item (a) is not a blocker: one extra click, not a lost paper."""
    assert resolver_url("10.1/x", None) == "https://doi.org/10.1/x"
    assert resolver_url("10.1/x", "https://libkey.io/l/9/{doi}") == "https://libkey.io/l/9/10.1/x"
    assert resolver_url(None, None) is None


# ── Text extraction ───────────────────────────────────────────────────────────


def test_jats_sections_are_labelled() -> None:
    document = extract_text.extract(JATS, "xml")

    assert document.labels() == ["abstract", "introduction", "methods", "results"]
    assert "488.7 mg/L" in document.section_text("results")
    assert "28 °C" in document.section_text("methods")


def test_extraction_can_exclude_the_introduction() -> None:
    """The precision guard: an Introduction reporting someone else's 1200 mg/L,
    attributed to this paper's authors, is a wrong datasheet row."""
    document = extract_text.extract(JATS, "xml")

    selected = document.section_text("methods", "results")
    assert "488.7" in selected
    assert "1200 mg/L" not in selected


def test_inline_markup_content_survives() -> None:
    """`<italic>Y. lipolytica</italic>` is the organism name, not decoration."""
    document = extract_text.extract(JATS, "xml")
    assert "Yarrowia lipolytica" in document.title


def test_a_delta_in_a_strain_name_survives_jats() -> None:
    document = extract_text.extract(JATS, "xml")
    report = extract_text.character_fidelity(document.title + document.full_text)

    assert "Po1g-Δku70" in document.title
    assert report.delta_count >= 2
    assert not report.looks_corrupted


def test_a_transliterated_strain_name_is_flagged_as_corruption() -> None:
    """`Po1g-Dku70` is a different strain, and nothing downstream could tell."""
    report = extract_text.character_fidelity("Strain Po1g-Dku70 was grown at 28 C.")

    assert report.suspicious_strain_names == ["Po1g-Dku70"]
    assert report.looks_corrupted


def test_replacement_characters_are_counted_as_corruption() -> None:
    assert extract_text.character_fidelity("28 �C, 5 �mol").looks_corrupted


def test_a_jats_document_with_no_body_is_reported_not_silently_empty() -> None:
    document = extract_text.extract(b"<article><front/></article>", "xml")

    assert document.sections == []
    assert any("no <body>" in warning for warning in document.warnings)


def test_unparseable_xml_is_a_warning_not_an_exception() -> None:
    document = extract_text.extract(b"<article", "xml")
    assert any("unparseable" in warning for warning in document.warnings)


@pytest.mark.parametrize(
    ("heading", "expected"),
    [
        ("Materials and Methods", extract_text.SECTION_METHODS),
        ("2. Experimental", extract_text.SECTION_METHODS),
        ("Results", extract_text.SECTION_RESULTS),
        ("Results and Discussion", extract_text.SECTION_METHODS if False else extract_text.SECTION_RESULTS),
        ("Discussion", extract_text.SECTION_DISCUSSION),
        ("Background", extract_text.SECTION_INTRO),
        ("Supporting Information", extract_text.SECTION_SUPPLEMENTARY),
        ("Acknowledgements", extract_text.SECTION_OTHER),
    ],
)
def test_section_heading_classification(heading: str, expected: str) -> None:
    assert extract_text.classify_heading(heading) == expected


def test_a_scanned_pdf_says_it_needs_ocr() -> None:
    """Silently returning empty text would put a blank document in the corpus."""
    minimal_pdf = (
        b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
        b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
        b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 200 200]>>endobj\n"
        b"trailer<</Root 1 0 R>>"
    )
    document = extract_text.extract(minimal_pdf, "pdf")
    assert document.source_format == "pdf"
    assert document.warnings


def test_an_unknown_format_is_reported() -> None:
    document = extract_text.extract(b"data", "docx")
    assert any("no extractor" in warning for warning in document.warnings)
