"""Phase D: the extraction pass, its dry run, and the datasheet CSV.

No network and no database: the provider is a fake that records what it was asked
for, so what is measured is this layer's own behaviour — cost projection, batch
keying, escalation budgeting, and the shape of a persisted cell.
"""

import json
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy.dialects import postgresql

from app.core.config import settings
from app.datasheet import extraction_cache, extractor
from app.datasheet.extractor import (
    ExtractionPlan,
    PaperInput,
    build_batch_requests,
    cells_needing_escalation,
    load_fulltext_payload,
    system_prompt_for,
    template_specs,
)
from app.db.models import DatasheetExtractionCache
from app.providers.base import BatchResult, BatchStatus, CompletionUsage, StructuredResult
from pipelines.acquisition.cache_layout import cache_paths
from pipelines.extraction.csv_writer import header, write_datasheet_csv
from pipelines.extraction.sections import select_sections
from pipelines.extraction.template import NOT_REPORTED, column_specs_from_rows

COLUMNS = [
    {"key": "compounds", "label": "Compounds", "kind": "free_text", "order_index": 0,
     "extraction_hint": "Target product(s).", "source_hint": "any", "enabled": True},
    {"key": "concentration_yield", "label": "Concentration/Yield", "kind": "numeric",
     "order_index": 1, "source_hint": "fulltext", "enabled": True},
    {"key": "standard_product_class", "label": "Standard Product Class", "kind": "controlled",
     "order_index": 2, "vocabulary": ["Organic Acids", "Microbial Lipids"], "enabled": True},
    {"key": "retired", "label": "Retired", "kind": "free_text", "order_index": 3, "enabled": False},
]

PAYLOAD = {
    "source_format": "xml",
    "title": "Engineering Yarrowia lipolytica",
    "abstract": "We reached 50 g/L citric acid.",
    "warnings": [],
    "sections": [
        {"label": "methods", "heading": "Methods", "text": "Grown on glucose in YPD."},
        {"label": "results", "heading": "Results", "text": "Titre reached 50 g/L."},
    ],
}


def make_run(**overrides):
    data = {
        "id": uuid.uuid4(),
        "name": "yarrowia",
        "template_snapshot": {"name": "rlalab-datasheet-v1", "version": 3, "columns": COLUMNS},
        "config_snapshot": {},
        "extraction_batch_id": None,
        "extraction_batch_submitted_at": None,
        "extraction_batch_polled_at": None,
    }
    data.update(overrides)
    return SimpleNamespace(**data)


async def submit_then_collect(db, run, provider, cache_root, progress=None):
    """The two halves of a live batch pass: submit and park, then collect.

    They are separate calls in production too — the worker returns between them, so
    the ingestion queue keeps moving while the batch runs.
    """
    parked = await extractor.run_extraction_phase(
        db, run, cache_root=cache_root, provider=provider, dry_run=False, progress=progress
    )
    collected = await extractor.collect_extraction_batch(
        db, run, cache_root=cache_root, provider=provider, progress=progress
    )
    return parked, collected


def make_paper(payload=PAYLOAD, candidate_id=None) -> PaperInput:
    selection = select_sections(payload)
    return PaperInput(
        candidate_id=candidate_id or uuid.uuid4(),
        custom_id=str(candidate_id or uuid.uuid4()),
        identifier="10.1/a",
        title="Engineering Yarrowia lipolytica",
        selection=selection,
    )


def cell(value: str, confidence: float) -> dict:
    return {
        "value": value,
        "confidence": confidence,
        "evidence_quote": "q",
        "evidence_section": "results",
    }


class FakeProvider:
    """Records requests; returns canned structured results."""

    def __init__(self, *, data=None, tokens: int | None = 1000, batch: bool = True):
        self.data = data or {
            "compounds": cell("citric acid", 0.9),
            "concentration_yield": cell("50 g/L", 0.9),
            "standard_product_class": cell("Organic Acids", 0.9),
        }
        self.tokens = tokens
        self.batch = batch
        self.count_calls: list[str] = []
        self.structured_calls: list[dict] = []
        self.submitted: list[list] = []
        self.cancelled: list[str] = []

    async def count_prompt_tokens(self, *, system, content, model=None):
        if self.tokens is None:
            raise NotImplementedError("no tokeniser")
        self.count_calls.append(content)
        return self.tokens

    async def extract_structured(self, *, system, content, schema, max_tokens=8192, model=None):
        self.structured_calls.append({"model": model, "schema": schema, "content": content})
        keys = set(schema["properties"])
        return StructuredResult(
            data={key: value for key, value in self.data.items() if key in keys},
            usage=CompletionUsage(prompt_tokens=100, completion_tokens=20, model=model or "m",
                                  cached_tokens=40),
        )

    async def submit_batch(self, requests):
        if not self.batch:
            raise NotImplementedError("no batching")
        self.submitted.append(requests)
        return "batch_1"

    async def poll_batch(self, batch_id):
        return BatchStatus(id=batch_id, processing_status="ended", succeeded=len(self.submitted[0]))

    async def cancel_batch(self, batch_id):
        self.cancelled.append(batch_id)

    async def fetch_batch_results(self, batch_id):
        # Deliberately reversed: results come back in arbitrary order and must be
        # matched on custom_id, never on position.
        for request in reversed(self.submitted[0]):
            yield BatchResult(
                custom_id=request.custom_id,
                status="succeeded",
                data=self.data,
                usage=CompletionUsage(prompt_tokens=100, completion_tokens=20,
                                      model="claude-sonnet-5", cached_tokens=40),
            )


