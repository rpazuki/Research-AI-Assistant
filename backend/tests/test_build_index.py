import json

from pipelines.corpus_cache import CorpusCache, CorpusManifest
from pipelines.indexing.build_index import (
    batched,
    chunk_mode_for_source,
    chunks_for_document,
    documents_from_cached_datasheet_fulltext,
    documents_from_cached_datasheet_rows,
    documents_from_cached_discovery,
    documents_from_cached_lab_text,
    documents_from_cached_pdf_text,
    embedding_batch_size_for_source,
    load_pmc_ids,
    open_or_create_cache_from_path,
    validate_index_embedding,
)
from pipelines.processing.chunker import Chunker
from pipelines.processing.normalizer import NormalizedDocument


class DummyEmbedder:
    def __init__(self, model_name: str, dimensions: int) -> None:
        self.model_name = model_name
        self.dimensions = dimensions


def test_validate_index_embedding_accepts_pubmedbert_dimensions() -> None:
    validate_index_embedding(DummyEmbedder("pubmedbert", 768))


def test_validate_index_embedding_rejects_non_matching_dimensions() -> None:
    try:
        validate_index_embedding(DummyEmbedder("minilm", 384))
    except ValueError as exc:
        assert "768-dimensional" in str(exc)
        assert "minilm" in str(exc)
    else:
        raise AssertionError("Expected validate_index_embedding to reject non-768 dimensions")


def test_batched_splits_items_into_fixed_size_batches() -> None:
    assert list(batched([1, 2, 3, 4, 5], 2)) == [[1, 2], [3, 4], [5]]


def test_embedding_batch_size_uses_source_override_then_default() -> None:
    cfg = {
        "indexing": {
            "embedding_batch_size": 3,
            "embedding_batch_size_by_source": {"pubmed_abstract": 11},
        }
    }

    assert embedding_batch_size_for_source(cfg, "pubmed_abstract") == 11
    assert embedding_batch_size_for_source(cfg, "pmc_fulltext") == 3


def test_open_or_create_cache_from_path_initializes_ui_default_cache(tmp_path) -> None:
    config_path = tmp_path / "corpus.toml"
    config_path.write_text(
        """
[corpus]
name = "rlalab-pubmed-v1"
source = "pubmed_abstract"
embedding_model = "pubmedbert"

[pubmed]
query = "synthetic biology"
year_from = 2000
year_to = 2026

[chunking]
chunk_size = 512
chunk_overlap = 64
""".strip()
    )
    cache_path = tmp_path / "data" / "corpora" / "rlalab-pubmed-v1" / "cumulative"

    cache = open_or_create_cache_from_path(config_path, cache_path)

    assert cache.root == cache_path
    assert cache.manifest is not None
    assert cache.manifest.corpus_name == "rlalab-pubmed-v1"
    assert cache.manifest.run_id == "cumulative"
    assert (cache_path / "manifest.json").exists()
    assert (cache_path / "config" / "corpus.toml").exists()


def make_cache(tmp_path, source: str = "pdf") -> CorpusCache:
    manifest = CorpusManifest(
        schema_version="1.0",
        corpus_name="test-corpus",
        run_id="2026-05-23T120000Z",
        created_at="2026-05-23T12:00:00Z",
        source=source,
    )
    return CorpusCache.create(base_dir=tmp_path, manifest=manifest)


def test_documents_from_cached_pdf_text_reads_extracted_text(tmp_path) -> None:
    cache = make_cache(tmp_path)
    text_path = cache.write_bytes("raw/pdf/extracted/abc123.txt", b"cached full text")

    docs = list(documents_from_cached_pdf_text(cache))

    assert text_path.exists()
    assert docs[0].document_id == "pdf:abc123"
    assert docs[0].full_text == "cached full text"
    assert docs[0].metadata["text_extraction_status"] == "cached"


def test_load_pmc_ids_can_use_cached_pubmed_documents(tmp_path) -> None:
    cache = make_cache(tmp_path, source="pubmed_abstract")
    cache.write_document(
        NormalizedDocument(document_id="pmid:123", source="pubmed", pmid="123", pmc_id="PMC123"),
        access_status="metadata-only",
        parser_version="pubmed-v1",
    )

    ids = load_pmc_ids({"pmc": {"from_cached_pubmed_documents": True}}, cache=cache)

    assert ids == ["PMC123"]


