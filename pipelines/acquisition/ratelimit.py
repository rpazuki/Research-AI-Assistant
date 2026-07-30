"""Per-host politeness for the acquisition ladder.

This lands **before** the fetchers on purpose (plan §8.1): retrofitting throttling
onto working fetchers is how an IP block happens.

Two problems get conflated here, and only one is a rate limit.

**API quotas** (NCBI, Crossref, Unpaywall, OpenAlex) are documented and honourable.
A token bucket plus one in-flight request per host satisfies them.

**Publisher bot protection** is not a rate limit. The access probe recorded 126
HTTP 403s, received on the *first* request to those hosts — TLS/header
fingerprinting, not throughput. Slowing down does not help, and retrying turns a
per-request block into an IP-range block that affects colleagues. So:

* **403/401/402 are never retried.** They mean "not for scripts", and the paper is
  routed to assisted acquisition instead.
* **Three consecutive blocks trip a per-host circuit breaker** for the rest of the
  run — this is what stops 48 MDPI papers producing 48 × 403.
* `Retry-After` is honoured on 429/503, because tenacity-style exponential backoff
  ignores the header the server actually sent.
* Every request is tallied per host so blocks are visible in the UI, not silent.

Limits are process-scoped, which is only enforceable because one worker process
serves both the ingestion and datasheet queues.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

import httpx

logger = logging.getLogger(__name__)

USER_AGENT = "RLALab-AI-Assistant/1.0 (+mailto:{contact}; Imperial College London; datasheet acquisition)"

# Documented quotas, plan §6.5. Publisher hosts get the conservative default.
HOST_LIMITS: dict[str, float] = {
    "eutils.ncbi.nlm.nih.gov": 0.35,
    "www.ncbi.nlm.nih.gov": 0.35,
    "ftp.ncbi.nlm.nih.gov": 0.35,
    "api.crossref.org": 0.05,
    "api.openalex.org": 0.10,
    "api.unpaywall.org": 0.10,
    "www.ebi.ac.uk": 0.15,
    "api.biorxiv.org": 1.00,
    "www.biorxiv.org": 1.00,
    "www.medrxiv.org": 1.00,
}
PUBLISHER_MIN_INTERVAL_S = 3.0
NCBI_WITH_KEY_MIN_INTERVAL_S = 0.10

MAX_ATTEMPTS = 2
MAX_CONSECUTIVE_BLOCKS = 3
DEFAULT_TIMEOUT_S = 60.0
MAX_RETRY_AFTER_S = 120.0


class Outcome(str, Enum):
    """What happened, in the vocabulary the ladder and the UI use."""

    SUCCESS = "success"
    NOT_FOUND = "not_found"
    BLOCKED = "blocked"          # 401/402/403 — route to assisted, never retry
    RATE_LIMITED = "rate_limited"
    ERROR = "error"
    CIRCUIT_OPEN = "circuit_open"
    DISALLOWED = "disallowed"    # robots.txt said no
    OVER_BUDGET = "over_budget"


BLOCKED_STATUSES = frozenset({401, 402, 403})
RETRYABLE_STATUSES = frozenset({429, 500, 502, 503, 504})


@dataclass
class HostTally:
    """What the run did to one host. Surfaced per run so blocks are visible."""

    host: str
    requests: int = 0
    successes: int = 0
    blocked: int = 0
    rate_limited: int = 0
    errors: int = 0
    not_found: int = 0
    consecutive_blocks: int = 0
    circuit_open: bool = False
    total_latency_s: float = 0.0

    def as_dict(self) -> dict:
        return {
            "host": self.host,
            "requests": self.requests,
            "successes": self.successes,
            "blocked": self.blocked,
            "rate_limited": self.rate_limited,
            "errors": self.errors,
            "not_found": self.not_found,
            "circuit_open": self.circuit_open,
            "mean_latency_s": (
                round(self.total_latency_s / self.requests, 2) if self.requests else None
            ),
        }


@dataclass
class FetchResult:
    outcome: Outcome
    status_code: int | None = None
    content: bytes | None = None
    content_type: str | None = None
    url: str | None = None
    detail: str | None = None

    @property
    def ok(self) -> bool:
        return self.outcome is Outcome.SUCCESS and bool(self.content)


@dataclass
class RateLimiter:
    """One instance per run. Owns the buckets, the breakers and the tallies."""

    contact_email: str | None = None
    max_requests_per_host: int = 400
    respect_robots: bool = True
    timeout_s: float = DEFAULT_TIMEOUT_S
    # Injected in tests so a mocked transport pays no real delay.
    sleep: callable = time.sleep

    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)
    _last_request_at: dict[str, float] = field(default_factory=dict, repr=False)
    _tallies: dict[str, HostTally] = field(default_factory=dict, repr=False)
    _robots: dict[str, RobotFileParser | None] = field(default_factory=dict, repr=False)
    _cancelled: bool = False

    # ── introspection ────────────────────────────────────────────────────────

    def tallies(self) -> list[dict]:
        with self._lock:
            return [tally.as_dict() for tally in sorted(self._tallies.values(), key=lambda t: t.host)]

    def tally_for(self, host: str) -> HostTally:
        with self._lock:
            return self._tallies.setdefault(host, HostTally(host=host))

    def cancel(self) -> None:
        """Kill switch. A running job polls its own cancellation and calls this."""
        self._cancelled = True

    # ── policy ───────────────────────────────────────────────────────────────

    def min_interval_for(self, host: str, *, url: str = "") -> float:
        if host in HOST_LIMITS:
            if host.endswith("ncbi.nlm.nih.gov") and "api_key=" in url:
                return NCBI_WITH_KEY_MIN_INTERVAL_S
            return HOST_LIMITS[host]
        # Anything not on the documented-quota list is a publisher until proven
        # otherwise, and publishers get the slowest setting.
        return PUBLISHER_MIN_INTERVAL_S

    def user_agent(self) -> str:
        return USER_AGENT.format(contact=self.contact_email or "rlalab@imperial.ac.uk")

    def _throttle(self, host: str, url: str) -> None:
        """Sleep so this host's minimum interval holds. Concurrency is 1 per host:
        the slot is reserved under the lock, so callers queue instead of all waking
        at the same instant."""
        with self._lock:
            interval = self.min_interval_for(host, url=url)
            now = time.monotonic()
            earliest = self._last_request_at.get(host, 0.0) + interval
            wait = earliest - now
            self._last_request_at[host] = max(now, earliest)
        if wait > 0:
            self.sleep(wait)

    def _robots_allows(self, url: str, client: httpx.Client) -> bool:
        """Check robots.txt once per host per run, for publisher-direct fetches only.

        Documented APIs are exempt, and the reason is concrete: NCBI's E-utilities
        host serves `Disallow: /` — a rule aimed at crawlers indexing the site,
        while E-utilities is an API we are an intended client of, governed by its
        own usage policy (which the rate limits, `api_key` and contact address
        honour). Applying robots there disabled the ladder's most productive route
        and sent every PMC open-access paper to the assisted queue.

        A robots.txt we cannot read is treated as permissive: refusing to fetch
        open-access content because a server 500s on /robots.txt helps nobody.
        """
        parts = urlsplit(url)
        host = parts.netloc.lower()

        if not self.respect_robots or host in HOST_LIMITS:
            return True
        if host not in self._robots:
            parser: RobotFileParser | None = None
            try:
                response = client.get(
                    f"{parts.scheme}://{parts.netloc}/robots.txt", timeout=15.0
                )
                if response.status_code < 400 and response.text:
                    parser = RobotFileParser()
                    parser.parse(response.text.splitlines())
            except httpx.HTTPError as exc:
                logger.debug("robots.txt unavailable for %s: %s", host, exc)
            self._robots[host] = parser

        parser = self._robots.get(host)
        if parser is None:
            return True
        return parser.can_fetch(self.user_agent(), url)

    # ── the one entry point ──────────────────────────────────────────────────

    def fetch(
        self,
        url: str,
        *,
        client: httpx.Client,
        accept: str | None = None,
        params: dict | None = None,
    ) -> FetchResult:
        """GET a URL under the run's politeness policy.

        Never raises for an HTTP outcome: the ladder needs to know *why* a route
        failed so it can pick the next one, and "blocked" must be distinguishable
        from "not found".
        """
        if self._cancelled:
            return FetchResult(Outcome.OVER_BUDGET, detail="run cancelled")

        host = urlsplit(url).netloc.lower()
        tally = self.tally_for(host)

        if tally.circuit_open:
            return FetchResult(Outcome.CIRCUIT_OPEN, url=url, detail=f"{host} circuit open")
        if tally.requests >= self.max_requests_per_host:
            return FetchResult(
                Outcome.OVER_BUDGET,
                url=url,
                detail=f"{host} reached {self.max_requests_per_host} requests this run",
            )
        if not self._robots_allows(url, client):
            logger.info("robots.txt disallows %s", url)
            return FetchResult(Outcome.DISALLOWED, url=url, detail="robots.txt disallows")

        headers = {"User-Agent": self.user_agent()}
        if accept:
            headers["Accept"] = accept

        last: FetchResult = FetchResult(Outcome.ERROR, url=url, detail="no attempt made")
        for attempt in range(1, MAX_ATTEMPTS + 1):
            self._throttle(host, url)
            started = time.monotonic()
            try:
                response = client.get(url, headers=headers, params=params, follow_redirects=True)
            except httpx.HTTPError as exc:
                last = FetchResult(Outcome.ERROR, url=url, detail=f"{type(exc).__name__}: {exc}")
                self._record(tally, last, time.monotonic() - started)
                if attempt < MAX_ATTEMPTS:
                    continue
                return last

            elapsed = time.monotonic() - started
            status = response.status_code

            if status in BLOCKED_STATUSES:
                # Never retried, by policy. Retrying is how a per-request block
                # becomes an IP-range block.
                result = FetchResult(
                    Outcome.BLOCKED, status_code=status, url=url,
                    detail=f"HTTP {status} — bot protection or entitlement required",
                )
                self._record(tally, result, elapsed)
                return result

            if status == 404 or status == 410:
                result = FetchResult(Outcome.NOT_FOUND, status_code=status, url=url)
                self._record(tally, result, elapsed)
                return result

            if status in RETRYABLE_STATUSES:
                result = FetchResult(
                    Outcome.RATE_LIMITED if status == 429 else Outcome.ERROR,
                    status_code=status, url=url, detail=f"HTTP {status}",
                )
                self._record(tally, result, elapsed)
                if attempt < MAX_ATTEMPTS:
                    self.sleep(self._retry_after(response))
                    continue
                return result

            if status >= 400:
                result = FetchResult(
                    Outcome.ERROR, status_code=status, url=url, detail=f"HTTP {status}"
                )
                self._record(tally, result, elapsed)
                return result

            result = FetchResult(
                Outcome.SUCCESS,
                status_code=status,
                content=response.content,
                content_type=(response.headers.get("content-type") or "").split(";")[0].strip()
                or None,
                url=str(response.url),
            )
            self._record(tally, result, elapsed)
            return result

        return last

    @staticmethod
    def _retry_after(response: httpx.Response) -> float:
        """Honour the header the server sent, bounded."""
        raw = response.headers.get("retry-after")
        if not raw:
            return 2.0
        try:
            return min(MAX_RETRY_AFTER_S, max(0.0, float(raw)))
        except ValueError:
            return 5.0  # HTTP-date form; a short fixed wait is close enough

    def _record(self, tally: HostTally, result: FetchResult, elapsed: float) -> None:
        with self._lock:
            tally.requests += 1
            tally.total_latency_s += elapsed
            if result.outcome is Outcome.SUCCESS:
                tally.successes += 1
                tally.consecutive_blocks = 0
            elif result.outcome is Outcome.BLOCKED:
                tally.blocked += 1
                tally.consecutive_blocks += 1
                if tally.consecutive_blocks >= MAX_CONSECUTIVE_BLOCKS and not tally.circuit_open:
                    tally.circuit_open = True
                    logger.warning(
                        "circuit breaker opened for %s after %d consecutive blocks; "
                        "its remaining papers go to assisted acquisition",
                        tally.host,
                        tally.consecutive_blocks,
                    )
            elif result.outcome is Outcome.RATE_LIMITED:
                tally.rate_limited += 1
            elif result.outcome is Outcome.NOT_FOUND:
                tally.not_found += 1
            else:
                tally.errors += 1
