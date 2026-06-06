from pipelines.corpus_cache import CorpusCache, CorpusManifest
from pipelines.indexing.build_index import (
    batched,
    documents_from_cached_lab_text,
    documents_from_cached_pdf_text,
    embedding_batch_size_for_source,
    load_pmc_ids,
    open_or_create_cache_from_path,
    validate_index_embedding,
)
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
