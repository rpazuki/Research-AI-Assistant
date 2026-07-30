"""Shared HTTP plumbing for the discovery clients.

One place for the polite defaults every upstream expects: an identifying user
agent, a bounded timeout, retries only on transport errors and 5xx/429, and a
caller-supplied ``httpx.Client`` so tests can inject a transport instead of
reaching the network. Follows the retry shape already used by
``pipelines/ingestion/pmc_fulltext.py``.

Deliberately not a rate limiter — that is S3's per-host token bucket
(``pipelines/acquisition/ratelimit.py``). What is here is the request-level
politeness that every client needs regardless.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

import httpx

logger = logging.getLogger(__name__)

USER_AGENT = "RLALab-AI-Assistant/1.0 (Imperial College London; datasheet discovery)"
DEFAULT_TIMEOUT_S = 20.0
DEFAULT_MAX_ATTEMPTS = 3
RETRY_STATUS_CODES = frozenset({429, 500, 502, 503, 504})


# Minimum seconds between requests to the same host, from the published quotas
# (plan §6.5). Search APIs only — the acquisition ladder's token bucket, circuit
# breaker and robots handling land in S3 and supersede this for publisher hosts.
# Process-scoped on purpose: a per-call limiter with several callers multiplies
# real egress.
HOST_MIN_INTERVAL_S: dict[str, float] = {
    "eutils.ncbi.nlm.nih.gov": 0.35,  # 0.10 with an API key; see _min_interval_for
    "pubchem.ncbi.nlm.nih.gov": 0.25,
    "www.ebi.ac.uk": 0.15,
    "api.crossref.org": 0.10,
    "api.openalex.org": 0.10,
    "api.biorxiv.org": 1.00,
}
DEFAULT_MIN_INTERVAL_S = 0.25
NCBI_WITH_KEY_MIN_INTERVAL_S = 0.10

_throttle_lock = threading.Lock()
_last_request_at: dict[str, float] = {}


def _min_interval_for(host: str, url: str) -> float:
    interval = HOST_MIN_INTERVAL_S.get(host, DEFAULT_MIN_INTERVAL_S)
    if host.endswith("ncbi.nlm.nih.gov") and "api_key=" in url:
        return NCBI_WITH_KEY_MIN_INTERVAL_S
    return interval


def _throttle(url: str) -> None:
    """Sleep just long enough that this host's minimum interval is respected."""
    host = urlsplit(url).netloc.lower()
    if not host:
        return

    with _throttle_lock:
        interval = _min_interval_for(host, url)
        now = time.monotonic()
        earliest = _last_request_at.get(host, 0.0) + interval
        wait = earliest - now
        # Reserve the slot before releasing the lock so concurrent callers queue
        # rather than all waking to the same instant.
        _last_request_at[host] = max(now, earliest)

    if wait > 0:
        time.sleep(wait)


def reset_throttle() -> None:
    """Forget request history. Tests only."""
    with _throttle_lock:
        _last_request_at.clear()


class DiscoveryLookupError(RuntimeError):
    """An upstream lookup failed in a way the caller should surface, not swallow.

    Carries the upstream name so a route can say *which* service is down rather
    than reporting a generic failure.
    """

    def __init__(self, upstream: str, message: str) -> None:
        super().__init__(f"{upstream}: {message}")
        self.upstream = upstream
        self.message = message


@dataclass(frozen=True)
class HttpSettings:
    """Per-call knobs. Defaults are the polite ones; callers rarely change them."""

    timeout_s: float = DEFAULT_TIMEOUT_S
    max_attempts: int = DEFAULT_MAX_ATTEMPTS
    backoff_base_s: float = 0.5
    user_agent: str = USER_AGENT
    # Tests set this False so a mocked transport does not pay real sleeps.
    throttle: bool = True


def build_client(settings: HttpSettings | None = None) -> httpx.Client:
    """Create a client with the polite defaults. Caller owns closing it."""
    resolved = settings or HttpSettings()
    return httpx.Client(
        timeout=resolved.timeout_s,
        follow_redirects=True,
        headers={"User-Agent": resolved.user_agent, "Accept-Encoding": "gzip, deflate"},
    )


def get(
    url: str,
    *,
    upstream: str,
    params: Mapping[str, Any] | None = None,
    client: httpx.Client | None = None,
    settings: HttpSettings | None = None,
    allow_404: bool = False,
) -> httpx.Response | None:
    """GET with bounded retries.

    Returns ``None`` for a 404 when ``allow_404`` is set — several of these APIs
    use 404 to mean "no such compound", which is an answer, not a failure.
    Raises ``DiscoveryLookupError`` for anything else that does not succeed, so a
    dead upstream never masquerades as an empty result.
    """
    resolved = settings or HttpSettings()
    owns_client = client is None
    active = client or build_client(resolved)
    cleaned = {key: value for key, value in (params or {}).items() if value not in (None, "")}

    try:
        last_error: str = "no attempt made"
        for attempt in range(1, resolved.max_attempts + 1):
            try:
                if resolved.throttle:
                    _throttle(str(active.build_request("GET", url, params=cleaned).url))
                response = active.get(url, params=cleaned)
            except httpx.HTTPError as exc:
                last_error = f"{type(exc).__name__}: {exc}"
            else:
                if response.status_code == 404 and allow_404:
                    return None
                if response.status_code < 400:
                    return response
                last_error = f"HTTP {response.status_code}"
                if response.status_code not in RETRY_STATUS_CODES:
                    break

            if attempt < resolved.max_attempts:
                delay = resolved.backoff_base_s * (2 ** (attempt - 1))
                logger.warning(
                    "%s lookup attempt %d/%d failed (%s); retrying in %.1fs",
                    upstream,
                    attempt,
                    resolved.max_attempts,
                    last_error,
                    delay,
                )
                time.sleep(delay)

        raise DiscoveryLookupError(upstream, last_error)
    finally:
        if owns_client:
            active.close()


def get_json(
    url: str,
    *,
    upstream: str,
    params: Mapping[str, Any] | None = None,
    client: httpx.Client | None = None,
    settings: HttpSettings | None = None,
    allow_404: bool = False,
) -> Any | None:
    response = get(
        url,
        upstream=upstream,
        params=params,
        client=client,
        settings=settings,
        allow_404=allow_404,
    )
    if response is None:
        return None
    try:
        return response.json()
    except ValueError as exc:
        raise DiscoveryLookupError(upstream, f"response was not JSON: {exc}") from exc