# ── Prompt and schema ─────────────────────────────────────────────────────────


def test_system_prompt_lists_enabled_columns_and_their_vocabularies() -> None:
    specs = template_specs(make_run())

    prompt = system_prompt_for(specs)

    assert "compounds (Compounds)" in prompt
    assert "one of: Organic Acids; Microbial Lipids" in prompt
    assert "retired" not in prompt


def test_system_prompt_forbids_borrowing_another_paper_s_numbers() -> None:
    """The failure this guards against is invisible in the output: the number is
    real, only the attribution is wrong."""
    prompt = system_prompt_for(template_specs(make_run()))

    assert "other groups' results" in prompt
    assert "cited study" in prompt


def test_system_prompt_is_stable_across_papers() -> None:
    """It carries the cache breakpoint. Anything per-paper or time-varying in here
    means the prompt cache never reads and the run silently costs more."""
    specs = template_specs(make_run())

    assert system_prompt_for(specs) == system_prompt_for(specs)


# ── Dry run ───────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_plan_counts_tokens_with_the_provider_when_available(tmp_path, monkeypatch) -> None:
    run = make_run()
    provider = FakeProvider(tokens=8_350)
    candidate = SimpleNamespace(id=uuid.uuid4(), doi="10.1/a", pmid=None, pmc_id=None, title="T")
    _write_payload(tmp_path, "10.1/a", PAYLOAD)
    db = _FakeDb([candidate])

    plan = await extractor.plan_extraction(db, run, cache_root=tmp_path, provider=provider)

    assert plan.paper_count == 1
    assert plan.token_method == "provider"
    assert plan.input_tokens == 8_350


@pytest.mark.asyncio
async def test_plan_falls_back_to_an_estimate_and_says_which_it_used(tmp_path) -> None:
    run = make_run()
    candidate = SimpleNamespace(id=uuid.uuid4(), doi="10.1/a", pmid=None, pmc_id=None, title="T")
    _write_payload(tmp_path, "10.1/a", PAYLOAD)

    plan = await extractor.plan_extraction(
        _FakeDb([candidate]), run, cache_root=tmp_path, provider=FakeProvider(tokens=None)
    )

    assert plan.token_method == "estimated_from_chars"
    assert plan.as_dict()["token_method"] == "estimated_from_chars"


@pytest.mark.asyncio
async def test_papers_with_no_fetched_text_are_counted_not_silently_dropped(tmp_path) -> None:
    run = make_run()
    fetched = SimpleNamespace(id=uuid.uuid4(), doi="10.1/a", pmid=None, pmc_id=None, title="T")
    paywalled = SimpleNamespace(id=uuid.uuid4(), doi="10.1/b", pmid=None, pmc_id=None, title="T2")
    _write_payload(tmp_path, "10.1/a", PAYLOAD)

    plan = await extractor.plan_extraction(
        _FakeDb([fetched, paywalled]), run, cache_root=tmp_path, provider=None
    )

    assert plan.paper_count == 1
    assert plan.skipped_no_text == ["10.1/b"]
    assert plan.as_dict()["skipped_no_text"] == 1


@pytest.mark.asyncio
async def test_max_papers_per_run_is_a_second_ceiling(tmp_path) -> None:
    run = make_run()
    candidates = []
    for index in range(3):
        doi = f"10.1/{index}"
        candidates.append(SimpleNamespace(id=uuid.uuid4(), doi=doi, pmid=None, pmc_id=None, title="T"))
        _write_payload(tmp_path, doi, PAYLOAD)

    plan = await extractor.plan_extraction(
        _FakeDb(candidates), run, cache_root=tmp_path, provider=None, max_papers=2
    )

    assert plan.paper_count == 2
    assert plan.skipped_over_cap == 1


def test_projected_cost_uses_batch_rates() -> None:
    plan = ExtractionPlan(model="claude-sonnet-5")
    plan.papers = [make_paper() for _ in range(700)]
    for paper in plan.papers:
        paper.prompt_tokens = 8_350

    # 700 × 8,350 input at $1.00/MTok + 700 × 1,500 output at $5.00/MTok.
    assert plan.projected_cost_usd() == pytest.approx(5.845 + 5.25, rel=0.01)


def test_unknown_model_projects_zero_rather_than_a_wrong_number() -> None:
    plan = ExtractionPlan(model="some-future-model")
    plan.papers = [make_paper()]

    assert plan.projected_cost_usd() == 0.0


# ── The gate ──────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_extraction_is_a_dry_run_unless_explicitly_enabled(tmp_path, monkeypatch) -> None:
    """Extraction is the only phase that sends paper text off-site. It does not
    happen because a job was queued."""
    monkeypatch.setattr(settings, "datasheet_extraction_enabled", False)
    run = make_run()
    candidate = SimpleNamespace(id=uuid.uuid4(), doi="10.1/a", pmid=None, pmc_id=None, title="T")
    _write_payload(tmp_path, "10.1/a", PAYLOAD)
    provider = FakeProvider()

    summary = await extractor.run_extraction_phase(
        _FakeDb([candidate]), run, cache_root=tmp_path, provider=provider, dry_run=False
    )

    assert summary.dry_run is True
    assert summary.extracted == 0
    assert provider.structured_calls == []
    assert provider.submitted == []
    assert summary.plan["papers"] == 1


