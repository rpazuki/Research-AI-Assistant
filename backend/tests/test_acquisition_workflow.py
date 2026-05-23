import shutil

from pipelines.acquisition.fulltext import (
    acquisition_guidance,
    export_review_csv,
    register_manual_asset,
)
from pipelines.corpus_cache import CorpusCache, CorpusManifest
from pipelines.processing.normalizer import NormalizedDocument


def make_cache(tmp_path) -> CorpusCache:
    manifest = CorpusManifest(
        schema_version="1.0",
        corpus_name="test-corpus",
        run_id="2026-05-23T120000Z",
        created_at="2026-05-23T12:00:00Z",
        source="pubmed_abstract",
    )
    return CorpusCache.create(base_dir=tmp_path, manifest=manifest)


def test_export_review_csv_creates_manual_review_file(tmp_path) -> None:
    cache = make_cache(tmp_path)
    cache.write_document(
        NormalizedDocument(
            document_id="pmid:123",
            source="pubmed",
            pmid="123",
            doi="10.1000/example",
            pmc_id="PMC123",
        ),
        access_status="metadata-only",
        parser_version="pubmed-v1",
    )
    output = cache.root / "acquisition" / "review.csv"

    count = export_review_csv(cache, output)

    assert count == 2
    assert output.exists()
    assert "review_decision" in output.read_text()


def test_register_manual_asset_records_licensed_file_without_download(tmp_path) -> None:
    cache = make_cache(tmp_path)
    pdf = tmp_path / "article.pdf"
    pdf.write_bytes(b"%PDF-1.4\nlicensed paper")

    record = register_manual_asset(
        cache,
        file_path=pdf,
        document_id="pmid:123",
        access_status="licensed-access",
        access_method="imperial-library",
        source_url="https://doi.org/10.1000/example",
        license="licensed-access",
        terms_note="Imperial library access",
        acquired_by="authorized-user",
    )

    assert record["asset_type"] == "licensed_pdf"
    assert record["download_performed_by_pipeline"] is False
    assert record["access_method"] == "imperial-library"
    assert (cache.root / record["relative_path"]).exists()
    assert "Do not store Imperial" in acquisition_guidance()


def test_cache_validate_detects_transferable_registered_assets(tmp_path) -> None:
    cache = make_cache(tmp_path)
    text = tmp_path / "paper.txt"
    text.write_text("licensed full text")
    register_manual_asset(
        cache,
        file_path=text,
        document_id="pmid:123",
        access_status="licensed-access",
        access_method="manual-upload",
    )

    copied_root = tmp_path / "copy" / cache.root.name
    shutil.copytree(cache.root, copied_root)
    validation = CorpusCache.open(copied_root).validate()

    assert validation["ok"] is True
    assert validation["counts"]["assets"] == 1
