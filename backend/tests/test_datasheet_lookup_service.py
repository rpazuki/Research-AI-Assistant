"""Tests for the backend half of seed lookup: caching, threading, error translation.

The discovery clients themselves are covered offline in `test_discovery_seeds.py`;
here they are replaced by fakes so the service's own behaviour is what is measured.
"""

from __future__ import annotations

import asyncio
import threading

import pytest
from fastapi import HTTPException

from app.datasheet import lookup_service
from pipelines.discovery.http import DiscoveryLookupError
from pipelines.discovery.taxonomy import OrganismSeed, OrganismSuggestion


@pytest.fixture(autouse=True)
def _clear_cache():
    lookup_service.clear_lookup_cache()
    yield
    lookup_service.clear_lookup_cache()


def make_seed(taxid: int = 4952) -> OrganismSeed:
    return OrganismSeed(
        taxid=taxid,
        scientific_name="Yarrowia lipolytica",
        rank="species",
        synonyms=("Candida lipolytica",),
    )


@pytest.mark.asyncio
async def test_repeated_lookups_hit_the_cache_not_the_upstream(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Typeahead sends a request per keystroke pause; the same seed is resolved
    repeatedly while a curator fills the form."""
    calls: list[int] = []

    def fake_fetch(taxid, **_kwargs):
        calls.append(taxid)
        return make_seed(taxid)

    monkeypatch.setattr(lookup_service, "fetch_organism", fake_fetch)

    first = await lookup_service.resolve_organism_seed(taxid=4952)
    second = await lookup_service.resolve_organism_seed(taxid=4952)

    assert first == second
    assert calls == [4952]


@pytest.mark.asyncio
async def test_a_miss_is_not_cached_so_a_later_success_is_visible(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An organism added to NCBI, or a typo the curator then fixes upstream, must
    not stay 'not found' for the cache lifetime."""
    results = iter([None, make_seed()])

    monkeypatch.setattr(lookup_service, "fetch_organism", lambda taxid, **_k: next(results))

    assert await lookup_service.resolve_organism_seed(taxid=4952) is None
    assert await lookup_service.resolve_organism_seed(taxid=4952) is not None


@pytest.mark.asyncio
async def test_cache_keys_separate_different_queries(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        lookup_service,
        "search_organisms",
        lambda query, **_kwargs: [OrganismSuggestion(taxid=len(query), scientific_name=query)],
    )

    first = await lookup_service.suggest_organisms("yarrowia")
    second = await lookup_service.suggest_organisms("candida")

    assert first[0].scientific_name == "yarrowia"
    assert second[0].scientific_name == "candida"


@pytest.mark.asyncio
async def test_an_upstream_failure_becomes_a_502_not_an_empty_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The wizard must never let a curator conclude an organism is unknown because
    NCBI was down."""

    def fail(*_args, **_kwargs):
        raise DiscoveryLookupError("NCBI Taxonomy", "HTTP 503")

    monkeypatch.setattr(lookup_service, "search_organisms", fail)

    with pytest.raises(HTTPException) as excinfo:
        await lookup_service.suggest_organisms("yarrowia")

    assert excinfo.value.status_code == 502
    assert "NCBI Taxonomy" in excinfo.value.detail


@pytest.mark.asyncio
async def test_a_failure_is_not_cached(monkeypatch: pytest.MonkeyPatch) -> None:
    attempts: list[int] = []

    def fail_then_succeed(query, **_kwargs):
        attempts.append(1)
        if len(attempts) == 1:
            raise DiscoveryLookupError("NCBI Taxonomy", "HTTP 503")
        return [OrganismSuggestion(taxid=4952, scientific_name="Yarrowia lipolytica")]

    monkeypatch.setattr(lookup_service, "search_organisms", fail_then_succeed)

    with pytest.raises(HTTPException):
        await lookup_service.suggest_organisms("yarrowia")

    recovered = await lookup_service.suggest_organisms("yarrowia")
    assert recovered[0].taxid == 4952


@pytest.mark.asyncio
async def test_the_blocking_client_runs_off_the_event_loop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`httpx.Client` is synchronous: called directly it would stall the loop for a
    whole NCBI round trip, blocking every other request."""
    loop_thread = threading.get_ident()
    seen: list[int] = []

    def fake_fetch(taxid, **_kwargs):
        seen.append(threading.get_ident())
        return make_seed(taxid)

    monkeypatch.setattr(lookup_service, "fetch_organism", fake_fetch)

    await lookup_service.resolve_organism_seed(taxid=4952)

    assert seen and seen[0] != loop_thread


@pytest.mark.asyncio
async def test_an_empty_query_resolves_without_calling_upstream(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail(*_args, **_kwargs):
        raise AssertionError("upstream must not be called for an empty query")

    monkeypatch.setattr(lookup_service, "resolve_organism", fail)
    monkeypatch.setattr(lookup_service, "resolve_product", fail)

    assert await lookup_service.resolve_organism_seed(query="  ") is None
    assert await lookup_service.resolve_product_seed(query="") is None


@pytest.mark.asyncio
async def test_the_cache_is_bounded(monkeypatch: pytest.MonkeyPatch) -> None:
    """It absorbs typeahead bursts; it is not a long-lived store."""
    monkeypatch.setattr(
        lookup_service,
        "search_organisms",
        lambda query, **_kwargs: [OrganismSuggestion(taxid=1, scientific_name=query)],
    )

    for index in range(lookup_service.CACHE_MAX_ENTRIES + 20):
        await lookup_service.suggest_organisms(f"organism-{index}")

    assert len(lookup_service._cache) <= lookup_service.CACHE_MAX_ENTRIES


@pytest.mark.asyncio
async def test_expired_entries_are_dropped(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[int] = []

    def fake_fetch(taxid, **_kwargs):
        calls.append(taxid)
        return make_seed(taxid)

    monkeypatch.setattr(lookup_service, "fetch_organism", fake_fetch)
    monkeypatch.setattr(lookup_service, "CACHE_TTL_S", -1.0)

    await lookup_service.resolve_organism_seed(taxid=4952)
    await lookup_service.resolve_organism_seed(taxid=4952)

    assert calls == [4952, 4952]


@pytest.mark.asyncio
async def test_concurrent_lookups_do_not_deadlock(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(lookup_service, "fetch_organism", lambda taxid, **_k: make_seed(taxid))

    seeds = await asyncio.gather(
        *(lookup_service.resolve_organism_seed(taxid=taxid) for taxid in range(4950, 4960))
    )

    assert [seed.taxid for seed in seeds] == list(range(4950, 4960))
