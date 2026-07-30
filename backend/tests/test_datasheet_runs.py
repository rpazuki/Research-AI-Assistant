"""Tests for the S2 backend half: run routes, phase-A persistence, worker driving.

No database and no network: the discovery pass and the DB calls are replaced by
fakes so what is measured is this layer's own behaviour.
"""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from app.api import deps
from app.datasheet import discovery_service, worker
from app.db.models import User
from app.main import app
from pipelines.discovery.canonicalize import Candidate

NOW = datetime(2026, 7, 30, 10, 0, tzinfo=timezone.utc)
RUN_ID = uuid.uuid4()


class DummyDB:
    pass


def make_admin() -> User:
    return User(
        id=uuid.uuid4(),
        email="admin@example.com",
        hashed_password="hashed",
        full_name="Admin",
        role="admin",
        is_active=True,
        token_limit=1_000_000,
    )


def make_researcher() -> User:
    return User(
        id=uuid.uuid4(),
        email="researcher@example.com",
        hashed_password="hashed",
        full_name="Researcher",
        role="researcher",
        is_active=True,
        token_limit=1_000_000,
    )


def make_run(**overrides):
    data = {
        "id": RUN_ID,
        "name": "yarrowia-2016-2026",
        "status": "queued",
        "phase": None,
        "stop_after_phase": "ingestion",
        "seed_kind": "organism",
        "organism_name": "Yarrowia lipolytica",
        "organism_taxid": 4952,
        "organism_synonyms": ["Yarrowia lipolytica", "Candida lipolytica"],
        "product_term": None,
        "product_ids": None,
        "product_synonyms": [],
        "product_classes": None,
        "year_from": 2016,
        "year_to": 2026,
        "template_snapshot": {"name": "rlalab-datasheet-v1", "version": 1},
        "config_snapshot": {"discovery": {"max_records_per_source": 500}},
        "candidate_count": 3426,
        "acquired_count": None,
        "cache_path": "data/corpora/datasheets/test-run",
        "progress_message": "Queued",
        "log_tail": None,
        "error": None,
        "created_at": NOW,
        "started_at": None,
        "finished_at": None,
    }
    data.update(overrides)
    return SimpleNamespace(**data)


def make_candidate_row(**overrides):
    data = {
        "id": uuid.uuid4(),
        "doi": "10.1021/acsomega.6c03958",
        "pmid": "42428839",
        "pmc_id": "PMC13347637",
        "title": "Engineering of Yarrowia lipolytica for hesperetin",
        "journal": "ACS Omega",
        "publisher": "ACS",
        "year": 2026,
        "found_in": ["pubmed", "europepmc"],
        "oa_status": "open",
        "license": "cc by-nc-nd",
        "is_preprint": False,
        "preprint_doi": None,
        "version_of_record_doi": None,
        "doc_type": "primary",
        "is_review": False,
        "is_retracted": False,
        "relevance": "studies",
        "relevance_reason": "seed term in title (1 hit)",
        "acquisition_status": "pending",
        "acquisition_route": None,
        "dedupe_group": "doi:10.1021/acsomega.6c03958",
        "possible_duplicate_of": None,
        "duplicate_evidence": None,
        "notes": None,
    }
    data.update(overrides)
    return SimpleNamespace(**data)


@asynccontextmanager
async def make_client(user: User):
    async def override_current_user():
        return user

    async def override_db():
        yield DummyDB()

    app.dependency_overrides[deps.get_current_user] = override_current_user
    app.dependency_overrides[deps.get_db] = override_db
    transport = httpx.ASGITransport(app=app)
    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            yield client
    finally:
        app.dependency_overrides.clear()


