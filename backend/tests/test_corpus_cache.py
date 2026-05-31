from datetime import datetime

from pipelines.corpus_cache import (
    CorpusCache,
    CorpusManifest,
    cached_pmc_xml_exists,
    chunk_from_cache_record,
    chunk_to_cache_record,
    document_from_cache_record,
    document_to_cache_record,
    full_text_candidates,
    write_acquisition_queue,
)
from pipelines.processing.chunker import Chunk
from pipelines.processing.normalizer import AuthorRecord, NormalizedDocument


def make_manifest() -> CorpusManifest:
    return CorpusManifest(
        schema_version="1.0",
        corpus_name="test-corpus",
        run_id="2026-05-23T120000Z",
        created_at="2026-05-23T12:00:00Z",
        source="pubmed_abstract",
        embedding_model="pubmedbert",
        chunk_size=512,
        chunk_overlap=64,
    )


def test_cache_layout_and_manifest_round_trip(tmp_path) -> None:
    cache = CorpusCache.create(base_dir=tmp_path, manifest=make_manifest())

    assert (cache.root / "manifest.json").exists()
    assert (cache.root / "raw/pubmed/efetch").is_dir()
    assert (cache.root / "normalized").is_dir()
    assert CorpusCache.open(cache.root).manifest.corpus_name == "test-corpus"


def test_document_cache_record_round_trip() -> None:
    doc = NormalizedDocument(
        document_id="pmid:123",
        source="pubmed",
        title="A title",
        abstract="An abstract",
        authors=[AuthorRecord(last_name="Smith", fore_name="Jane", initials="J")],
        journal="Journal",
        year=2026,
        doi="10.1000/example",
        pmid="123",
        pmc_id="PMC123",
        ingested_at=datetime(2026, 5, 23, 12, 0, 0),
    )

    record = document_to_cache_record(
        doc,
        source_run_id="run",
        raw_asset_path="raw/pubmed/efetch/batch_000001.xml",
        access_status="metadata-only",
        parser_version="pubmed-v1",
    )
    restored = document_from_cache_record(record)

    assert record["cache_id"].startswith("sha256:")
    assert restored.document_id == doc.document_id
    assert restored.authors[0].display_name() == "Smith, Jane"
    assert restored.metadata["raw_asset_path"] == "raw/pubmed/efetch/batch_000001.xml"


def test_chunk_cache_record_round_trip() -> None:
    chunk = Chunk(document_id="pmid:123", chunk_index=0, chunk_type="abstract", content="text", token_count=2)

    record = chunk_to_cache_record(chunk, embedding_model="pubmedbert", source_run_id="run")
    restored = chunk_from_cache_record(record)

    assert record["embedding_status"] == "pending"
    assert restored == chunk


def test_full_text_candidates_include_pmcid_and_doi_routes() -> None:
    doc = NormalizedDocument(
        document_id="pmid:123",
        source="pubmed",
        pmid="123",
        pmc_id="PMC123",
        doi="10.1000/example",
    )

    candidates = full_text_candidates(doc)

    assert {candidate["route"] for candidate in candidates} == {"pmcid", "doi"}
    assert candidates[0]["access_status"] == "open-access-candidate"


def test_full_text_candidates_skip_document_when_pmc_xml_is_cached(tmp_path) -> None:
    cache = CorpusCache.create(base_dir=tmp_path, manifest=make_manifest())
    cache.write_bytes("raw/pmc/xml/PMC123.xml", b"<article/>")
    doc = NormalizedDocument(
        document_id="pmid:123",
        source="pubmed",
        pmid="123",
        pmc_id="PMC123",
        doi="10.1000/example",
    )

    assert cached_pmc_xml_exists(cache, "PMC123") is True
    assert full_text_candidates(doc, cache=cache) == []

    candidates = full_text_candidates(doc, cache=cache, include_cached_fulltext=True)
    assert {candidate["route"] for candidate in candidates} == {"pmcid", "doi"}


def test_write_acquisition_queue_skips_cached_pmc_xml_unless_included(tmp_path) -> None:
    cache = CorpusCache.create(base_dir=tmp_path, manifest=make_manifest())
    cache.write_bytes("raw/pmc/xml/PMC123.xml", b"<article/>")
    doc = NormalizedDocument(
        document_id="pmid:123",
        source="pubmed",
        pmid="123",
        pmc_id="PMC123",
        doi="10.1000/example",
    )
    queue_path = cache.root / "reports" / "acquisition_queue.jsonl"

    count = write_acquisition_queue([doc], queue_path, cache=cache)
    assert count == 0
    assert queue_path.read_text() == ""

    count = write_acquisition_queue([doc], queue_path, cache=cache, include_cached_fulltext=True)
    assert count == 2
    assert len(cache.read_jsonl("reports/acquisition_queue.jsonl")) == 2


def test_refresh_counts_from_artifacts_counts_accumulated_jsonl(tmp_path) -> None:
    cache = CorpusCache.create(base_dir=tmp_path, manifest=make_manifest())
    cache.write_document(NormalizedDocument(document_id="pmid:1", source="pubmed", pmid="1"))
    cache.write_document(NormalizedDocument(document_id="pmid:2", source="pubmed", pmid="2"))
    cache.write_chunks(
        [
            Chunk(document_id="pmid:1", chunk_index=0, chunk_type="abstract", content="one"),
            Chunk(document_id="pmid:2", chunk_index=0, chunk_type="abstract", content="two"),
        ],
        embedding_model="pubmedbert",
    )
    cache.write_bytes("raw/pubmed/efetch/batch_a.xml", b"<xml/>")

    cache.refresh_counts_from_artifacts()

    assert cache.manifest is not None
    assert cache.manifest.counts["pmids"] == 2
    assert cache.manifest.counts["raw_records"] == 1
    assert cache.manifest.counts["normalized_documents"] == 2
    assert cache.manifest.counts["chunks"] == 2
