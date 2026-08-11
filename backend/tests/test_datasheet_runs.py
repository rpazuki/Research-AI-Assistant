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
from app.datasheet.extractor import ExtractionSummary
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
        "stop_after_phase": "export",
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
        "extracted_count": None,
        "prompt_tokens": None,
        "completion_tokens": None,
        "cached_tokens": None,
        "extraction_batch_id": None,
        "extraction_batch_submitted_at": None,
        "extraction_batch_polled_at": None,
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
        "extraction_status": None,
        "extraction_error": None,
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

    async def fake_row_count(_db, _run_id):
        return 0

    monkeypatch.setattr("app.api.routes.admin_datasheet.get_run", fake_get_run)
    monkeypatch.setattr("app.api.routes.admin_datasheet.count_candidates", fake_counts)
    monkeypatch.setattr("app.api.routes.admin_datasheet.list_candidates", fake_list_candidates)
    monkeypatch.setattr("app.api.routes.admin_datasheet.count_rows", fake_row_count)
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
async def test_rows_endpoint_returns_cells_with_their_evidence(monkeypatch) -> None:
    """A reviewer judges a cell from its quote; a bare value would be
    indistinguishable from a guess."""
    patch_run_routes(monkeypatch)

    async def fake_rows(_db, _run_id, limit=200, offset=0):
        return [
            {
                "id": uuid.uuid4(),
                "candidate_id": uuid.uuid4(),
                "title": "Engineering Yarrowia",
                "cells": {
                    "compounds": {
                        "value": "citric acid",
                        "confidence": 0.92,
                        "evidence_quote": "Titre reached 50 g/L citric acid",
                        "evidence_section": "results",
                    }
                },
                "source_tier": "fulltext",
                "extraction_model": "claude-sonnet-5",
                "doi": "10.1/a",
                "year": 2020,
            }
        ]

    monkeypatch.setattr("app.api.routes.admin_datasheet.list_rows", fake_rows)

    async with make_client(make_admin()) as client:
        response = await client.get(f"/api/v1/admin/datasheets/runs/{RUN_ID}/rows")

    assert response.status_code == 200
    body = response.json()[0]
    assert body["cells"]["compounds"]["evidence_quote"].startswith("Titre reached")
    assert body["source_tier"] == "fulltext"


@pytest.mark.asyncio
async def test_datasheet_csv_downloads_as_an_attachment(monkeypatch) -> None:
    patch_run_routes(monkeypatch)

    async def fake_csv(_db, _run):
        return "Compounds,doi\ncitric acid,10.1/a\n"

    monkeypatch.setattr("app.api.routes.admin_datasheet.datasheet_csv_for_run", fake_csv)

    async with make_client(make_admin()) as client:
        response = await client.get(f"/api/v1/admin/datasheets/runs/{RUN_ID}/datasheet.csv")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    assert "attachment" in response.headers["content-disposition"]
    assert response.text.startswith("Compounds,doi")


@pytest.mark.asyncio
async def test_extraction_estimate_reports_cost_without_sending_anything(monkeypatch) -> None:
    """The projection is the only thing that happens while extraction is off, so
    the endpoint says so rather than looking like an empty result."""
    from app.datasheet.extractor import ExtractionPlan

    patch_run_routes(monkeypatch)
    plan = ExtractionPlan(model="claude-sonnet-5")

    async def fake_plan(_db, _run, cache_root=None, provider=None):
        return plan

    monkeypatch.setattr("app.api.routes.admin_datasheet.plan_extraction", fake_plan)
    monkeypatch.setattr(
        "app.api.routes.admin_datasheet.resolve_run_cache_root", lambda _run: Path("/tmp/x")
    )

    async with make_client(make_admin()) as client:
        response = await client.post(
            f"/api/v1/admin/datasheets/runs/{RUN_ID}/extraction-estimate"
        )

    assert response.status_code == 200
    body = response.json()
    assert body["extraction_enabled"] is False
    assert body["papers"] == 0
    assert body["model"] == "claude-sonnet-5"


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