def patch_run_routes(monkeypatch, *, run=None, candidates=None, counts=None):
    run = run if run is not None else make_run()

    async def fake_get_run(_db, _run_id):
        return run

    async def fake_counts(_db, _run_id):
        return counts if counts is not None else {"total": 2, "relevance_studies": 2}

    async def fake_list_candidates(_db, _run_id, **_kwargs):
        return candidates if candidates is not None else [make_candidate_row()]

    monkeypatch.setattr("app.api.routes.admin_datasheet.get_run", fake_get_run)
    monkeypatch.setattr("app.api.routes.admin_datasheet.count_candidates", fake_counts)
    monkeypatch.setattr("app.api.routes.admin_datasheet.list_candidates", fake_list_candidates)
    return run


RUN_PAYLOAD = {
    "name": "yarrowia-2016-2026",
    "seed_kind": "organism",
    "organism_name": "Yarrowia lipolytica",
    "organism_taxid": 4952,
    "organism_synonyms": ["Yarrowia lipolytica", "Candida lipolytica"],
    "year_from": 2016,
    "year_to": 2026,
}


# ── Admin gate and validation ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_runs_require_admin() -> None:
    async with make_client(make_researcher()) as client:
        response = await client.get("/api/v1/admin/datasheets/runs")
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_an_organism_seed_without_search_terms_is_rejected() -> None:
    """The synonym set is the whole point of the seed; an empty one would silently
    search for nothing."""
    async with make_client(make_admin()) as client:
        response = await client.post(
            "/api/v1/admin/datasheets/runs",
            json={**RUN_PAYLOAD, "organism_synonyms": []},
        )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_reversed_years_are_rejected() -> None:
    async with make_client(make_admin()) as client:
        response = await client.post(
            "/api/v1/admin/datasheets/runs",
            json={**RUN_PAYLOAD, "year_from": 2026, "year_to": 2016},
        )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_an_unknown_template_is_a_404(monkeypatch) -> None:
    async def fake_create(*_args, **_kwargs):
        raise discovery_service.DatasheetRunError("Template 'nope' not found")

    monkeypatch.setattr("app.api.routes.admin_datasheet.create_run", fake_create)

    async with make_client(make_admin()) as client:
        response = await client.post(
            "/api/v1/admin/datasheets/runs", json={**RUN_PAYLOAD, "template_name": "nope"}
        )
    assert response.status_code == 404


# ── Run lifecycle over HTTP ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_creating_a_run_queues_it_rather_than_searching_inline(monkeypatch) -> None:
    """A discovery pass is thousands of upstream records over minutes; doing it in
    the request would hold a connection open for the whole thing."""
    created = make_run()
    captured: dict = {}

    async def fake_create(_db, **kwargs):
        captured.update(kwargs)
        return created

    monkeypatch.setattr("app.api.routes.admin_datasheet.create_run", fake_create)
    patch_run_routes(monkeypatch, run=created)

    async with make_client(make_admin()) as client:
        response = await client.post("/api/v1/admin/datasheets/runs", json=RUN_PAYLOAD)

    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "queued"
    assert body["organism_synonyms"] == ["Yarrowia lipolytica", "Candida lipolytica"]
    assert captured["config"]["discovery"]["max_records_per_source"] == 6000


@pytest.mark.asyncio
async def test_run_detail_reports_counts_and_the_discovery_summary(monkeypatch) -> None:
    run = make_run(
        status="succeeded",
        phase="discovery",
        config_snapshot={
            "discovery": {},
            "discovery_result": {"candidates": 3426, "source_errors": {}},
        },
    )
    patch_run_routes(
        monkeypatch,
        run=run,
        counts={"total": 3426, "relevance_studies": 2266, "retracted": 2},
    )

    async with make_client(make_admin()) as client:
        response = await client.get(f"/api/v1/admin/datasheets/runs/{RUN_ID}")

    body = response.json()
    assert body["candidate_counts"]["relevance_studies"] == 2266
    assert body["discovery_summary"]["candidates"] == 3426
    assert body["template_name"] == "rlalab-datasheet-v1"