@pytest.mark.asyncio
async def test_a_missing_provider_downgrades_to_a_dry_run(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(settings, "datasheet_extraction_enabled", True)
    run = make_run()
    candidate = SimpleNamespace(id=uuid.uuid4(), doi="10.1/a", pmid=None, pmc_id=None, title="T")
    _write_payload(tmp_path, "10.1/a", PAYLOAD)

    summary = await extractor.run_extraction_phase(
        _FakeDb([candidate]), run, cache_root=tmp_path, provider=None, dry_run=False
    )

    assert summary.dry_run is True


# ── Batch pass ────────────────────────────────────────────────────────────────


def test_batch_requests_carry_one_custom_id_per_paper() -> None:
    papers = [make_paper(candidate_id=uuid.uuid4()) for _ in range(3)]

    requests = build_batch_requests(
        papers, system="sys", schema={"type": "object"}, model="claude-sonnet-5"
    )

    assert [request.custom_id for request in requests] == [p.custom_id for p in papers]
    assert {request.model for request in requests} == {"claude-sonnet-5"}


@pytest.mark.asyncio
async def test_batch_results_are_matched_on_custom_id_not_position(tmp_path, monkeypatch) -> None:
    """The fake returns results reversed. Matching on position would attribute
    every paper's values to a different paper."""
    monkeypatch.setattr(settings, "datasheet_extraction_enabled", True)
    monkeypatch.setattr(settings, "datasheet_escalation_enabled", False)
    run = make_run()
    candidates = []
    for index in range(3):
        doi = f"10.1/{index}"
        candidates.append(
            SimpleNamespace(id=uuid.uuid4(), doi=doi, pmid=None, pmc_id=None, title=f"T{index}")
        )
        _write_payload(tmp_path, doi, PAYLOAD)
    db = _FakeDb(candidates)
    provider = FakeProvider()

    _parked, summary = await submit_then_collect(db, run, provider, tmp_path)

    assert summary.extracted == 3
    assert {str(row.candidate_id) for row in db.added} == {str(c.id) for c in candidates}


# ── Park and resume ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_submitting_a_batch_parks_the_run_instead_of_waiting_on_it(
    tmp_path, monkeypatch
) -> None:
    """One process serves the ingestion queue too. Sitting in a poll loop for the
    1-24 hours a batch can take would block every job an admin is watching."""
    monkeypatch.setattr(settings, "datasheet_extraction_enabled", True)
    run = make_run()
    candidate = SimpleNamespace(id=uuid.uuid4(), doi="10.1/a", pmid=None, pmc_id=None, title="T")
    _write_payload(tmp_path, "10.1/a", PAYLOAD)
    provider = FakeProvider()

    summary = await extractor.run_extraction_phase(
        _FakeDb([candidate]), run, cache_root=tmp_path, provider=provider, dry_run=False
    )

    assert summary.awaiting_batch is True
    assert summary.batch_id == "batch_1"
    assert summary.extracted == 0
    # The id is on the run, not in a local variable: a restart here resumes rather
    # than orphaning a batch that is already being billed.
    assert run.extraction_batch_id == "batch_1"
    assert run.extraction_batch_submitted_at is not None