# ── Cancellation and re-extraction ────────────────────────────────────────────


class RunSession:
    """Minimal async session for the run-lifecycle helpers."""

    def __init__(self, run):
        self.run = run
        self.statements: list = []
        self.commits = 0

    async def get(self, _model, _run_id):
        return self.run

    async def execute(self, statement):
        self.statements.append(statement)
        return SimpleNamespace()

    async def commit(self):
        self.commits += 1

    async def refresh(self, _run):
        return None


@pytest.mark.asyncio
async def test_cancelling_a_parked_run_asks_the_provider_to_stop_the_batch(monkeypatch) -> None:
    """A parked run is not `running`, so no worker will look at it again. If this
    call does not stop the batch, nothing does: it runs to completion, is billed in
    full, and its results are never collected."""
    run = make_run(status="awaiting_batch", extraction_batch_id="msgbatch_01")
    cancelled: list[str] = []

    async def fake_cancel(_provider, target):
        cancelled.append(target.extraction_batch_id)
        return True

    monkeypatch.setattr(discovery_service, "cancel_extraction_batch", fake_cancel)
    monkeypatch.setattr(discovery_service, "extraction_provider", lambda: object())

    result = await discovery_service.request_cancel(RunSession(run), RUN_ID)

    assert cancelled == ["msgbatch_01"]
    assert result.status == "cancelled"
    # Cancelling is not free, and the log says so rather than implying a refund.
    assert "still billed" in run.log_tail


@pytest.mark.asyncio
async def test_an_unreachable_provider_still_cancels_the_run(monkeypatch) -> None:
    """And leaves the batch id on the row: an uncollectable charge that is named is
    traceable, one that is erased is not."""
    run = make_run(status="awaiting_batch", extraction_batch_id="msgbatch_01")

    async def fake_cancel(_provider, _target):
        return False

    monkeypatch.setattr(discovery_service, "cancel_extraction_batch", fake_cancel)
    monkeypatch.setattr(discovery_service, "extraction_provider", lambda: object())

    result = await discovery_service.request_cancel(RunSession(run), RUN_ID)

    assert result.status == "cancelled"
    assert run.extraction_batch_id == "msgbatch_01"
    assert "could not be cancelled" in run.log_tail


@pytest.mark.asyncio
async def test_re_extraction_clears_the_rows_and_requeues_at_phase_d() -> None:
    run = make_run(
        status="succeeded",
        phase="export",
        extracted_count=5,
        prompt_tokens=41_000,
        extraction_batch_id="msgbatch_old",
        stop_after_phase="export",
    )
    session = RunSession(run)

    result = await discovery_service.request_reextraction(session, RUN_ID)

    assert result.status == "queued"
    # The worker's "start at D" signal — a normal queued run has phase = NULL.
    assert result.phase == "extraction"
    assert run.extraction_batch_id is None
    assert (run.extracted_count, run.prompt_tokens, run.finished_at) == (None, None, None)
    kinds = [(statement.is_delete, statement.is_update) for statement in session.statements]
    # The old rows go, and every candidate's recorded outcome is reset — otherwise a
    # shorter re-extraction leaves the previous pass's rows in the datasheet.
    assert (True, False) in kinds
    assert (False, True) in kinds


@pytest.mark.asyncio
async def test_re_extracting_a_running_run_is_refused() -> None:
    """Clearing rows underneath a worker that is writing them is a race, not a retry."""
    for status_name in ("queued", "running", "awaiting_batch", "cancel_requested"):
        run = make_run(status=status_name)
        with pytest.raises(discovery_service.DatasheetRunError, match=status_name):
            await discovery_service.request_reextraction(RunSession(run), RUN_ID)


@pytest.mark.asyncio
async def test_re_extract_over_http_reports_a_conflict_rather_than_a_500(monkeypatch) -> None:
    async def refuses(_db, _run_id):
        raise discovery_service.DatasheetRunError("Run is running; cancel it before re-extracting")

    monkeypatch.setattr("app.api.routes.admin_datasheet.request_reextraction", refuses)

    async with make_client(make_admin()) as client:
        response = await client.post(f"/api/v1/admin/datasheets/runs/{RUN_ID}/reextract")

    assert response.status_code == 409
    assert "cancel it" in response.json()["detail"]