@pytest.mark.asyncio
async def test_a_missing_run_is_a_404(monkeypatch) -> None:
    async def fake_get_run(_db, _run_id):
        return None

    monkeypatch.setattr("app.api.routes.admin_datasheet.get_run", fake_get_run)

    async with make_client(make_admin()) as client:
        response = await client.get(f"/api/v1/admin/datasheets/runs/{uuid.uuid4()}")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_candidates_carry_the_reason_they_were_kept(monkeypatch) -> None:
    """A filter a curator cannot audit is a filter they cannot trust."""
    patch_run_routes(monkeypatch)

    async with make_client(make_admin()) as client:
        response = await client.get(f"/api/v1/admin/datasheets/runs/{RUN_ID}/candidates")

    row = response.json()[0]
    assert row["relevance"] == "studies"
    assert row["relevance_reason"] == "seed term in title (1 hit)"
    assert row["found_in"] == ["pubmed", "europepmc"]


@pytest.mark.asyncio
async def test_a_duplicate_suspicion_reaches_the_ui_unmerged(monkeypatch) -> None:
    """Two rows, both kept, each citing itself — the owner decision. The suspicion
    travels with them so a human can act on it."""
    patch_run_routes(
        monkeypatch,
        candidates=[
            make_candidate_row(
                doi="10.1016/j.synbio.2026.01.017",
                possible_duplicate_of=["10.2139/ssrn.5675827"],
                duplicate_evidence="same normalised title as 10.2139/ssrn.5675827 (years [2025, 2026])",
            ),
            make_candidate_row(doi="10.2139/ssrn.5675827", is_preprint=True),
        ],
    )

    async with make_client(make_admin()) as client:
        response = await client.get(f"/api/v1/admin/datasheets/runs/{RUN_ID}/candidates")

    rows = response.json()
    assert len(rows) == 2
    assert rows[0]["possible_duplicate_of"] == ["10.2139/ssrn.5675827"]
    assert "years [2025, 2026]" in rows[0]["duplicate_evidence"]


def test_the_duplicate_suspicion_is_persisted() -> None:
    row = discovery_service._candidate_row(
        RUN_ID,
        Candidate(
            doi="10.1016/vor",
            possible_duplicate_of=("10.2139/ssrn.1",),
            duplicate_evidence="same normalised title as 10.2139/ssrn.1",
        ),
        included=True,
    )
    assert row.possible_duplicate_of == ["10.2139/ssrn.1"]
    assert row.duplicate_evidence == "same normalised title as 10.2139/ssrn.1"


def test_no_suspicion_stores_null_rather_than_an_empty_array() -> None:
    row = discovery_service._candidate_row(RUN_ID, Candidate(doi="10.1/x"), included=True)
    assert row.possible_duplicate_of is None


@pytest.mark.asyncio
async def test_candidate_filters_reach_the_query(monkeypatch) -> None:
    captured: dict = {}

    async def fake_list_candidates(_db, _run_id, **kwargs):
        captured.update(kwargs)
        return []

    patch_run_routes(monkeypatch)
    monkeypatch.setattr("app.api.routes.admin_datasheet.list_candidates", fake_list_candidates)

    async with make_client(make_admin()) as client:
        await client.get(
            f"/api/v1/admin/datasheets/runs/{RUN_ID}/candidates",
            params={"relevance": "mentions", "acquisition_status": "skipped", "limit": 10},
        )

    assert captured["relevance"] == "mentions"
    assert captured["acquisition_status"] == "skipped"
    assert captured["limit"] == 10


@pytest.mark.asyncio
async def test_manifest_downloads_as_a_csv_attachment(monkeypatch) -> None:
    patch_run_routes(monkeypatch)

    async def fake_manifest(_db, _run_id):
        return "doi,included\n10.1/x,yes\n"

    monkeypatch.setattr("app.api.routes.admin_datasheet.manifest_csv_for_run", fake_manifest)

    async with make_client(make_admin()) as client:
        response = await client.get(f"/api/v1/admin/datasheets/runs/{RUN_ID}/manifest.csv")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    assert "attachment" in response.headers["content-disposition"]
    assert response.text.startswith("doi,included")