@pytest.mark.asyncio
async def test_a_still_processing_batch_re_parks_without_collecting(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(settings, "datasheet_extraction_enabled", True)
    run = make_run()
    candidate = SimpleNamespace(id=uuid.uuid4(), doi="10.1/a", pmid=None, pmc_id=None, title="T")
    _write_payload(tmp_path, "10.1/a", PAYLOAD)
    db = _FakeDb([candidate])
    provider = FakeProvider()

    async def still_running(batch_id):
        return BatchStatus(id=batch_id, processing_status="in_progress", processing=1)

    await extractor.run_extraction_phase(
        db, run, cache_root=tmp_path, provider=provider, dry_run=False
    )
    provider.poll_batch = still_running
    polled_before = run.extraction_batch_polled_at

    summary = await extractor.collect_extraction_batch(
        db, run, cache_root=tmp_path, provider=provider
    )

    assert summary.awaiting_batch is True
    assert summary.extracted == 0
    assert db.added == []
    # Re-stamped, which is what throttles the next claim.
    assert run.extraction_batch_polled_at >= polled_before
    assert run.extraction_batch_id == "batch_1"


@pytest.mark.asyncio
async def test_resuming_matches_results_to_papers_by_identifier(tmp_path, monkeypatch) -> None:
    """Resume rebuilds the paper list rather than remembering it. The reversed
    results and the shuffled candidate order together mean any positional matching
    attributes values to the wrong paper."""
    monkeypatch.setattr(settings, "datasheet_extraction_enabled", True)
    monkeypatch.setattr(settings, "datasheet_escalation_enabled", False)
    run = make_run()
    candidates = []
    for index in range(3):
        doi = f"10.1/{index}"
        candidates.append(
            SimpleNamespace(id=uuid.uuid4(), doi=doi, pmid=None, pmc_id=None, title=f"T{index}")
        )
        _write_payload(tmp_path, doi, PAYLOAD)
    db = _FakeDb(candidates)
    provider = FakeProvider()

    await extractor.run_extraction_phase(
        db, run, cache_root=tmp_path, provider=provider, dry_run=False
    )
    # A fresh session on the other side of a worker restart: nothing carried over
    # but the batch id on the run.
    resumed = _FakeDb(list(reversed(candidates)))
    summary = await extractor.collect_extraction_batch(
        resumed, run, cache_root=tmp_path, provider=provider
    )

    assert summary.extracted == 3
    assert {str(row.candidate_id) for row in resumed.added} == {str(c.id) for c in candidates}
    # Cleared on success, so a later re-claim cannot re-collect a finished batch.
    assert run.extraction_batch_id is None


@pytest.mark.asyncio
async def test_a_result_whose_candidate_vanished_is_skipped_not_guessed_at(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setattr(settings, "datasheet_extraction_enabled", True)
    monkeypatch.setattr(settings, "datasheet_escalation_enabled", False)
    run = make_run()
    kept = SimpleNamespace(id=uuid.uuid4(), doi="10.1/a", pmid=None, pmc_id=None, title="T")
    deleted = SimpleNamespace(id=uuid.uuid4(), doi="10.1/b", pmid=None, pmc_id=None, title="T2")
    for candidate in (kept, deleted):
        _write_payload(tmp_path, candidate.doi, PAYLOAD)
    db = _FakeDb([kept, deleted])
    provider = FakeProvider()

    await extractor.run_extraction_phase(
        db, run, cache_root=tmp_path, provider=provider, dry_run=False
    )
    resumed = _FakeDb([kept])          # the other candidate is gone
    summary = await extractor.collect_extraction_batch(
        resumed, run, cache_root=tmp_path, provider=provider
    )

    assert summary.extracted == 1
    assert summary.failed == 0
    assert [str(row.candidate_id) for row in resumed.added] == [str(kept.id)]


@pytest.mark.asyncio
async def test_cancellation_before_submission_spends_nothing(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(settings, "datasheet_extraction_enabled", True)
    run = make_run()
    candidate = SimpleNamespace(id=uuid.uuid4(), doi="10.1/a", pmid=None, pmc_id=None, title="T")
    _write_payload(tmp_path, "10.1/a", PAYLOAD)
    provider = FakeProvider()

    summary = await extractor.run_extraction_phase(
        _FakeDb([candidate]),
        run,
        cache_root=tmp_path,
        provider=provider,
        dry_run=False,
        is_cancelled=lambda: True,
    )

    assert provider.submitted == []
    assert summary.awaiting_batch is False
    assert run.extraction_batch_id is None


@pytest.mark.asyncio
async def test_cancelling_a_batch_is_best_effort_and_never_raises() -> None:
    """A provider that cannot be reached must not stop the run from cancelling —
    the batch id stays on the row so the cost is traceable rather than invisible."""
    run = make_run(extraction_batch_id="batch_1")
    provider = FakeProvider()

    assert await extractor.cancel_extraction_batch(provider, run) is True
    assert provider.cancelled == ["batch_1"]

    async def unreachable(_batch_id):
        raise RuntimeError("connection reset")

    provider.cancel_batch = unreachable
    assert await extractor.cancel_extraction_batch(provider, run) is False
    assert run.extraction_batch_id == "batch_1"

    # Nothing to cancel is not an error, and neither is having no provider.
    assert await extractor.cancel_extraction_batch(provider, make_run()) is False
    assert await extractor.cancel_extraction_batch(None, run) is False


# ── Result cache ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_a_cached_paper_produces_a_row_without_touching_the_provider(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setattr(settings, "datasheet_extraction_enabled", True)
    run = make_run()
    candidate = SimpleNamespace(id=uuid.uuid4(), doi="10.1/a", pmid=None, pmc_id=None, title="T")
    _write_payload(tmp_path, "10.1/a", PAYLOAD)
    db = _FakeDb([candidate], cache_entries=[cache_entry(select_sections(PAYLOAD).text)])
    provider = FakeProvider()

    summary = await extractor.run_extraction_phase(
        db, run, cache_root=tmp_path, provider=provider, dry_run=False
    )

    assert summary.reused == 1
    assert summary.extracted == 1
    assert provider.submitted == []
    assert provider.structured_calls == []
    assert db.added[0].cells["compounds"]["value"] == "cached citrate"
    # Token columns stay empty: this pass spent nothing, and copying the original
    # figures would report money as spent twice.
    assert db.added[0].prompt_tokens is None
    assert marked(db, candidate.id) == ("cached", None)


@pytest.mark.asyncio
async def test_a_template_version_bump_misses_the_cache(tmp_path, monkeypatch) -> None:
    """A new column set is a different question, so an old answer must not stand in."""
    monkeypatch.setattr(settings, "datasheet_extraction_enabled", True)
    run = make_run(template_snapshot={"name": "t", "version": 4, "columns": COLUMNS})
    candidate = SimpleNamespace(id=uuid.uuid4(), doi="10.1/a", pmid=None, pmc_id=None, title="T")
    _write_payload(tmp_path, "10.1/a", PAYLOAD)
    db = _FakeDb(
        [candidate],
        cache_entries=[cache_entry(select_sections(PAYLOAD).text, template_version=3)],
    )

    plan = await extractor.plan_extraction(db, run, cache_root=tmp_path, provider=None)

    assert plan.cached_papers == []
    assert len(plan.pending) == 1


@pytest.mark.asyncio
async def test_a_changed_section_budget_misses_the_cache(tmp_path, monkeypatch) -> None:
    """The key is the hash of the text actually sent. Change what gets selected and
    the prompt changes, so a stored result no longer answers the question asked."""
    monkeypatch.setattr(settings, "datasheet_max_section_tokens", 24_000)
    run = make_run()
    candidate = SimpleNamespace(id=uuid.uuid4(), doi="10.1/a", pmid=None, pmc_id=None, title="T")
    _write_payload(tmp_path, "10.1/a", PAYLOAD)
    entries = [cache_entry(select_sections(PAYLOAD).text)]

    hit = await extractor.plan_extraction(
        _FakeDb([candidate], cache_entries=entries), run, cache_root=tmp_path, provider=None
    )
    monkeypatch.setattr(settings, "datasheet_max_section_tokens", 20)
    miss = await extractor.plan_extraction(
        _FakeDb([candidate], cache_entries=entries), run, cache_root=tmp_path, provider=None
    )

    assert len(hit.cached_papers) == 1
    assert miss.cached_papers == []


@pytest.mark.asyncio
async def test_the_dry_run_excludes_cached_papers_from_the_projected_cost(
    tmp_path, monkeypatch
) -> None:
    """A projection answers "what will this cost me now", not "what would it have
    cost from scratch"."""
    monkeypatch.setattr(settings, "datasheet_extraction_enabled", False)
    monkeypatch.setattr(settings, "datasheet_extraction_model", "claude-sonnet-5")
    run = make_run()
    candidates = []
    for index in range(2):
        doi = f"10.1/{index}"
        candidates.append(SimpleNamespace(id=uuid.uuid4(), doi=doi, pmid=None, pmc_id=None, title="T"))
        _write_payload(tmp_path, doi, PAYLOAD)
    db = _FakeDb(candidates, cache_entries=[cache_entry(select_sections(PAYLOAD).text)])

    # Both papers hash the same text here, so one entry covers both.
    plan = await extractor.plan_extraction(db, run, cache_root=tmp_path, provider=None)

    assert plan.paper_count == 2
    assert len(plan.cached_papers) == 2
    assert plan.as_dict()["cached"] == 2
    assert plan.as_dict()["to_extract"] == 0
    assert plan.projected_cost_usd() == 0.0


@pytest.mark.asyncio
async def test_a_fresh_extraction_writes_a_cache_entry_after_escalation(
    tmp_path, monkeypatch
) -> None:
    """Stored after escalation, so a re-run inherits the escalated values rather
    than re-paying the stronger model for the same cells."""
    monkeypatch.setattr(settings, "datasheet_extraction_enabled", True)
    monkeypatch.setattr(settings, "datasheet_use_batch_api", False)
    monkeypatch.setattr(settings, "datasheet_escalation_enabled", True)
    monkeypatch.setattr(settings, "datasheet_escalation_max_fraction", 1.0)
    run = make_run()
    candidate = SimpleNamespace(id=uuid.uuid4(), doi="10.1/a", pmid=None, pmc_id=None, title="T")
    _write_payload(tmp_path, "10.1/a", PAYLOAD)
    db = _FakeDb([candidate])
    provider = FakeProvider(
        data={
            "compounds": cell("citric acid", 0.95),
            "concentration_yield": cell(NOT_REPORTED, 0.2),
            "standard_product_class": cell("Organic Acids", 0.95),
        }
    )

    await extractor.run_extraction_phase(
        db, run, cache_root=tmp_path, provider=provider, dry_run=False
    )

    entry = db.cache_writes[0]
    assert entry["content_sha256"] == extraction_cache.content_hash(select_sections(PAYLOAD).text)
    assert entry["template_version"] == 3
    assert entry["model"] == "claude-sonnet-5"
    assert entry["escalated_cells"] == 1
    assert entry["cells"]["concentration_yield"]["escalated"] is True


@pytest.mark.asyncio
async def test_a_refused_paper_is_one_missing_row_not_a_failed_run(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(settings, "datasheet_extraction_enabled", True)
    monkeypatch.setattr(settings, "datasheet_use_batch_api", False)
    monkeypatch.setattr(settings, "datasheet_escalation_enabled", False)
    run = make_run()
    candidates = [
        SimpleNamespace(id=uuid.uuid4(), doi=f"10.1/{i}", pmid=None, pmc_id=None, title="T")
        for i in range(2)
    ]
    for candidate in candidates:
        _write_payload(tmp_path, candidate.doi, PAYLOAD)

    provider = FakeProvider()
    calls = {"n": 0}
    original = provider.extract_structured

    async def sometimes_refuses(**kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise ValueError("extraction refused by the model's safety classifiers")
        return await original(**kwargs)

    provider.extract_structured = sometimes_refuses

    summary = await extractor.run_extraction_phase(
        _FakeDb(candidates), run, cache_root=tmp_path, provider=provider, dry_run=False
    )

    assert summary.refused == 1
    assert summary.extracted == 1


# ── Cells and escalation ──────────────────────────────────────────────────────


def test_every_enabled_column_gets_a_cell_even_when_the_model_omits_it() -> None:
    specs = template_specs(make_run())

    cells = extractor._cells_from({"compounds": cell("citrate", 0.8)}, specs, source_tier="fulltext")

    assert set(cells) == {"compounds", "concentration_yield", "standard_product_class"}
    assert cells["concentration_yield"]["value"] == NOT_REPORTED
    assert cells["compounds"]["source_tier"] == "fulltext"


def test_confidence_is_clamped_and_never_crashes_on_junk() -> None:
    specs = template_specs(make_run())

    cells = extractor._cells_from(
        {"compounds": {"value": "x", "confidence": "not a number"},
         "concentration_yield": {"value": "y", "confidence": 5}},
        specs,
        source_tier="abstract",
    )

    assert cells["compounds"]["confidence"] == 0.0
    assert cells["concentration_yield"]["confidence"] == 1.0


def test_escalation_flags_low_confidence_and_not_reported_cells() -> None:
    cells = {
        "a": cell("value", 0.95),
        "b": cell("value", 0.2),
        "c": cell(NOT_REPORTED, 0.99),
    }

    assert sorted(cells_needing_escalation(cells, threshold=0.6)) == ["b", "c"]


@pytest.mark.asyncio
async def test_escalation_is_capped_so_a_bad_batch_cannot_multiply_the_bill(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setattr(settings, "datasheet_extraction_enabled", True)
    monkeypatch.setattr(settings, "datasheet_escalation_enabled", True)
    monkeypatch.setattr(settings, "datasheet_escalation_max_fraction", 0.10)
    run = make_run()
    candidates = []
    for index in range(4):
        doi = f"10.1/{index}"
        candidates.append(SimpleNamespace(id=uuid.uuid4(), doi=doi, pmid=None, pmc_id=None, title="T"))
        _write_payload(tmp_path, doi, PAYLOAD)

    # Everything comes back unsure: without a cap this would escalate every paper.
    provider = FakeProvider(
        data={
            "compounds": cell("citric acid", 0.1),
            "concentration_yield": cell(NOT_REPORTED, 0.1),
            "standard_product_class": cell("Organic Acids", 0.1),
        }
    )

    _parked, summary = await submit_then_collect(
        _FakeDb(candidates), run, provider, tmp_path
    )

    # 4 papers × 3 cells = 12 cells; a 10% budget is 1 cell, so no paper (3 flagged
    # cells each) fits and nothing is escalated.
    assert summary.escalated == 0
    assert summary.extracted == 4


@pytest.mark.asyncio
async def test_escalation_uses_the_stronger_model_on_only_the_flagged_columns(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setattr(settings, "datasheet_extraction_enabled", True)
    monkeypatch.setattr(settings, "datasheet_escalation_enabled", True)
    monkeypatch.setattr(settings, "datasheet_escalation_max_fraction", 1.0)
    monkeypatch.setattr(settings, "datasheet_use_batch_api", False)
    run = make_run()
    candidate = SimpleNamespace(id=uuid.uuid4(), doi="10.1/a", pmid=None, pmc_id=None, title="T")
    _write_payload(tmp_path, "10.1/a", PAYLOAD)

    provider = FakeProvider(
        data={
            "compounds": cell("citric acid", 0.95),
            "concentration_yield": cell(NOT_REPORTED, 0.2),
            "standard_product_class": cell("Organic Acids", 0.95),
        }
    )

    summary = await extractor.run_extraction_phase(
        _FakeDb([candidate]), run, cache_root=tmp_path, provider=provider, dry_run=False
    )

    escalation = provider.structured_calls[-1]
    assert escalation["model"] == settings.datasheet_escalation_model
    # Only the unsure column is re-asked — re-extracting the confident ones would
    # pay twice for answers already in hand.
    assert set(escalation["schema"]["properties"]) == {"concentration_yield"}
    assert summary.escalated == 1


# ── CSV ───────────────────────────────────────────────────────────────────────


def test_csv_header_is_the_curated_columns_then_provenance() -> None:
    specs = column_specs_from_rows(COLUMNS)

    columns = header(specs)

    assert columns[:3] == ["Compounds", "Concentration/Yield", "Standard Product Class"]
    assert "Retired" not in columns          # disabled columns are not exported
    assert columns[3:6] == ["doi", "pmid", "journal"]


def test_csv_writes_not_reported_for_empty_cells() -> None:
    specs = column_specs_from_rows(COLUMNS)
    rows = [{"cells": {"compounds": cell("citric acid", 0.9)}, "doi": "10.1/a", "year": 2020}]

    text = write_datasheet_csv(rows, specs)
    lines = text.splitlines()

    assert lines[0].startswith("Compounds,Concentration/Yield,Standard Product Class,doi")
    assert lines[1].startswith(f"citric acid,{NOT_REPORTED},{NOT_REPORTED},10.1/a")


def test_csv_renders_booleans_the_way_the_curators_write_them() -> None:
    specs = column_specs_from_rows(COLUMNS)
    rows = [{"cells": {}, "is_review": False, "is_retracted": True}]

    text = write_datasheet_csv(rows, specs)

    assert ",no," in text
    assert ",yes," in text


# ── Fixtures ──────────────────────────────────────────────────────────────────


def _write_payload(cache_root: Path, identifier: str, payload: dict) -> None:
    _asset, text_path = cache_paths(cache_root, identifier)
    text_path.parent.mkdir(parents=True, exist_ok=True)
    text_path.write_text(json.dumps(payload), encoding="utf-8")


def test_load_fulltext_payload_tolerates_a_corrupt_file(tmp_path) -> None:
    _asset, text_path = cache_paths(tmp_path, "10.1/a")
    text_path.parent.mkdir(parents=True, exist_ok=True)
    text_path.write_text("{not json", encoding="utf-8")

    assert load_fulltext_payload(tmp_path, "10.1/a") is None


class _FakeDb:
    """Minimal async session: serves candidates and cache entries, records writes.

    The cache lookup is honoured field by field rather than blanket-matched. The
    property under test is that the key is `(content_sha256, template_version,
    model)` — a fake that ignored two of the three would pass whatever the code did.
    """

    def __init__(self, candidates, cache_entries=None):
        self._candidates = candidates
        self._cache = list(cache_entries or [])
        self.added = []
        self.commits = 0
        self.marks: list[dict] = []          # candidate extraction_status writes
        self.cache_writes: list[dict] = []   # extraction cache upserts

    async def execute(self, statement):
        if statement.is_select:
            if statement.column_descriptions[0]["entity"] is DatasheetExtractionCache:
                params = statement.compile().params
                hashes = params.get("content_sha256_1") or []
                matches = [
                    entry
                    for entry in self._cache
                    if entry.content_sha256 in hashes
                    and entry.template_version == params.get("template_version_1")
                    and entry.model == params.get("model_1")
                ]
                return SimpleNamespace(scalars=lambda: matches)
            return SimpleNamespace(scalars=lambda: list(self._candidates))
        if statement.is_update:
            self.marks.append(statement.compile().params)
        elif statement.is_insert:
            self.cache_writes.append(statement.compile(dialect=postgresql.dialect()).params)
        return SimpleNamespace()

    def add(self, row):
        self.added.append(row)

    async def commit(self):
        self.commits += 1


def cache_entry(text: str, *, template_version=3, model="claude-sonnet-5", cells=None, escalated=0):
    """A stored result for the exact prompt `text` would produce."""
    return SimpleNamespace(
        content_sha256=extraction_cache.content_hash(text),
        template_version=template_version,
        model=model,
        cells=cells or {"compounds": cell("cached citrate", 0.9)},
        prompt_tokens=9_000,
        completion_tokens=1_400,
        escalated_cells=escalated,
    )


def marked(db: _FakeDb, candidate_id) -> tuple[str | None, str | None]:
    """The extraction status and reason recorded against one candidate."""
    for params in db.marks:
        if candidate_id in (params.get("id_1") or []):
            return params.get("extraction_status"), params.get("extraction_error")
    return None, None


# ── Reporting from phase D to completion ──────────────────────────────────────


@pytest.mark.asyncio
async def test_a_running_batch_reports_progress_rather_than_going_silent(
    tmp_path, monkeypatch
) -> None:
    """A batch can take an hour. A single unchanging message for that long is
    indistinguishable from a hung worker, and the usual response to a hung worker
    is a restart — in the middle of a paid batch."""
    monkeypatch.setattr(settings, "datasheet_extraction_enabled", True)
    monkeypatch.setattr(settings, "datasheet_escalation_enabled", False)
    run = make_run()
    candidate = SimpleNamespace(id=uuid.uuid4(), doi="10.1/a", pmid=None, pmc_id=None, title="T")
    _write_payload(tmp_path, "10.1/a", PAYLOAD)

    db = _FakeDb([candidate])
    provider = FakeProvider()
    lines: list[str] = []
    report = lambda message, _payload=None: lines.append(message)  # noqa: E731

    await extractor.run_extraction_phase(
        db, run, cache_root=tmp_path, provider=provider, dry_run=False, progress=report
    )
    still_running = BatchStatus(id="batch_1", processing_status="in_progress", processing=1)
    provider.poll_batch = lambda _batch_id=None: _resolved(still_running)
    await extractor.collect_extraction_batch(
        db, run, cache_root=tmp_path, provider=provider, progress=report
    )
    provider.poll_batch = FakeProvider.poll_batch.__get__(provider)
    await extractor.collect_extraction_batch(
        db, run, cache_root=tmp_path, provider=provider, progress=report
    )

    assert any("submitted with 1 papers" in line for line in lines)
    assert any("parked until it ends" in line for line in lines)
    assert any("processing" in line for line in lines)
    assert any("collecting results" in line for line in lines)
    assert any("Extracted 1 rows" in line for line in lines)


async def _resolved(value):
    return value


# ── Failure attribution ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_a_refusal_records_its_reason_on_the_candidate(tmp_path, monkeypatch) -> None:
    """A refused paper has no datasheet row by design, so `1 refused` is the only
    trace unless the reason is written where the paper is."""
    monkeypatch.setattr(settings, "datasheet_extraction_enabled", True)
    monkeypatch.setattr(settings, "datasheet_use_batch_api", False)
    monkeypatch.setattr(settings, "datasheet_escalation_enabled", False)
    run = make_run()
    candidate = SimpleNamespace(id=uuid.uuid4(), doi="10.1/a", pmid=None, pmc_id=None, title="T")
    _write_payload(tmp_path, "10.1/a", PAYLOAD)
    db = _FakeDb([candidate])
    provider = FakeProvider()

    async def refuses(**_kwargs):
        raise ValueError("extraction refused by the model's safety classifiers (category=cyber)")

    provider.extract_structured = refuses

    summary = await extractor.run_extraction_phase(
        db, run, cache_root=tmp_path, provider=provider, dry_run=False
    )

    assert summary.refused == 1
    assert db.added == []
    state, reason = marked(db, candidate.id)
    assert state == "refused"
    assert "safety classifiers" in reason


@pytest.mark.asyncio
async def test_a_paper_with_no_fetched_text_is_recorded_as_such(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(settings, "datasheet_extraction_enabled", True)
    monkeypatch.setattr(settings, "datasheet_use_batch_api", False)
    monkeypatch.setattr(settings, "datasheet_escalation_enabled", False)
    run = make_run()
    fetched = SimpleNamespace(id=uuid.uuid4(), doi="10.1/a", pmid=None, pmc_id=None, title="T")
    paywalled = SimpleNamespace(id=uuid.uuid4(), doi="10.1/b", pmid=None, pmc_id=None, title="T2")
    _write_payload(tmp_path, "10.1/a", PAYLOAD)
    db = _FakeDb([fetched, paywalled])

    await extractor.run_extraction_phase(
        db, run, cache_root=tmp_path, provider=FakeProvider(), dry_run=False
    )

    assert marked(db, paywalled.id) == ("no_text", None)
    assert marked(db, fetched.id) == ("extracted", None)


@pytest.mark.asyncio
async def test_a_dry_run_records_nothing_against_a_candidate(tmp_path, monkeypatch) -> None:
    """The dry run is a projection. Writing an outcome for a paper nothing was done
    to would make an unattempted run look attempted."""
    monkeypatch.setattr(settings, "datasheet_extraction_enabled", False)
    run = make_run()
    candidate = SimpleNamespace(id=uuid.uuid4(), doi="10.1/a", pmid=None, pmc_id=None, title="T")
    _write_payload(tmp_path, "10.1/a", PAYLOAD)
    db = _FakeDb([candidate])

    await extractor.run_extraction_phase(
        db, run, cache_root=tmp_path, provider=FakeProvider(), dry_run=False
    )

    assert db.marks == []
    assert db.cache_writes == []


@pytest.mark.asyncio
async def test_the_dry_run_reports_its_projection_through_the_same_channel(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setattr(settings, "datasheet_extraction_enabled", False)
    run = make_run()
    candidate = SimpleNamespace(id=uuid.uuid4(), doi="10.1/a", pmid=None, pmc_id=None, title="T")
    _write_payload(tmp_path, "10.1/a", PAYLOAD)
    lines: list[str] = []

    await extractor.run_extraction_phase(
        _FakeDb([candidate]),
        run,
        cache_root=tmp_path,
        provider=FakeProvider(),
        dry_run=False,
        progress=lambda message, _payload=None: lines.append(message),
    )

    assert any("papers ready" in line for line in lines)


@pytest.mark.asyncio
async def test_a_capped_escalation_says_what_it_skipped(tmp_path, monkeypatch) -> None:
    """Silence here reads as 'nothing needed escalating', which is the opposite of
    what happened."""
    monkeypatch.setattr(settings, "datasheet_extraction_enabled", True)
    monkeypatch.setattr(settings, "datasheet_escalation_enabled", True)
    monkeypatch.setattr(settings, "datasheet_escalation_max_fraction", 0.0)
    monkeypatch.setattr(settings, "datasheet_use_batch_api", False)
    run = make_run()
    candidate = SimpleNamespace(id=uuid.uuid4(), doi="10.1/a", pmid=None, pmc_id=None, title="T")
    _write_payload(tmp_path, "10.1/a", PAYLOAD)
    lines: list[str] = []

    summary = await extractor.run_extraction_phase(
        _FakeDb([candidate]),
        run,
        cache_root=tmp_path,
        provider=FakeProvider(data={"compounds": cell(NOT_REPORTED, 0.1)}),
        dry_run=False,
        progress=lambda message, _payload=None: lines.append(message),
    )

    assert summary.escalation_skipped == 1
    assert summary.as_dict()["escalation_skipped"] == 1
    assert any("Escalation budget reached" in line for line in lines)


# ── Phase E: export ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_export_writes_the_datasheet_beside_the_assets(tmp_path, monkeypatch) -> None:
    """A run's deliverable should be an artefact on disk, not only an HTTP
    response: recoverable on another host and reviewable with the app down."""
    from app.datasheet import export_service

    monkeypatch.setattr(export_service, "count_rows", _count(2))
    monkeypatch.setattr(
        export_service,
        "datasheet_csv_for_run",
        _csv("Compounds,doi\ncitric acid,10.1/a\n"),
    )
    monkeypatch.setattr(
        "app.ingestion.admin_service.store_cache_path", lambda path: f"data/corpora/{Path(path).name}"
    )
    run = make_run(csv_path=None)
    lines: list[str] = []

    result = await export_service.run_export_phase(
        _FakeDb([]),
        run,
        cache_root=tmp_path,
        progress=lambda message, _payload=None: lines.append(message),
    )

    written = tmp_path / export_service.CSV_FILE_NAME
    assert written.read_text().startswith("Compounds,doi")
    assert result["rows"] == 2
    # Stored repo-relative: an absolute path means "wherever the writer's
    # filesystem was" and breaks the moment a container and a host share a db.
    assert run.csv_path == "data/corpora/datasheet.csv"
    assert any("Wrote 2 rows" in line for line in lines)


@pytest.mark.asyncio
async def test_export_writes_nothing_when_there_are_no_rows(tmp_path, monkeypatch) -> None:
    """A dry run legitimately produces no rows. A header-only file would look like
    a real, empty datasheet."""
    from app.datasheet import export_service

    monkeypatch.setattr(export_service, "count_rows", _count(0))
    run = make_run(csv_path=None)

    result = await export_service.run_export_phase(_FakeDb([]), run, cache_root=tmp_path)

    assert result == {"rows": 0, "csv_path": None}
    assert not (tmp_path / export_service.CSV_FILE_NAME).exists()
    assert run.csv_path is None


def _count(value: int):
    async def counter(_db, _run_id):
        return value

    return counter


def _csv(text: str):
    async def render(_db, _run):
        return text

    return render