@pytest.mark.asyncio
async def test_re_extract_over_http_returns_the_requeued_run(monkeypatch) -> None:
    requeued = make_run(status="queued", phase="extraction")

    async def fake_reextract(_db, _run_id):
        return requeued

    monkeypatch.setattr("app.api.routes.admin_datasheet.request_reextraction", fake_reextract)
    patch_run_routes(monkeypatch, run=requeued)

    async with make_client(make_admin()) as client:
        response = await client.post(f"/api/v1/admin/datasheets/runs/{RUN_ID}/reextract")

    assert response.status_code == 200
    assert response.json()["phase"] == "extraction"


# ── stop_after_phase ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_a_discovery_only_run_can_be_queued(monkeypatch) -> None:
    """Now that runs default to going the whole way, this is the only way to review a
    manifest before anything is fetched or any tokens are projected."""
    created = make_run(stop_after_phase="discovery")
    captured: dict = {}

    async def fake_create(_db, **kwargs):
        captured.update(kwargs)
        return created

    monkeypatch.setattr("app.api.routes.admin_datasheet.create_run", fake_create)
    patch_run_routes(monkeypatch, run=created)

    async with make_client(make_admin()) as client:
        response = await client.post(
            "/api/v1/admin/datasheets/runs",
            json={**RUN_PAYLOAD, "stop_after_phase": "discovery"},
        )

    assert response.status_code == 201
    assert captured["stop_after_phase"] == "discovery"
    assert response.json()["stop_after_phase"] == "discovery"


@pytest.mark.asyncio
async def test_an_unknown_stop_phase_is_rejected_at_the_edge() -> None:
    async with make_client(make_admin()) as client:
        response = await client.post(
            "/api/v1/admin/datasheets/runs",
            json={**RUN_PAYLOAD, "stop_after_phase": "extraction"},
        )

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_runs_default_to_going_the_whole_way(monkeypatch) -> None:
    captured: dict = {}

    async def fake_create(_db, **kwargs):
        captured.update(kwargs)
        return make_run()

    monkeypatch.setattr("app.api.routes.admin_datasheet.create_run", fake_create)
    patch_run_routes(monkeypatch)

    async with make_client(make_admin()) as client:
        await client.post("/api/v1/admin/datasheets/runs", json=RUN_PAYLOAD)

    assert captured["stop_after_phase"] == "export"


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


def test_the_manifest_is_written_into_the_runs_cache_directory(tmp_path, monkeypatch) -> None:
    """A run directory has to describe itself: `safe_stem` is one-way, so without
    this CSV nothing outside the database can map `assets/<stem>.pdf` back to a
    paper — and the ingestion pipeline reads exactly this file."""
    from pipelines.acquisition.cache_layout import manifest_csv_path

    run = make_run()
    monkeypatch.setattr(discovery_service, "resolve_run_cache_root", lambda _run: tmp_path)

    path = discovery_service.write_manifest_to_cache(
        run,
        [Candidate(doi="10.1/keep", title="Kept", relevance="studies")],
        included_dois={"10.1/keep"},
    )

    assert path == manifest_csv_path(tmp_path)
    text = path.read_text()
    assert text.splitlines()[0].startswith("doi,pmid,pmc_id,title")
    assert "Kept" in text


def test_a_manifest_that_cannot_be_written_does_not_fail_the_run(tmp_path, monkeypatch) -> None:
    """4,000 papers found must not be discarded because a directory is read-only."""
    def explode(_run):
        raise OSError("read-only file system")

    monkeypatch.setattr(discovery_service, "resolve_run_cache_root", explode)

    assert discovery_service.write_manifest_to_cache(make_run(), [], included_dois=set()) is None


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