@pytest.mark.asyncio
async def test_cancelling_a_finished_run_is_not_an_error(monkeypatch) -> None:
    finished = make_run(status="succeeded", finished_at=NOW)

    async def fake_cancel(_db, _run_id):
        return finished

    patch_run_routes(monkeypatch, run=finished)
    monkeypatch.setattr("app.api.routes.admin_datasheet.request_cancel", fake_cancel)

    async with make_client(make_admin()) as client:
        response = await client.post(f"/api/v1/admin/datasheets/runs/{RUN_ID}/cancel")

    assert response.status_code == 200
    assert response.json()["status"] == "succeeded"


# ── Phase-A persistence mapping ───────────────────────────────────────────────


def test_the_query_is_built_from_the_runs_own_seed() -> None:
    query = discovery_service.build_query(make_run())

    assert query.organism_terms == ("Yarrowia lipolytica", "Candida lipolytica")
    assert query.year_from == 2016
    assert query.max_records_per_source == 500


def test_an_excluded_candidate_is_recorded_as_skipped_not_deleted() -> None:
    """It stays in the manifest with its reason instead of disappearing — silent
    omission is the failure this whole feature exists to fix."""
    included = discovery_service._candidate_row(
        RUN_ID, Candidate(doi="10.1/keep", relevance="studies"), included=True
    )
    excluded = discovery_service._candidate_row(
        RUN_ID,
        Candidate(doi="10.1/drop", relevance="mentions", relevance_reason="single mention"),
        included=False,
    )

    assert included.acquisition_status == "pending"
    assert excluded.acquisition_status == "skipped"
    assert excluded.relevance_reason == "single mention"


def test_the_preprint_doi_survives_persistence() -> None:
    """bioRxiv serves JATS for it openly, which is often the only free full text
    for a paywalled version of record."""
    row = discovery_service._candidate_row(
        RUN_ID,
        Candidate(doi="10.1016/vor", preprint_doi="10.1101/2020.01.01.000001"),
        included=True,
    )
    assert row.preprint_doi == "10.1101/2020.01.01.000001"


def test_a_candidate_with_no_relevance_verdict_defaults_to_unknown() -> None:
    row = discovery_service._candidate_row(RUN_ID, Candidate(doi="10.1/x", relevance=""), included=True)
    assert row.relevance == "unknown"


def test_log_tail_is_bounded() -> None:
    """Run logs are read in a UI; an unbounded tail would grow without limit."""
    log = None
    for index in range(discovery_service.LOG_TAIL_LINES + 40):
        log = discovery_service.append_log(log, f"line {index}")

    assert len(log.splitlines()) == discovery_service.LOG_TAIL_LINES
    assert log.splitlines()[-1].endswith(f"line {discovery_service.LOG_TAIL_LINES + 39}")


# ── Worker ────────────────────────────────────────────────────────────────────


class FakeSession:
    def __init__(self, run):
        self.run = run
        self.commits = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None

    async def get(self, _model, _run_id):
        return self.run

    async def commit(self):
        self.commits += 1


@pytest.mark.asyncio
async def test_a_failed_run_is_marked_failed_and_the_worker_survives(monkeypatch) -> None:
    """One bad run must not take the worker down — it also serves the ingestion
    queue that an admin is actively watching."""
    run = make_run(status="running")
    session = FakeSession(run)

    async def failing_phase(*_args, **_kwargs):
        raise RuntimeError("OpenAlex exploded")

    monkeypatch.setattr(worker, "AsyncSessionLocal", lambda: session)
    monkeypatch.setattr(worker, "run_discovery_phase", failing_phase)

    await worker.run_datasheet_job(RUN_ID)

    assert run.status == "failed"
    assert "OpenAlex exploded" in run.error
    assert run.finished_at is not None


