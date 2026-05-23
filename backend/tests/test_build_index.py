from pipelines.corpus_cache import CorpusCache, CorpusManifest
from pipelines.indexing.build_index import (
    documents_from_cached_pdf_text,
    load_pmc_ids,
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