def patch_phases(monkeypatch, run, *, acquisition=None, cancelled=False, extraction=None):
    session = FakeSession(run)

    async def fake_discovery(*_args, **_kwargs):
        return {"candidates": 10}

    async def fake_extraction(*_args, **_kwargs):
        # Default: the dry run the worker performs when extraction is disabled.
        return extraction or ExtractionSummary(
            model="claude-sonnet-5",
            dry_run=True,
            plan={
                "papers": 6,
                "input_tokens": 50_100,
                "token_method": "estimated_from_chars",
                "model": "claude-sonnet-5",
                "projected_cost_usd": 0.1,
            },
        )

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
    async def fake_export(*_args, **_kwargs):
        return {"rows": 5, "csv_path": "data/corpora/datasheets/test-run/datasheet.csv"}

    monkeypatch.setattr(worker, "run_extraction_phase", fake_extraction)
    monkeypatch.setattr(worker, "run_export_phase", fake_export)
    monkeypatch.setattr(worker, "extraction_provider", lambda: None)
    monkeypatch.setattr(worker, "resolve_run_cache_root", lambda _run: Path("/tmp/does-not-matter"))
    monkeypatch.setattr(worker, "is_cancel_requested", cancel_state)
    return session


@pytest.mark.asyncio
async def test_a_run_drives_discovery_then_acquisition(monkeypatch) -> None:
    run = make_run(status="running")
    patch_phases(monkeypatch, run)

    await worker.run_datasheet_job(RUN_ID)

    assert run.status == "succeeded"
    assert run.acquired_count == 6
    assert "6 fetched (2 from cache), 3 need assisted acquisition" in run.log_tail


@pytest.mark.asyncio
async def test_extraction_defaults_to_a_dry_run_and_says_so(monkeypatch) -> None:
    """With extraction disabled the run still reaches phase D — it reports what a
    real pass would cost and stops. Succeeded, not failed: nothing went wrong."""
    run = make_run(status="running")
    patch_phases(monkeypatch, run)

    await worker.run_datasheet_job(RUN_ID)

    assert run.status == "succeeded"
    assert run.phase == "extraction"
    assert run.extracted_count == 0
    assert "6 papers ready to extract" in run.progress_message
    assert "DATASHEET_EXTRACTION_ENABLED" in run.log_tail
    assert run.config_snapshot["extraction_result"]["dry_run"] is True


@pytest.mark.asyncio
async def test_a_live_extraction_records_rows_and_token_counters(monkeypatch) -> None:
    """Token counters come from actual usage, not the projection — cost is observed."""
    run = make_run(status="running")
    patch_phases(
        monkeypatch,
        run,
        extraction=ExtractionSummary(
            model="claude-sonnet-5",
            escalation_model="claude-opus-5",
            dry_run=False,
            extracted=5,
            escalated=1,
            refused=0,
            failed=1,
            prompt_tokens=41_000,
            completion_tokens=7_400,
            cached_tokens=12_000,
        ),
    )

    await worker.run_datasheet_job(RUN_ID)

    assert run.status == "succeeded"
    assert run.phase == "export"
    assert run.extracted_count == 5
    assert (run.prompt_tokens, run.completion_tokens, run.cached_tokens) == (41_000, 7_400, 12_000)
    assert "5 rows, 1 escalated" in run.log_tail
    # The run is not complete until the datasheet exists on disk.
    assert "datasheet.csv" in run.progress_message
    assert run.config_snapshot["export_result"]["rows"] == 5


