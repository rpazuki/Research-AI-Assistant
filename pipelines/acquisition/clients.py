"""Full-text routes, one function per rung of the ladder.

Each returns a `RouteAttempt` describing what happened, because the ladder needs
to distinguish "this route has nothing" from "this host blocked us" — the first
means try the next rung, the second means stop touching that host and send the
paper to assisted acquisition.

Ordered by preference, and the order is about *format* as much as availability:
XML keeps `Po1g-Δku70` and table structure that PDF extraction mangles.

    1 PMC OA        JATS XML for the PMC open-access subset
    2 Europe PMC    JATS XML; a different subset from PMC's, so worth its own rung
    3 bioRxiv       JATS for a preprint — often the only free text for a paywalled VoR
    4 Unpaywall     the OA location a publisher or repository actually serves
    5 publisher TDM inert without a key; logs `blocked_needs_entitlement`
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from urllib.parse import quote

import httpx

from pipelines.acquisition.ratelimit import FetchResult, Outcome, RateLimiter

logger = logging.getLogger(__name__)

PMC_OA_XML_URL = "https://www.ncbi.nlm.nih.gov/pmc/oai/oai.cgi"
EUTILS_EFETCH = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
EUROPEPMC_FULLTEXT = "https://www.ebi.ac.uk/europepmc/webservices/rest/{source}/{pid}/fullTextXML"
BIORXIV_JATS = "https://www.biorxiv.org/content/{doi}v{version}.source.xml"
UNPAYWALL_URL = "https://api.unpaywall.org/v2/{doi}"

# What a route can produce. `xml` is preferred everywhere it is available.
FORMAT_XML = "xml"
FORMAT_PDF = "pdf"


@dataclass
class RouteAttempt:
    """One rung's result."""

    route: str
    outcome: Outcome
    content: bytes | None = None
    content_format: str | None = None
    source_url: str | None = None
    license: str | None = None
    detail: str | None = None

    @property
    def ok(self) -> bool:
        return self.outcome is Outcome.SUCCESS and bool(self.content)


def _looks_like_html(result: FetchResult) -> bool:
    """A publisher landing page, not the article.

    Both HTML and JATS start with `<`, so sniffing the first byte is not enough —
    and a landing page ingested as full text puts "Buy this article" in the corpus.
    """
    if result.content_type and "html" in result.content_type:
        return True
    head = (result.content or b"").lstrip()[:200].lower()
    return head.startswith(b"<!doctype html") or head.startswith(b"<html")


def _looks_like_xml(result: FetchResult) -> bool:
    if not result.content or _looks_like_html(result):
        return False
    if result.content_type and "xml" in result.content_type:
        return True
    return result.content.lstrip()[:200].startswith(b"<")


def _looks_like_pdf(result: FetchResult) -> bool:
    return bool(result.content and result.content[:5] == b"%PDF-")


def fetch_pmc_oa(
    *, pmc_id: str | None, limiter: RateLimiter, client: httpx.Client, api_key: str | None = None
) -> RouteAttempt:
    """JATS from PMC via efetch.

    efetch rather than the OA package service: it answers with the XML directly,
    and a closed-access PMC record returns an empty article set rather than an
    error, which is a clean "nothing here" signal.
    """
    if not pmc_id:
        return RouteAttempt("pmc_oa", Outcome.NOT_FOUND, detail="no PMCID")

    numeric = pmc_id.upper().removeprefix("PMC")
    result = limiter.fetch(
        EUTILS_EFETCH,
        client=client,
        accept="application/xml",
        params={"db": "pmc", "id": numeric, "retmode": "xml", "api_key": api_key},
    )
    if result.outcome is not Outcome.SUCCESS:
        return RouteAttempt("pmc_oa", result.outcome, detail=result.detail)

    body = result.content or b""
    # A record PMC holds but does not license for bulk access comes back as a stub
    # with no <body>; treating that as success would ingest an empty document.
    if b"<body" not in body:
        return RouteAttempt(
            "pmc_oa", Outcome.NOT_FOUND, detail="PMC returned metadata without a body"
        )

    return RouteAttempt(
        "pmc_oa",
        Outcome.SUCCESS,
        content=body,
        content_format=FORMAT_XML,
        source_url=result.url,
    )


def fetch_europepmc(
    *, pmc_id: str | None, limiter: RateLimiter, client: httpx.Client
) -> RouteAttempt:
    """JATS from Europe PMC. Its open subset is not identical to PMC's."""
    if not pmc_id:
        return RouteAttempt("europepmc", Outcome.NOT_FOUND, detail="no PMCID")

    url = EUROPEPMC_FULLTEXT.format(source="PMC", pid=pmc_id.upper())
    result = limiter.fetch(url, client=client, accept="application/xml")
    if result.outcome is not Outcome.SUCCESS or not _looks_like_xml(result):
        # Europe PMC 404s `fullTextXML` even when it reports `inEPMC=Y`; that is a
        # normal miss, not an error worth surfacing.
        return RouteAttempt(
            "europepmc",
            result.outcome if result.outcome is not Outcome.SUCCESS else Outcome.NOT_FOUND,
            detail=result.detail,
        )

    return RouteAttempt(
        "europepmc",
        Outcome.SUCCESS,
        content=result.content,
        content_format=FORMAT_XML,
        source_url=result.url,
    )