def patch_phases(monkeypatch, run, *, acquisition=None, cancelled=False):
    session = FakeSession(run)

    async def fake_discovery(*_args, **_kwargs):
        return {"candidates": 10}

    async def fake_acquisition(*_args, **_kwargs):
        return acquisition or {
            "attempted": 10,
            "fetched": 6,
            "assisted_pending": 3,
            "failed": 1,
            "from_cache": 2,
            "by_route": {"pmc_oa": 4, "unpaywall": 2},
            "by_format": {"xml": 5, "pdf": 1},
            "fidelity_warnings": 0,
            "host_tallies": [],
        }

    async def cancel_state(_run_id):
        return cancelled

    monkeypatch.setattr(worker, "AsyncSessionLocal", lambda: session)
    monkeypatch.setattr(worker, "run_discovery_phase", fake_discovery)
    monkeypatch.setattr(worker, "run_acquisition_phase", fake_acquisition)
    monkeypatch.setattr(worker, "resolve_run_cache_root", lambda _run: Path("/tmp/does-not-matter"))
    monkeypatch.setattr(worker, "is_cancel_requested", cancel_state)
    return session


@pytest.mark.asyncio
async def test_a_run_drives_discovery_then_acquisition(monkeypatch) -> None:
    """Round 1 ends after acquisition. Reported as succeeded rather than left
    'running', so the run list is honest about a round without extraction."""
    run = make_run(status="running")
    patch_phases(monkeypatch, run)

    await worker.run_datasheet_job(RUN_ID)

    assert run.status == "succeeded"
    assert run.phase == "acquisition"
    assert run.acquired_count == 6
    assert "6 fetched (2 from cache), 3 need assisted acquisition" in run.log_tail
    assert "extraction is round 2" in run.log_tail


@pytest.mark.asyncio
async def test_an_opened_circuit_is_named_in_the_run_log(monkeypatch) -> None:
    """A publisher that blocked us is stated, not left for someone to infer from a
    low fetch count."""
    run = make_run(status="running")
    patch_phases(
        monkeypatch,
        run,
        acquisition={
            "attempted": 50, "fetched": 2, "assisted_pending": 48, "failed": 0, "from_cache": 0,
            "by_route": {}, "by_format": {}, "fidelity_warnings": 0,
            "host_tallies": [{"host": "www.mdpi.com", "circuit_open": True, "blocked": 3}],
        },
    )

    await worker.run_datasheet_job(RUN_ID)

    assert "Circuit opened for: www.mdpi.com" in run.log_tail
    assert "went to assisted" in run.log_tail


@pytest.mark.asyncio
async def test_a_failed_acquisition_marks_the_run_failed(monkeypatch) -> None:
    run = make_run(status="running")
    session = patch_phases(monkeypatch, run)

    async def boom(*_args, **_kwargs):
        raise RuntimeError("Unpaywall exploded")

    monkeypatch.setattr(worker, "run_acquisition_phase", boom)

    await worker.run_datasheet_job(RUN_ID)

    assert run.status == "failed"
    assert "Unpaywall exploded" in run.error
    assert session.commits > 0


@pytest.mark.asyncio
async def test_a_cancellation_requested_during_discovery_is_honoured(monkeypatch) -> None:
    run = make_run(status="running")

    patch_phases(monkeypatch, run, cancelled=True)

    await worker.run_datasheet_job(RUN_ID)

    assert run.status == "cancelled"


@pytest.mark.asyncio
async def test_polling_reports_when_there_was_nothing_to_claim(monkeypatch) -> None:
    async def nothing_queued():
        return None

    monkeypatch.setattr(worker, "claim_next_run", nothing_queued)
    assert await worker.poll_once() is False