@pytest.mark.asyncio
async def test_a_failed_extraction_fails_the_run_without_killing_the_worker(monkeypatch) -> None:
    run = make_run(status="running")

    async def exploding_extraction(*_args, **_kwargs):
        raise RuntimeError("batch submission rejected")

    patch_phases(monkeypatch, run)
    monkeypatch.setattr(worker, "run_extraction_phase", exploding_extraction)

    await worker.run_datasheet_job(RUN_ID)

    assert run.status == "failed"
    assert "batch submission rejected" in run.error
    assert run.finished_at is not None


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
async def test_a_submitted_batch_parks_the_run_rather_than_finishing_it(monkeypatch) -> None:
    """The worker also serves the ingestion queue. A run whose batch is with the
    provider must give the process back instead of sitting in a poll loop for
    however many hours the batch takes."""
    run = make_run(status="running")
    session = patch_phases(
        monkeypatch,
        run,
        extraction=ExtractionSummary(
            model="claude-sonnet-5",
            dry_run=False,
            awaiting_batch=True,
            batch_id="msgbatch_01",
            plan={"papers": 6, "to_extract": 6},
        ),
    )
    exported = {"called": False}

    async def should_not_export(*_args, **_kwargs):
        exported["called"] = True
        return {"rows": 0, "csv_path": None}

    monkeypatch.setattr(worker, "run_export_phase", should_not_export)

    assert await worker.run_datasheet_job(RUN_ID) is True

    assert run.status == "awaiting_batch"
    assert "msgbatch_01" in run.progress_message
    assert exported["called"] is False
    assert run.finished_at is None
    assert session.commits > 0


@pytest.mark.asyncio
async def test_a_parked_run_resumes_at_collection_and_skips_a_and_b(monkeypatch) -> None:
    """Re-running discovery on resume would re-query every source and re-fetch every
    paper — and produce a candidate set the paid batch no longer matches."""
    run = make_run(status="awaiting_batch", phase="extraction", extraction_batch_id="msgbatch_01")
    patch_phases(monkeypatch, run)
    phases_run: list[str] = []

    async def discovery_must_not_run(*_args, **_kwargs):
        phases_run.append("discovery")
        return {}

    async def acquisition_must_not_run(*_args, **_kwargs):
        phases_run.append("acquisition")
        return {}

    async def fake_collect(*_args, **_kwargs):
        return ExtractionSummary(
            model="claude-sonnet-5", dry_run=False, extracted=4, reused=1, prompt_tokens=30_000
        )

    monkeypatch.setattr(worker, "run_discovery_phase", discovery_must_not_run)
    monkeypatch.setattr(worker, "run_acquisition_phase", acquisition_must_not_run)
    monkeypatch.setattr(worker, "collect_extraction_batch", fake_collect)
    monkeypatch.setattr(worker, "extraction_provider", lambda: object())

    assert await worker.run_datasheet_job(RUN_ID) is True

    assert phases_run == []
    assert run.status == "succeeded"
    assert run.extracted_count == 4
    assert "1 reused from cache" in run.log_tail


@pytest.mark.asyncio
async def test_a_batch_still_processing_reports_no_work_so_the_loop_sleeps(monkeypatch) -> None:
    """Returning "work done" here would spin: the loop would re-claim the same run
    immediately and poll the batch endpoint as fast as it can."""
    run = make_run(status="awaiting_batch", extraction_batch_id="msgbatch_01")
    patch_phases(monkeypatch, run)

    async def still_processing(*_args, **_kwargs):
        return ExtractionSummary(model="claude-sonnet-5", awaiting_batch=True, batch_id="msgbatch_01")

    monkeypatch.setattr(worker, "collect_extraction_batch", still_processing)
    monkeypatch.setattr(worker, "extraction_provider", lambda: object())

    assert await worker.run_datasheet_job(RUN_ID) is False
    assert run.status == "awaiting_batch"


@pytest.mark.asyncio
async def test_cancelling_a_parked_run_cancels_the_batch_before_giving_up_on_it(
    monkeypatch,
) -> None:
    run = make_run(status="cancel_requested", extraction_batch_id="msgbatch_01")
    patch_phases(monkeypatch, run, cancelled=True)
    cancelled: list[str] = []

    async def fake_cancel(_provider, target_run):
        cancelled.append(target_run.extraction_batch_id)
        return True

    monkeypatch.setattr(worker, "cancel_extraction_batch", fake_cancel)
    monkeypatch.setattr(worker, "extraction_provider", lambda: object())

    await worker.run_datasheet_job(RUN_ID)

    assert cancelled == ["msgbatch_01"]
    assert run.status == "cancelled"
    # Says plainly that cancelling is not free.
    assert "still billed" in run.log_tail


