import asyncio
import uuid
from contextlib import asynccontextmanager
from datetime import date, datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from fastapi import HTTPException

from app.api import deps
from app.db.models import User
from app.ingestion.admin_service import (
    ALLOWED_CACHE_ROOT,
    APPROVED_CONFIG_DIR,
    get_worker_status,
    get_approved_config,
    list_approved_configs,
    load_ingestion_defaults,
    resolve_cache_path,
    store_cache_path,
    write_worker_heartbeat,
)
from app.ingestion.worker import (
    append_log,
    dump_toml_sections,
    format_toml_value,
    maintain_running_heartbeat,
    run_job,
)
from app.main import app
from pipelines.corpus_cache import CorpusCache, CorpusManifest


def make_admin(role: str = "admin") -> User:
    return User(
        id=uuid.uuid4(),
        email=f"{role}@example.com",
        hashed_password="hashed",
        full_name="Admin",
        role=role,
        is_active=True,
        token_limit=1_000_000,
    )


class DummyDB:
    pass


class FakeWorkerSession:
    def __init__(self, job):
        self.job = job

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None

    def begin(self):
        return self

    async def get(self, _model, _job_id):
        return self.job


def fake_worker_session_factory(job):
    return lambda: FakeWorkerSession(job)


def config_name_for_source(source: str) -> str:
    for config in list_approved_configs():
        if config["source"] == source:
            return config["name"]
    raise AssertionError(f"No approved config found for source {source}")


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


def test_lists_only_approved_ingestion_configs() -> None:
    configs = list_approved_configs()

    assert configs
    assert all(Path(config["path"]).parent == APPROVED_CONFIG_DIR for config in configs)
    assert {config["source"] for config in configs} >= {"pubmed_abstract", "pdf"}
    assert "admin_ingestion_defaults.toml" not in {config["name"] for config in configs}


def test_loads_committed_ingestion_defaults() -> None:
    defaults = load_ingestion_defaults()

    assert defaults["config_name"] == config_name_for_source("pubmed_abstract")
    assert defaults["mode"] == "full"
    assert defaults["cache_path"] == "data/corpora/rlalab-pubmed-v1/cumulative"
    assert defaults["write_acquisition_queue"] is False


@pytest.mark.asyncio
async def test_admin_stats_endpoint_returns_operational_summary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_get_admin_stats(_db):
        return {
            "overview": {
                "document_count": 17,
                "chunk_count": 71,
                "indexed_token_count": 12345,
                "user_count": 4,
                "active_user_count": 3,
                "inactive_user_count": 1,
                "session_count": 8,
                "question_count": 21,
                "assistant_message_count": 20,
                "prompt_token_count": 900,
                "completion_token_count": 300,
                "total_chat_token_count": 1200,
                "avg_latency_ms": 512.5,
                "upload_batch_count": 2,
                "uploaded_pdf_file_count": 9,
                "uploaded_pdf_bytes": 2048,
                "last_ingestion_at": datetime(2026, 6, 1, 10, 0, tzinfo=timezone.utc),
                "last_corpus_name": "rlalab-pubmed-v1",
                "year_min": 2000,
                "year_max": 2026,
            },
            "content": {
                "abstract_only_documents": 10,
                "full_text_documents": 3,
                "pdf_documents": 4,
                "electronic_lab_notebook_documents": 0,
                "other_documents": 0,
            },
            "sources": [
                {
                    "source": "pubmed",
                    "document_count": 10,
                    "chunk_count": 30,
                    "indexed_token_count": 6000,
                }
            ],
            "job_statuses": [{"status": "succeeded", "count": 2}],
            "recent_jobs": [
                {
                    "id": uuid.uuid4(),
                    "status": "succeeded",
                    "source": "pubmed_abstract",
                    "mode": "incremental",
                    "document_count": 17,
                    "chunk_count": 71,
                    "created_at": datetime(2026, 6, 1, 9, 0, tzinfo=timezone.utc),
                    "started_at": datetime(2026, 6, 1, 9, 1, tzinfo=timezone.utc),
                    "finished_at": datetime(2026, 6, 1, 9, 5, tzinfo=timezone.utc),
                    "progress_message": "Succeeded",
                    "error": None,
                }
            ],
        }

    monkeypatch.setattr("app.db.crud.get_admin_stats", fake_get_admin_stats)

    async with make_client(make_admin()) as client:
        response = await client.get("/api/v1/admin/stats")

    assert response.status_code == 200
    body = response.json()
    assert body["overview"]["document_count"] == 17
    assert body["overview"]["total_chat_token_count"] == 1200
    assert body["content"]["pdf_documents"] == 4
    assert body["sources"][0]["source"] == "pubmed"
    assert body["recent_jobs"][0]["mode"] == "incremental"


