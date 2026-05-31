import shutil

from pipelines.acquisition.fulltext import (
    acquisition_guidance,
    export_review_csv,
    read_queue,
    register_manual_assets_from_manifest,
    register_manual_asset,
    write_batch_template,
)
from pipelines.corpus_cache import CorpusCache, CorpusManifest, write_acquisition_queue
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


def test_export_review_csv_filters_existing_cached_pmc_xml_from_stale_queue(tmp_path) -> None:
    cache = make_cache(tmp_path)
    doc = NormalizedDocument(
        document_id="pmid:123",
        source="pubmed",
        pmid="123",
        doi="10.1000/example",
        pmc_id="PMC123",
    )
    cache.write_document(doc, access_status="metadata-only", parser_version="pubmed-v1")
    write_acquisition_queue([doc], cache.root / "reports" / "acquisition_queue.jsonl", include_cached_fulltext=True)
    cache.write_bytes("raw/pmc/xml/PMC123.xml", b"<article/>")
    output = cache.root / "acquisition" / "review.csv"

    count = export_review_csv(cache, output)

    assert count == 0
    assert len(read_queue(cache, include_cached_fulltext=True)) == 2


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


def test_register_manual_assets_from_csv_manifest(tmp_path) -> None:
    cache = make_cache(tmp_path)
    pdf_one = tmp_path / "one.pdf"
    pdf_two = tmp_path / "two.pdf"
    pdf_one.write_bytes(b"%PDF-1.4\nfirst")
    pdf_two.write_bytes(b"%PDF-1.4\nsecond")
    manifest = tmp_path / "batch.csv"
    manifest.write_text(
        "\n".join(
            [
                "file,document_id,access_method,access_status,source_url",
                "one.pdf,pmid:1,imperial-library,licensed-access,https://doi.org/10.1/one",
                "two.pdf,pmid:2,manual-upload,licensed-access,",
            ]
        )
        + "\n"
    )

    result = register_manual_assets_from_manifest(cache, manifest_path=manifest)

    assert result["registered"] == 2
    assert result["failed"] == 0
    assert len(cache.read_jsonl("acquisition/registered_assets.jsonl")) == 2
    assert len(cache.read_jsonl("assets/asset_manifest.jsonl")) == 2


def test_register_manual_assets_from_manifest_dry_run_does_not_write(tmp_path) -> None:
    cache = make_cache(tmp_path)
    pdf = tmp_path / "article.pdf"
    pdf.write_bytes(b"%PDF-1.4\npaper")
    manifest = tmp_path / "batch.csv"
    manifest.write_text("file,document_id\narticle.pdf,pmid:1\n")

    result = register_manual_assets_from_manifest(
        cache,
        manifest_path=manifest,
        default_access_method="manual-upload",
        dry_run=True,
    )

    assert result["registered"] == 1
    assert result["failed"] == 0
    assert cache.read_jsonl("acquisition/registered_assets.jsonl") == []


def test_write_batch_template_creates_csv(tmp_path) -> None:
    output = tmp_path / "template.csv"

    write_batch_template(output)

    text = output.read_text()
    assert "file,document_id,access_method" in text
    assert "/path/to/downloaded/article.pdf" in text


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