@pytest.mark.asyncio
async def test_a_parked_run_with_no_provider_fails_with_the_batch_id(monkeypatch) -> None:
    """Parking forever would hide a batch that is being billed and that nobody will
    ever read. The error names it so it can be cancelled by hand."""
    run = make_run(status="awaiting_batch", extraction_batch_id="msgbatch_01")
    patch_phases(monkeypatch, run)
    monkeypatch.setattr(worker, "extraction_provider", lambda: None)

    await worker.run_datasheet_job(RUN_ID)

    assert run.status == "failed"
    assert "msgbatch_01" in run.error


@pytest.mark.asyncio
async def test_a_requeued_run_at_phase_extraction_starts_at_d(monkeypatch) -> None:
    """What `reextract` queues. Discovery and acquisition are unchanged, so repeating
    them would cost thousands of upstream records for nothing."""
    run = make_run(status="running", phase="extraction")
    patch_phases(monkeypatch, run)
    phases_run: list[str] = []

    async def discovery_must_not_run(*_args, **_kwargs):
        phases_run.append("discovery")
        return {}

    monkeypatch.setattr(worker, "run_discovery_phase", discovery_must_not_run)

    await worker.run_datasheet_job(RUN_ID)

    assert phases_run == []
    assert "Re-extracting" in run.log_tail
    assert run.status == "succeeded"


class ClaimSession:
    """Captures the claim query and hands back one run."""

    def __init__(self, run):
        self.run = run
        self.statements: list = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None

    def begin(self):
        class _Tx:
            async def __aenter__(self_inner):
                return None

            async def __aexit__(self_inner, *_args):
                return None

        return _Tx()

    async def execute(self, statement):
        self.statements.append(statement)
        return SimpleNamespace(scalars=lambda: SimpleNamespace(first=lambda: self.run))


@pytest.mark.asyncio
async def test_the_claim_query_also_takes_parked_runs_that_are_due_a_poll(monkeypatch) -> None:
    run = make_run(status="awaiting_batch", extraction_batch_id="msgbatch_01")
    session = ClaimSession(run)
    monkeypatch.setattr(worker, "AsyncSessionLocal", lambda: session)

    claimed = await worker.claim_next_run()

    assert claimed == RUN_ID
    sql = str(session.statements[0])
    # Both halves matter: without the status the parked run is never picked up, and
    # without the polled_at predicate it is picked up on every single loop.
    assert "extraction_batch_polled_at" in sql
    assert "awaiting_batch" in session.statements[0].compile().params.values()
    # Left parked, and stamped: a crash mid-collection must leave it re-claimable,
    # and the stamp is what throttles the next claim.
    assert run.status == "awaiting_batch"
    assert run.extraction_batch_polled_at is not None


@pytest.mark.asyncio
async def test_claiming_a_queued_run_marks_it_running(monkeypatch) -> None:
    run = make_run(status="queued")
    monkeypatch.setattr(worker, "AsyncSessionLocal", lambda: ClaimSession(run))

    await worker.claim_next_run()

    assert run.status == "running"
    assert run.started_at is not None


@pytest.mark.asyncio
async def test_polling_reports_when_there_was_nothing_to_claim(monkeypatch) -> None:
    async def nothing_queued():
        return None

    monkeypatch.setattr(worker, "claim_next_run", nothing_queued)
    assert await worker.poll_once() is False


@pytest.mark.asyncio
async def test_a_round_one_run_still_stops_where_it_was_queued_to(monkeypatch) -> None:
    """Rows created before extraction existed carry stop_after_phase='ingestion'.
    Sweeping them into a phase they were never queued for would change what an
    already-completed run means."""
    run = make_run(status="running", stop_after_phase="ingestion")
    patch_phases(monkeypatch, run)

    await worker.run_datasheet_job(RUN_ID)

    assert run.status == "succeeded"
    assert run.phase == "acquisition"
    assert "stopped after acquisition" in run.log_tail
    assert run.extracted_count is None