def fetch_biorxiv(
    *,
    preprint_doi: str | None,
    limiter: RateLimiter,
    client: httpx.Client,
    version: int = 1,
) -> RouteAttempt:
    """JATS for a bioRxiv/medRxiv preprint.

    Worth a rung of its own: when the version of record is paywalled, the preprint
    is frequently the only free full text, and it is served as XML.
    """
    if not preprint_doi or not preprint_doi.startswith("10.1101/"):
        return RouteAttempt("biorxiv", Outcome.NOT_FOUND, detail="not a bioRxiv DOI")

    url = BIORXIV_JATS.format(doi=preprint_doi, version=version)
    result = limiter.fetch(url, client=client, accept="application/xml")
    if result.outcome is not Outcome.SUCCESS or not _looks_like_xml(result):
        return RouteAttempt(
            "biorxiv",
            result.outcome if result.outcome is not Outcome.SUCCESS else Outcome.NOT_FOUND,
            detail=result.detail,
        )

    return RouteAttempt(
        "biorxiv",
        Outcome.SUCCESS,
        content=result.content,
        content_format=FORMAT_XML,
        source_url=result.url,
        license="preprint",
    )


def find_unpaywall_location(
    *, doi: str | None, email: str | None, limiter: RateLimiter, client: httpx.Client
) -> dict | None:
    """Ask Unpaywall for the best OA location. Metadata only — no publisher fetch."""
    if not doi or not email:
        return None

    result = limiter.fetch(
        UNPAYWALL_URL.format(doi=quote(doi, safe="/")),
        client=client,
        accept="application/json",
        params={"email": email},
    )
    if result.outcome is not Outcome.SUCCESS or not result.content:
        return None

    import json

    try:
        payload = json.loads(result.content)
    except ValueError:
        return None

    best = payload.get("best_oa_location") or {}
    locations = [best, *(payload.get("oa_locations") or [])]
    for location in locations:
        if location and (location.get("url_for_pdf") or location.get("url")):
            return location
    return None


def fetch_unpaywall(
    *,
    doi: str | None,
    email: str | None,
    limiter: RateLimiter,
    client: httpx.Client,
) -> RouteAttempt:
    """Fetch the OA copy Unpaywall points at.

    Two hosts are involved: Unpaywall (a documented API) and whoever hosts the
    file (often a publisher). The second is where a 403 is expected, and it is the
    publisher's tally and circuit breaker that record it — which is the point of
    keying limits on host rather than route.
    """
    location = find_unpaywall_location(doi=doi, email=email, limiter=limiter, client=client)
    if not location:
        return RouteAttempt("unpaywall", Outcome.NOT_FOUND, detail="no OA location")

    target = location.get("url_for_pdf") or location.get("url")
    result = limiter.fetch(target, client=client, accept="application/pdf")
    if result.outcome is not Outcome.SUCCESS:
        return RouteAttempt(
            "unpaywall",
            result.outcome,
            detail=result.detail or f"fetching {target}",
            source_url=target,
        )

    if _looks_like_xml(result):
        content_format = FORMAT_XML
    elif _looks_like_pdf(result):
        content_format = FORMAT_PDF
    else:
        # A landing page rather than the file: HTML that is neither JATS nor PDF.
        # Recording it as a miss keeps HTML boilerplate out of the corpus.
        return RouteAttempt(
            "unpaywall",
            Outcome.NOT_FOUND,
            detail=f"served {result.content_type or 'unknown content'}, not a document",
            source_url=target,
        )

    return RouteAttempt(
        "unpaywall",
        Outcome.SUCCESS,
        content=result.content,
        content_format=content_format,
        source_url=result.url,
        license=location.get("license"),
    )


def fetch_publisher_tdm(
    *, doi: str | None, api_key: str | None, limiter: RateLimiter, client: httpx.Client
) -> RouteAttempt:
    """Publisher text-and-data-mining APIs. Implemented, inert without a key.

    Kept as a rung so the ladder does not change shape when a key arrives. The
    access probe measured unauthenticated TDM links returning 0 articles out of 12
    (Elsevier serves a ~2 KB stub), so calling it without entitlement is not worth
    a request.
    """
    if not api_key:
        return RouteAttempt(
            "publisher_tdm",
            Outcome.BLOCKED,
            detail="blocked_needs_entitlement: no publisher TDM key configured",
        )
    if not doi:
        return RouteAttempt("publisher_tdm", Outcome.NOT_FOUND, detail="no DOI")

    result = limiter.fetch(
        f"https://api.elsevier.com/content/article/doi/{quote(doi, safe='/')}",
        client=client,
        accept="text/xml",
        params={"apiKey": api_key},
    )
    if result.outcome is not Outcome.SUCCESS or not _looks_like_xml(result):
        return RouteAttempt(
            "publisher_tdm",
            result.outcome if result.outcome is not Outcome.SUCCESS else Outcome.NOT_FOUND,
            detail=result.detail,
        )
    # The measured failure mode: a 200 with a stub body instead of the article.
    if len(result.content or b"") < 4096:
        return RouteAttempt(
            "publisher_tdm",
            Outcome.BLOCKED,
            detail=f"blocked_needs_entitlement: {len(result.content or b'')} byte stub",
        )

    return RouteAttempt(
        "publisher_tdm",
        Outcome.SUCCESS,
        content=result.content,
        content_format=FORMAT_XML,
        source_url=result.url,
    )
