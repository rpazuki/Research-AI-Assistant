"""
app/datasheet/lookup_service.py
-------------------------------
Seed resolution for the datasheet wizard: organism -> taxid + synonyms,
bioproduct -> CID + synonyms + product class.

All the actual work is in `pipelines.discovery` (pure, HTTP-only, no DB). This
module is the thin backend half: it runs those blocking clients off the event
loop, caches results, and turns an upstream failure into an HTTP status a route
can return.

Two deliberate properties:

* **Blocking clients run in a worker thread.** `httpx.Client` is synchronous; a
  direct call would stall the event loop for the duration of an NCBI round trip.
* **Upstream failure is never an empty result.** A dead NCBI returns 502, not
  "no such organism" — the wizard must not let a curator conclude an organism is
  unknown because a service was down.
"""

from __future__ import annotations

import asyncio
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, TypeVar

from fastapi import HTTPException, status

from app.core.config import settings

_BACKEND_DIR = Path(__file__).resolve().parents[2]
# In the Docker image `pipelines` is copied inside backend/; locally it is a sibling.
_REPO_ROOT = _BACKEND_DIR if (_BACKEND_DIR / "pipelines").exists() else _BACKEND_DIR.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from pipelines.discovery.http import DiscoveryLookupError  # noqa: E402
from pipelines.discovery.product import (  # noqa: E402
    ProductSeed,
    fetch_product,
    resolve_product,
    search_products,
)
from pipelines.discovery.taxonomy import (  # noqa: E402
    OrganismSeed,
    OrganismSuggestion,
    fetch_organism,
    resolve_organism,
    search_organisms,
)
from pipelines.extraction.default_template import STANDARD_PRODUCT_CLASSES  # noqa: E402

# Re-exported so the route layer gets the controlled vocabulary without repeating
# the sys.path dance above.
PRODUCT_CLASSES: tuple[str, ...] = tuple(STANDARD_PRODUCT_CLASSES)

T = TypeVar("T")

# Typeahead sends a request per keystroke pause, and the same few seeds get
# resolved repeatedly while a curator fills the form. A short TTL is enough to
# collapse that without holding stale taxonomy: these records change on the order
# of years.
CACHE_TTL_S = 900.0
CACHE_MAX_ENTRIES = 512


@dataclass
class _CacheEntry:
    value: Any
    expires_at: float


_cache: dict[tuple[str, ...], _CacheEntry] = {}


def clear_lookup_cache() -> None:
    """Drop all cached lookups. Used by tests and after a config change."""
    _cache.clear()


def _cache_get(key: tuple[str, ...]) -> Any | None:
    entry = _cache.get(key)
    if entry is None:
        return None
    if entry.expires_at <= time.monotonic():
        _cache.pop(key, None)
        return None
    return entry.value


def _cache_put(key: tuple[str, ...], value: Any) -> None:
    if len(_cache) >= CACHE_MAX_ENTRIES:
        # Cheapest sufficient eviction: drop whatever expires soonest. The cache
        # exists to absorb typeahead bursts, not to be a long-lived store.
        oldest = min(_cache, key=lambda existing: _cache[existing].expires_at)
        _cache.pop(oldest, None)
    _cache[key] = _CacheEntry(value=value, expires_at=time.monotonic() + CACHE_TTL_S)


async def _run(key: tuple[str, ...], work: Callable[[], T]) -> T:
    """Run a blocking lookup off the loop, with caching and error translation."""
    cached = _cache_get(key)
    if cached is not None:
        return cached  # type: ignore[return-value]

    try:
        result = await asyncio.to_thread(work)
    except DiscoveryLookupError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"{exc.upstream} lookup failed: {exc.message}",
        ) from exc

    if result is not None:
        _cache_put(key, result)
    return result


async def suggest_organisms(query: str, *, limit: int = 10) -> list[OrganismSuggestion]:
    return await _run(
        ("organism-search", query.casefold(), str(limit)),
        lambda: search_organisms(
            query,
            limit=limit,
            email=settings.ncbi_email or None,
            api_key=settings.ncbi_api_key or None,
        ),
    )


async def resolve_organism_seed(
    *, query: str | None = None, taxid: int | None = None, extra_synonyms: tuple[str, ...] = ()
) -> OrganismSeed | None:
    if taxid is not None:
        return await _run(
            ("organism-taxid", str(taxid), *extra_synonyms),
            lambda: fetch_organism(
                taxid,
                extra_synonyms=extra_synonyms,
                email=settings.ncbi_email or None,
                api_key=settings.ncbi_api_key or None,
            ),
        )

    cleaned = (query or "").strip()
    if not cleaned:
        return None
    return await _run(
        ("organism-resolve", cleaned.casefold(), *extra_synonyms),
        lambda: resolve_organism(
            cleaned,
            extra_synonyms=extra_synonyms,
            email=settings.ncbi_email or None,
            api_key=settings.ncbi_api_key or None,
        ),
    )


async def suggest_products(query: str, *, limit: int = 10) -> list[Any]:
    return await _run(
        ("product-search", query.casefold(), str(limit)),
        lambda: search_products(query, limit=limit),
    )


async def resolve_product_seed(
    *, query: str | None = None, cid: int | None = None
) -> ProductSeed | None:
    if cid is not None:
        return await _run(("product-cid", str(cid)), lambda: fetch_product(cid))

    cleaned = (query or "").strip()
    if not cleaned:
        return None
    return await _run(("product-resolve", cleaned.casefold()), lambda: resolve_product(cleaned))
