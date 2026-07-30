"""Ordered route resolution: try each rung, stop at the first success.

The ladder's real job is not fetching — it is deciding what a *failure* means.
The corpus is 46% paywalled and a further ~126 papers sit behind bot protection
that returns 403 on the first request, so most papers will fail every automated
rung. Those must land as `assisted_pending` with a resolver URL a human can open,
never as `failed`: a failure looks like a bug to fix, an assisted row looks like
work to do, and only one of those is true.

    1 pmc_oa         JATS
    2 europepmc      JATS
    3 biorxiv        JATS (preprint of a paywalled VoR)
    4 unpaywall      publisher/repository OA copy
    5 publisher_tdm  inert without a key
    6 assisted       resolver URL for a human

Fetch-once: a paper whose asset is already in the cache is never re-requested,
across runs.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Callable

import httpx

from pipelines.acquisition import clients
from pipelines.acquisition.ratelimit import Outcome, RateLimiter

logger = logging.getLogger(__name__)

DEFAULT_LADDER: tuple[str, ...] = (
    "pmc_oa",
    "europepmc",
    "biorxiv",
    "unpaywall",
    "publisher_tdm",
)

# Acquisition statuses, matching `datasheet_candidates.acquisition_status`.
STATUS_FETCHED = "fetched"
STATUS_ASSISTED = "assisted_pending"
STATUS_BLOCKED = "blocked"
STATUS_FAILED = "failed"
STATUS_SKIPPED = "skipped"


@dataclass
class AcquisitionTarget:
    """What the ladder needs about one candidate."""

    doi: str | None = None
    pmid: str | None = None
    pmc_id: str | None = None
    preprint_doi: str | None = None
    title: str | None = None
    publisher: str | None = None


@dataclass
class AcquisitionOutcome:
    """What happened, in the shape the candidate row records."""

    status: str
    route: str | None = None
    content: bytes | None = None
    content_format: str | None = None
    source_url: str | None = None
    license: str | None = None
    resolver_url: str | None = None
    detail: str | None = None
    attempts: list[dict] = field(default_factory=list)

    @property
    def acquired(self) -> bool:
        return self.status == STATUS_FETCHED and bool(self.content)


@dataclass
class LadderConfig:
    routes: tuple[str, ...] = DEFAULT_LADDER
    unpaywall_email: str | None = None
    ncbi_api_key: str | None = None
    publisher_tdm_key: str | None = None
    resolver_url_template: str | None = None
    prefer_xml: bool = True


def resolver_url(doi: str | None, template: str | None) -> str | None:
    """The link a human opens to fetch a paper themselves.

    `template` is a LibKey/EZproxy pattern containing `{doi}`. With none configured
    this falls back to plain `doi.org` — one extra click through the institutional
    login, which is workable and is why the missing template never blocks a run.

    Never a scripted login: driving SSO with stored credentials is the fastest way
    to get the institution's IP range blocked, and it is credential handling that
    should not be automated.
    """
    if not doi:
        return None
    if template and "{doi}" in template:
        return template.replace("{doi}", doi)
    return f"https://doi.org/{doi}"


def acquire(
    target: AcquisitionTarget,
    *,
    config: LadderConfig,
    limiter: RateLimiter,
    client: httpx.Client,
    cached_asset: Callable[[AcquisitionTarget], tuple[bytes, str, str] | None] | None = None,
) -> AcquisitionOutcome:
    """Walk the ladder for one paper.

    `cached_asset(target) -> (content, format, route)` short-circuits everything:
    a document already under `assets/` is never re-requested, across runs.
    """
    if cached_asset is not None:
        cached = cached_asset(target)
        if cached:
            content, content_format, route = cached
            return AcquisitionOutcome(
                status=STATUS_FETCHED,
                route=route,
                content=content,
                content_format=content_format,
                detail="already cached; not re-requested",
            )

    attempts: list[dict] = []
    blocked_seen = False

    for route in config.routes:
        attempt = _run_route(route, target, config=config, limiter=limiter, client=client)
        attempts.append(
            {
                "route": route,
                "outcome": attempt.outcome.value,
                "detail": attempt.detail,
                "url": attempt.source_url,
            }
        )

        if attempt.ok:
            logger.info("acquired %s via %s (%s)", target.doi or target.pmid, route, attempt.content_format)
            return AcquisitionOutcome(
                status=STATUS_FETCHED,
                route=route,
                content=attempt.content,
                content_format=attempt.content_format,
                source_url=attempt.source_url,
                license=attempt.license,
                attempts=attempts,
            )

        if attempt.outcome in (Outcome.BLOCKED, Outcome.CIRCUIT_OPEN, Outcome.DISALLOWED):
            blocked_seen = True

    # Every automated route is exhausted. This is the expected path for most of a
    # paywalled corpus, so it is a queue entry, not a failure.
    link = resolver_url(target.doi, config.resolver_url_template)
    if link:
        return AcquisitionOutcome(
            status=STATUS_ASSISTED,
            resolver_url=link,
            detail=(
                "no automated route; blocked by publisher protection"
                if blocked_seen
                else "no automated open-access route"
            ),
            attempts=attempts,
        )

    return AcquisitionOutcome(
        status=STATUS_FAILED,
        detail="no DOI, so no resolver link can be generated",
        attempts=attempts,
    )


def _run_route(
    route: str,
    target: AcquisitionTarget,
    *,
    config: LadderConfig,
    limiter: RateLimiter,
    client: httpx.Client,
) -> clients.RouteAttempt:
    if route == "pmc_oa":
        return clients.fetch_pmc_oa(
            pmc_id=target.pmc_id, limiter=limiter, client=client, api_key=config.ncbi_api_key
        )
    if route == "europepmc":
        return clients.fetch_europepmc(pmc_id=target.pmc_id, limiter=limiter, client=client)
    if route == "biorxiv":
        return clients.fetch_biorxiv(
            preprint_doi=target.preprint_doi or target.doi, limiter=limiter, client=client
        )
    if route == "unpaywall":
        return clients.fetch_unpaywall(
            doi=target.doi, email=config.unpaywall_email, limiter=limiter, client=client
        )
    if route == "publisher_tdm":
        return clients.fetch_publisher_tdm(
            doi=target.doi, api_key=config.publisher_tdm_key, limiter=limiter, client=client
        )
    return clients.RouteAttempt(route, Outcome.NOT_FOUND, detail=f"unknown route '{route}'")