@pytest.mark.asyncio
async def test_admin_stats_document_errors_endpoint_reads_cache_errors(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    cache_root = tmp_path / "data" / "corpora" / "rlalab-pubmed-v1" / "run-1"
    error_file = cache_root / "normalized" / "documents.errors.jsonl"
    error_file.parent.mkdir(parents=True)
    error_file.write_text(
        '{"document_id":"pdf:empty","source":"pdf","error":"No text extracted"}\n',
        encoding="utf-8",
    )

    async def fake_list_ingestion_cache_paths(_db):
        return [str(cache_root)]

    monkeypatch.setattr("app.ingestion.admin_service.ALLOWED_CACHE_ROOT", tmp_path / "data" / "corpora")
    monkeypatch.setattr("app.db.crud.list_ingestion_cache_paths", fake_list_ingestion_cache_paths)

    async with make_client(make_admin()) as client:
        response = await client.get("/api/v1/admin/stats/ingestion-document-errors")

    assert response.status_code == 200
    body = response.json()
    assert body[0]["cache_path"] == "data/corpora/rlalab-pubmed-v1/run-1"
    assert body[0]["error_file_path"] == str(error_file)
    assert body[0]["exists"] is True
    assert body[0]["record_count"] == 1
    assert body[0]["records"][0]["error"] == "No text extracted"


@pytest.mark.asyncio
async def test_admin_ingestion_acquisition_queue_endpoint_reads_cache_queue(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    cache_root = tmp_path / "data" / "corpora" / "rlalab-pubmed-v1" / "run-1"
    queue_file = cache_root / "reports" / "acquisition_queue.jsonl"
    queue_file.parent.mkdir(parents=True)
    queue_file.write_text(
        '{"document_id":"pmid:123","doi":"10.1000/example","candidate_url":"https://example.org/article","candidate_pdf_url":"https://example.org/article.pdf"}\n',
        encoding="utf-8",
    )

    async def fake_list_ingestion_cache_paths(_db):
        return [str(cache_root)]

    monkeypatch.setattr("app.ingestion.admin_service.ALLOWED_CACHE_ROOT", tmp_path / "data" / "corpora")
    monkeypatch.setattr("app.db.crud.list_ingestion_cache_paths", fake_list_ingestion_cache_paths)

    async with make_client(make_admin()) as client:
        response = await client.get("/api/v1/admin/ingestion/acquisition-queue")

    assert response.status_code == 200
    body = response.json()
    assert body[0]["cache_path"] == "data/corpora/rlalab-pubmed-v1/run-1"
    assert body[0]["queue_file_path"] == str(queue_file)
    assert body[0]["exists"] is True
    assert body[0]["record_count"] == 1
    assert body[0]["records"][0]["candidate_url"] == "https://example.org/article"


@pytest.mark.asyncio
async def test_admin_ingestion_acquisition_queue_review_csv_downloads_generated_csv(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    cache_root = tmp_path / "data" / "corpora" / "rlalab-pubmed-v1" / "run-1"
    CorpusCache.create_at_root(
        root=cache_root,
        manifest=CorpusManifest(
            schema_version="1.0",
            corpus_name="rlalab-pubmed-v1",
            run_id="run-1",
            created_at="2026-06-05T00:00:00Z",
            source="pubmed_abstract",
        ),
    )
    queue_file = cache_root / "reports" / "acquisition_queue.jsonl"
    queue_file.write_text(
        '{"document_id":"pmid:123","pmid":"123","pmc_id":"PMC123","doi":"10.1000/example","route":"doi","candidate_url":"https://example.org/article","candidate_pdf_url":"https://example.org/article.pdf","priority":"high"}\n',
        encoding="utf-8",
    )

    monkeypatch.setattr("app.ingestion.admin_service.ALLOWED_CACHE_ROOT", tmp_path / "data" / "corpora")

    async with make_client(make_admin()) as client:
        response = await client.get(
            "/api/v1/admin/ingestion/acquisition-queue/review-csv",
            params={"cache_path": str(cache_root)},
        )

    assert response.status_code == 200
    assert response.headers["content-disposition"] == 'attachment; filename="review_queue.csv"'
    assert response.headers["x-record-count"] == "1"
    assert "candidate_url" in response.text
    assert "https://example.org/article.pdf" in response.text


def test_worker_status_reports_missing_heartbeat(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    heartbeat_path = tmp_path / "worker_heartbeat.json"
    monkeypatch.setattr("app.ingestion.admin_service.WORKER_HEARTBEAT_PATH", heartbeat_path)

    status = get_worker_status()

    assert status["active"] is False
    assert status["state"] == "not_seen"


def test_worker_status_reports_current_heartbeat(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    heartbeat_path = tmp_path / "worker_heartbeat.json"
    monkeypatch.setattr("app.ingestion.admin_service.WORKER_HEARTBEAT_PATH", heartbeat_path)

    write_worker_heartbeat(state="polling")
    status = get_worker_status()

    assert status["active"] is True
    assert status["state"] == "polling"


def test_rejects_unapproved_ingestion_config_path() -> None:
    with pytest.raises(HTTPException):
        get_approved_config("../secrets.toml")


def test_restricts_cache_paths_to_corpus_data() -> None:
    resolved = resolve_cache_path("data/corpora/rlalab-pubmed-v1/cumulative")

    assert resolved is not None
    assert str(resolved).endswith("data/corpora/rlalab-pubmed-v1/cumulative")
    assert resolved.is_absolute()

    with pytest.raises(HTTPException):
        resolve_cache_path("/tmp/not-an-approved-cache")


def test_accepts_a_cache_path_recorded_by_another_topology() -> None:
    """The split-brain case: a containerised worker records `/app/data/corpora/...`
    and a host backend, whose repo root is the checkout, must still read it."""
    resolved = resolve_cache_path("/app/data/corpora/rlalab-pubmed-v1/cumulative")

    assert resolved == ALLOWED_CACHE_ROOT.resolve() / "rlalab-pubmed-v1" / "cumulative"


@pytest.mark.parametrize(
    "value",
    [
        "data/corpora/rlalab-pubmed-v1/cumulative",
        "/app/data/corpora/rlalab-pubmed-v1/cumulative",
        str(ALLOWED_CACHE_ROOT / "rlalab-pubmed-v1" / "cumulative"),
    ],
)
def test_stored_cache_paths_are_repo_relative_whatever_the_input(value: str) -> None:
    """One canonical string per cache, so two processes cannot disagree."""
    assert store_cache_path(value) == "data/corpora/rlalab-pubmed-v1/cumulative"


def test_stores_the_cache_root_itself_without_a_trailing_segment() -> None:
    assert store_cache_path("/app/data/corpora") == "data/corpora"


def test_a_traversal_tail_is_rejected_rather_than_re_rooted() -> None:
    """Re-rooting must not become a way out of the cache root."""
    with pytest.raises(HTTPException):
        resolve_cache_path("data/corpora/../../etc/passwd")

    with pytest.raises(HTTPException):
        resolve_cache_path("/app/data/corpora/../../../etc/passwd")


def test_empty_cache_paths_stay_empty() -> None:
    assert resolve_cache_path(None) is None
    assert resolve_cache_path("") is None
    assert store_cache_path(None) is None


def test_dump_toml_sections_preserves_known_config_shape() -> None:
    text = dump_toml_sections(
        {
            "corpus": {"name": "rlalab-pubmed-v1", "source": "pdf"},
            "pdf": {"dir": "./data/pdfs"},
            "indexing": {"embedding_batch_size": 1},
        }
    )

    assert '[corpus]\nname = "rlalab-pubmed-v1"\nsource = "pdf"' in text
    assert '[pdf]\ndir = "./data/pdfs"' in text
    assert "[indexing]\nembedding_batch_size = 1" in text


def test_worker_toml_value_formatter_handles_config_primitives() -> None:
    assert format_toml_value("Yarrowia") == '"Yarrowia"'
    assert format_toml_value(True) == "true"
    assert format_toml_value(["PMC1", "PMC2"]) == '["PMC1", "PMC2"]'


def test_worker_log_tail_trims_old_content() -> None:
    existing = "x" * 20
    value = append_log(existing, "new event", limit=12)

    assert value.endswith("new event")
    assert len(value) == 12


@pytest.mark.asyncio
async def test_worker_maintains_heartbeat_during_long_running_job(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    job_id = uuid.uuid4()
    heartbeats: list[tuple[str, uuid.UUID | None]] = []

    def fake_write_worker_heartbeat(*, state: str, job_id: uuid.UUID | None = None) -> None:
        heartbeats.append((state, job_id))

    monkeypatch.setattr("app.ingestion.worker.write_worker_heartbeat", fake_write_worker_heartbeat)

    task = asyncio.create_task(maintain_running_heartbeat(job_id, interval_s=0.01))
    await asyncio.sleep(0.035)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert len(heartbeats) >= 3
    assert all(state == "running" for state, _ in heartbeats)
    assert all(seen_job_id == job_id for _, seen_job_id in heartbeats)


@pytest.mark.asyncio
async def test_worker_run_job_marks_success(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    job_id = uuid.uuid4()
    manifest_id = uuid.uuid4()
    job = SimpleNamespace(
        id=job_id,
        config_snapshot={"corpus": {"name": "test", "source": "pdf"}, "pdf": {"dir": "./data/pdfs"}},
        mode="full",
        from_date=None,
        year=None,
        options={},
        cache_path=None,
        status="running",
        progress_message="Worker started",
        log_tail=None,
        manifest_id=None,
        document_count=None,
        chunk_count=None,
        finished_at=None,
    )

    async def fake_build_index(config_path, **kwargs):
        assert Path(config_path).exists()
        await kwargs["progress_callback"](
            "Processed 100 documents",
            {"document_count": 100, "chunk_count": 150},
        )
        return {
            "manifest_id": str(manifest_id),
            "document_count": 100,
            "chunk_count": 150,
            "cache_path": "/app/data/corpora/test/run",
        }

    monkeypatch.setattr("app.ingestion.worker.JOB_WORK_ROOT", tmp_path)
    monkeypatch.setattr("app.ingestion.worker.AsyncSessionLocal", fake_worker_session_factory(job))
    monkeypatch.setattr("app.ingestion.worker.build_index", fake_build_index)

    await run_job(job_id)

    assert job.status == "succeeded"
    assert job.manifest_id == manifest_id
    assert job.document_count == 100
    assert job.chunk_count == 150
    assert job.cache_path == "data/corpora/test/run"
    assert job.finished_at is not None


@pytest.mark.asyncio
async def test_worker_run_job_marks_failure(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    job_id = uuid.uuid4()
    job = SimpleNamespace(
        id=job_id,
        config_snapshot={"corpus": {"name": "test", "source": "pdf"}, "pdf": {"dir": "./data/pdfs"}},
        mode="full",
        from_date=None,
        year=None,
        options={},
        cache_path=None,
        status="running",
        progress_message="Worker started",
        log_tail=None,
        error=None,
        finished_at=None,
    )

    async def fake_build_index(*_args, **_kwargs):
        raise RuntimeError("embedding model unavailable")

    monkeypatch.setattr("app.ingestion.worker.JOB_WORK_ROOT", tmp_path)
    monkeypatch.setattr("app.ingestion.worker.AsyncSessionLocal", fake_worker_session_factory(job))
    monkeypatch.setattr("app.ingestion.worker.build_index", fake_build_index)

    await run_job(job_id)

    assert job.status == "failed"
    assert job.error == "embedding model unavailable"
    assert job.progress_message == "Failed"
    assert job.finished_at is not None


@pytest.mark.asyncio
async def test_ingestion_configs_endpoint_requires_admin() -> None:
    async with make_client(make_admin(role="researcher")) as client:
        response = await client.get("/api/v1/admin/ingestion/configs")

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_ingestion_configs_endpoint_returns_approved_configs() -> None:
    async with make_client(make_admin()) as client:
        response = await client.get("/api/v1/admin/ingestion/configs")

    assert response.status_code == 200
    body = response.json()
    assert {item["source"] for item in body} >= {"pubmed_abstract", "pdf"}
    assert "admin_ingestion_defaults.toml" not in {item["name"] for item in body}
    assert all(item["path"].endswith(f"pipelines/configs/{item['name']}") for item in body)


@pytest.mark.asyncio
async def test_ingestion_defaults_endpoint_returns_prefill_values() -> None:
    async with make_client(make_admin()) as client:
        response = await client.get("/api/v1/admin/ingestion/defaults")

    assert response.status_code == 200
    body = response.json()
    assert body == {
        "config_name": config_name_for_source("pubmed_abstract"),
        "mode": "full",
        "cache_path": "data/corpora/rlalab-pubmed-v1/cumulative",
        "write_acquisition_queue": False,
        "include_cached_fulltext": False,
    }


@pytest.mark.asyncio
async def test_ingestion_config_editor_endpoints_create_read_and_update(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr("app.ingestion.admin_service.APPROVED_CONFIG_DIR", tmp_path)
    monkeypatch.setattr(
        "app.ingestion.admin_service.INGESTION_DEFAULTS_PATH",
        tmp_path / "admin_ingestion_defaults.toml",
    )

    content = {
        "corpus": {
            "name": "rlalab-test",
            "source": "pubmed_abstract",
            "embedding_model": "pubmedbert",
        },
        "pubmed": {
            "query": '"Yarrowia lipolytica"[Title/Abstract] AND english[lang]',
            "year_from": 2024,
            "year_to": 2025,
            "batch_size": 20,
            "sleep_between_batches_s": 0.15,
        },
        "chunking": {"chunk_size": 512, "chunk_overlap": 64},
    }

    async with make_client(make_admin()) as client:
        created = await client.post(
            "/api/v1/admin/ingestion/configs",
            json={"name": "test.pubmed.toml", "content": content},
        )
        loaded = await client.get("/api/v1/admin/ingestion/configs/test.pubmed.toml")
        updated_content = {
            **content,
            "pubmed": {**content["pubmed"], "year_to": 2026},
        }
        updated = await client.put(
            "/api/v1/admin/ingestion/configs/test.pubmed.toml",
            json={"content": updated_content},
        )
        duplicate = await client.post(
            "/api/v1/admin/ingestion/configs",
            json={"name": "test.pubmed.toml", "content": content},
        )

    assert created.status_code == 201
    assert created.json()["name"] == "test.pubmed.toml"
    assert loaded.status_code == 200
    assert loaded.json()["content"]["pubmed"]["year_from"] == 2024
    assert updated.status_code == 200
    assert updated.json()["content"]["pubmed"]["year_to"] == 2026
    assert duplicate.status_code == 409
    assert (tmp_path / "test.pubmed.toml").read_text().startswith("# RLALab corpus configuration")


@pytest.mark.asyncio
async def test_ingestion_worker_endpoint_returns_status(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "app.api.routes.admin.get_worker_status",
        lambda: {
            "active": False,
            "state": "not_seen",
            "job_id": None,
            "updated_at": None,
            "seconds_since_heartbeat": None,
            "message": "No ingestion worker heartbeat has been seen.",
        },
    )

    async with make_client(make_admin()) as client:
        response = await client.get("/api/v1/admin/ingestion/worker")

    assert response.status_code == 200
    assert response.json()["active"] is False


@pytest.mark.asyncio
async def test_create_ingestion_job_rejects_unapproved_config() -> None:
    async with make_client(make_admin()) as client:
        response = await client.post(
            "/api/v1/admin/ingestion/jobs",
            json={"config_name": "../secret.toml", "mode": "full"},
        )

    assert response.status_code == 400
    assert response.json()["detail"] == "Unknown ingestion config"


@pytest.mark.asyncio
async def test_create_ingestion_job_validates_mode_specific_fields() -> None:
    pubmed_config = config_name_for_source("pubmed_abstract")
    async with make_client(make_admin()) as client:
        incremental = await client.post(
            "/api/v1/admin/ingestion/jobs",
            json={"config_name": pubmed_config, "mode": "incremental"},
        )
        local_only = await client.post(
            "/api/v1/admin/ingestion/jobs",
            json={"config_name": pubmed_config, "mode": "local_only"},
        )

    assert incremental.status_code == 400
    assert incremental.json()["detail"] == "from_date is required"
    assert local_only.status_code == 400
    assert "cache_path is required" in local_only.json()["detail"]


@pytest.mark.asyncio
async def test_create_ingestion_job_persists_valid_request(monkeypatch: pytest.MonkeyPatch) -> None:
    admin = make_admin()
    pubmed_config = config_name_for_source("pubmed_abstract")
    created_jobs: list[dict] = []

    async def fake_create_ingestion_job(_db, **kwargs):
        created_jobs.append(kwargs)
        return SimpleNamespace(
            id=uuid.uuid4(),
            requested_by_user_id=kwargs["requested_by_user_id"],
            status="queued",
            config_name=kwargs["config_name"],
            config_path=kwargs["config_path"],
            source=kwargs["source"],
            mode=kwargs["mode"],
            from_date=kwargs["from_date"],
            year=kwargs["year"],
            cache_path=kwargs["cache_path"],
            pdf_upload_batch_id=kwargs["pdf_upload_batch_id"],
            options=kwargs["options"],
            manifest_id=None,
            document_count=None,
            chunk_count=None,
            progress_message="Queued",
            log_tail=None,
            error=None,
            created_at=datetime(2026, 5, 31, tzinfo=timezone.utc),
            started_at=None,
            finished_at=None,
            updated_at=datetime(2026, 5, 31, tzinfo=timezone.utc),
        )

    monkeypatch.setattr("app.db.crud.create_ingestion_job", fake_create_ingestion_job)

    async with make_client(admin) as client:
        response = await client.post(
            "/api/v1/admin/ingestion/jobs",
            json={
                "config_name": pubmed_config,
                "mode": "incremental",
                "from_date": "2026-05-01",
                "write_acquisition_queue": True,
            },
        )

    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "queued"
    assert body["mode"] == "incremental"
    assert created_jobs[0]["requested_by_user_id"] == admin.id
    assert created_jobs[0]["from_date"] == date(2026, 5, 1)
    assert created_jobs[0]["options"]["write_acquisition_queue"] is True


@pytest.mark.asyncio
async def test_pdf_upload_endpoint_stages_batch(monkeypatch: pytest.MonkeyPatch) -> None:
    admin = make_admin()

    async def fake_save_pdf_upload_folder(files, *, batch_id):
        assert batch_id
        assert len(files) == 2
        return Path("/tmp/uploaded-pdfs"), 2, 1234

    async def fake_create_ingestion_upload_batch(_db, **kwargs):
        return SimpleNamespace(
            id=kwargs["upload_batch_id"],
            name=kwargs["name"],
            directory_path=kwargs["directory_path"],
            file_count=kwargs["file_count"],
            total_bytes=kwargs["total_bytes"],
            created_at=datetime(2026, 5, 31, tzinfo=timezone.utc),
        )

    monkeypatch.setattr("app.api.routes.admin.save_pdf_upload_folder", fake_save_pdf_upload_folder)
    monkeypatch.setattr(
        "app.db.crud.create_ingestion_upload_batch",
        fake_create_ingestion_upload_batch,
    )

    files = [
        ("files", ("folder/one.pdf", b"%PDF-1.4 one", "application/pdf")),
        ("files", ("folder/two.pdf", b"%PDF-1.4 two", "application/pdf")),
    ]
    async with make_client(admin) as client:
        response = await client.post(
            "/api/v1/admin/ingestion/pdf-upload-folders",
            data={"name": "Manual batch"},
            files=files,
        )

    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "Manual batch"
    assert body["file_count"] == 2
    assert body["total_bytes"] == 1234


@pytest.mark.asyncio
async def test_cancel_ingestion_job_updates_queued_job(monkeypatch: pytest.MonkeyPatch) -> None:
    job_id = uuid.uuid4()
    job = SimpleNamespace(
        id=job_id,
        requested_by_user_id=uuid.uuid4(),
        status="queued",
        config_name="pubmed_abstract.rlalab.toml",
        config_path="/app/pipelines/configs/pubmed_abstract.rlalab.toml",
        source="pubmed_abstract",
        mode="full",
        from_date=None,
        year=None,
        cache_path=None,
        pdf_upload_batch_id=None,
        options={},
        manifest_id=None,
        document_count=None,
        chunk_count=None,
        progress_message="Queued",
        log_tail=None,
        error=None,
        created_at=datetime(2026, 5, 31, tzinfo=timezone.utc),
        started_at=None,
        finished_at=None,
        updated_at=datetime(2026, 5, 31, tzinfo=timezone.utc),
    )

    async def fake_get_ingestion_job(_db, requested_job_id):
        assert requested_job_id == job_id
        return job

    async def fake_cancel(_db, target_job, now):
        target_job.status = "cancelled"
        target_job.finished_at = now
        target_job.progress_message = "Cancelled before worker picked it up"
        return target_job

    monkeypatch.setattr("app.db.crud.get_ingestion_job", fake_get_ingestion_job)
    monkeypatch.setattr("app.db.crud.request_ingestion_job_cancel", fake_cancel)

    async with make_client(make_admin()) as client:
        response = await client.post(f"/api/v1/admin/ingestion/jobs/{job_id}/cancel")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "cancelled"
    assert "Cancelled" in body["progress_message"]