def test_load_pmc_ids_preserves_pubmed_ids_and_dois() -> None:
    ids = load_pmc_ids({"pmc": {"ids": ["41812577", "PMC1234567", "10.1000/example", "pmc7654321"]}})

    assert ids == ["41812577", "PMC1234567", "10.1000/example", "PMC7654321"]


def test_documents_from_cached_lab_text_reads_extracted_exports(tmp_path) -> None:
    cache = make_cache(tmp_path, source="lab_protocols")
    cache.write_bytes("raw/lab/extracted/protocol123.txt", b"protocol content")

    docs = list(documents_from_cached_lab_text(cache, "lab_protocols"))

    assert docs[0].document_id == "lab_protocols:protocol123"
    assert docs[0].full_text == "protocol content"
    assert docs[0].metadata["access_method"] == "local-export"


# ── Chunk mode ────────────────────────────────────────────────────────────────


def test_chunk_mode_is_stated_per_source_not_sniffed_from_the_name() -> None:
    """The old rule was `"abstract" in source`, which filed discovery_search and
    every datasheet_* key under fulltext by accident."""
    assert chunk_mode_for_source("pubmed_abstract") == "abstract"
    assert chunk_mode_for_source("discovery_search") == "abstract"
    assert chunk_mode_for_source("datasheet_manifest") == "abstract"
    assert chunk_mode_for_source("pmc_fulltext") == "fulltext"
    assert chunk_mode_for_source("datasheet_fulltext") == "fulltext"
    assert chunk_mode_for_source("lab_protocols") == "fulltext"
    assert chunk_mode_for_source("something_new") == "fulltext"


def test_documents_with_sections_are_chunked_section_by_section() -> None:
    doc = NormalizedDocument(
        document_id="pmid:1",
        source="pmc",
        title="A title",
        full_text="ignored when sections are present",
        sections=[
            {"label": "methods", "text": "Strains were grown."},
            {"label": "results", "text": "Titre reached 50 g/L."},
        ],
    )

    chunks = chunks_for_document(Chunker(chunk_size=1000, mode="fulltext"), doc)

    assert [chunk.section_label for chunk in chunks] == ["title", "methods", "results"]


def test_documents_without_sections_fall_back_to_whole_document_chunking() -> None:
    doc = NormalizedDocument(document_id="pmid:1", source="pubmed", abstract="One sentence.")

    chunks = chunks_for_document(Chunker(mode="abstract"), doc)

    assert len(chunks) == 1
    assert chunks[0].section_label is None


def test_row_scoped_sources_are_not_deduplicated_by_pmid_or_title() -> None:
    """Found by a real indexing run: two datasheet rows about one paper share its
    PMID and title, so the default deduplicator kept the first and dropped the
    second — silently discarding exactly the data the source exists to expose.
    Their identity is the row hash in document_id, which still catches a re-read.
    """
    from types import SimpleNamespace

    from pipelines.indexing.build_index import ROW_SCOPED_SOURCES
    from pipelines.processing.deduplicator import Deduplicator

    assert "datasheet_rows" in ROW_SCOPED_SOURCES

    dedup = Deduplicator(match_on_pmid=False, match_on_title=False)
    first = SimpleNamespace(
        document_id="datasheet_row:aaa", pmid="31234567", title="Datasheet row: A paper"
    )
    second = SimpleNamespace(
        document_id="datasheet_row:bbb", pmid="31234567", title="Datasheet row: A paper"
    )

    assert dedup.is_duplicate(first) is False
    dedup.register(first)
    assert dedup.is_duplicate(second) is False
    dedup.register(second)
    # The same row read twice is still a duplicate.
    assert dedup.is_duplicate(first) is True


def test_paper_scoped_sources_keep_pmid_deduplication() -> None:
    from types import SimpleNamespace

    from pipelines.processing.deduplicator import Deduplicator

    dedup = Deduplicator()
    dedup.register(SimpleNamespace(document_id="pmid:1", pmid="31234567", title="A paper"))

    assert dedup.is_duplicate(
        SimpleNamespace(document_id="doi:10.1/a", pmid="31234567", title="A paper")
    ) is True


# ── Cache replay for the new sources ──────────────────────────────────────────


def test_documents_from_cached_discovery_replays_only_what_the_run_included(tmp_path) -> None:
    cache = make_cache(tmp_path, source="discovery_search")
    cache.append_jsonl(
        "raw/discovery/candidates.jsonl",
        [
            {
                "doi": "10.1/kept",
                "pmid": "111",
                "title": "Kept",
                "relevance": "studies",
                "doc_type": "primary",
                "is_review": False,
                "is_retracted": False,
                "found_in": ["pubmed"],
            },
            {
                "doi": "10.1/dropped",
                "pmid": "222",
                "title": "Off topic",
                "relevance": "off_topic",
                "doc_type": "primary",
                "is_review": False,
                "is_retracted": False,
                "found_in": ["crossref"],
            },
            {
                "doi": "10.1/retracted",
                "pmid": "333",
                "title": "Retracted",
                "relevance": "studies",
                "doc_type": "primary",
                "is_review": False,
                "is_retracted": True,
                "found_in": ["pubmed"],
            },
        ],
    )

    docs = list(documents_from_cached_discovery(cache))

    assert [doc.document_id for doc in docs] == ["pmid:111"]
    assert docs[0].source == "discovery"


def test_documents_from_cached_datasheet_fulltext_rebuilds_sections(tmp_path) -> None:
    from pipelines.acquisition.cache_layout import safe_stem
    from pipelines.discovery.canonicalize import Candidate
    from pipelines.discovery.manifest_csv import write_manifest_csv

    cache = make_cache(tmp_path, source="datasheet_fulltext")
    candidate = Candidate(
        doi="10.1/a", pmid="111", title="A paper", relevance="studies", doc_type="primary"
    )
    cache.write_bytes(
        "raw/datasheet/manifest.csv",
        write_manifest_csv([candidate], included_dois={"10.1/a"}).encode("utf-8"),
    )
    cache.write_bytes(
        f"raw/datasheet/fulltext/{safe_stem('10.1/a')}.json",
        json.dumps(
            {
                "source_format": "xml",
                "title": "A paper",
                "abstract": "Abstract text.",
                "warnings": [],
                "sections": [{"label": "methods", "heading": "Methods", "text": "Grown in YPD."}],
            }
        ).encode("utf-8"),
    )

    docs = list(documents_from_cached_datasheet_fulltext(cache))

    assert [doc.document_id for doc in docs] == ["pmid:111"]
    assert [section["label"] for section in docs[0].sections] == ["methods"]


def test_cached_full_text_without_a_manifest_row_is_skipped(tmp_path) -> None:
    """The stem is a one-way hash: a payload with no row cannot be attributed to
    a paper, and an uncitable document is worse than a missing one."""
    from pipelines.discovery.manifest_csv import write_manifest_csv

    cache = make_cache(tmp_path, source="datasheet_fulltext")
    cache.write_bytes("raw/datasheet/manifest.csv", write_manifest_csv([]).encode("utf-8"))
    cache.write_bytes(
        "raw/datasheet/fulltext/orphan-0123456789.json",
        json.dumps({"source_format": "xml", "sections": [], "warnings": []}).encode("utf-8"),
    )

    assert list(documents_from_cached_datasheet_fulltext(cache)) == []


def test_documents_from_cached_datasheet_rows_reproduces_the_live_ids(tmp_path) -> None:
    from pathlib import Path

    from pipelines.ingestion.datasheet_rows import row_to_document

    cache = make_cache(tmp_path, source="datasheet_rows")
    row = {"Article": "A paper", "Compounds": "citric acid", "doi": "10.1/a", "year": "2020"}
    cache.append_jsonl(
        "raw/datasheet/rows/rows.jsonl",
        [{"row_index": 0, "template": "default", "source_file": "rows.csv", "row": row}],
    )

    docs = list(documents_from_cached_datasheet_rows(cache))
    live = row_to_document(row, row_index=0, template_name="default", source_path=Path("rows.csv"))

    assert len(docs) == 1
    # A replay that minted new ids would double every row in the corpus.
    assert docs[0].document_id == live.document_id
    assert "citric acid" in docs[0].full_text
