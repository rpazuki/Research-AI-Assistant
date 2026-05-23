from pipelines.corpus_cache import CorpusCache, CorpusManifest
from pipelines.ingestion.lab_sources import (
    LocalTableCollectionIngester,
    LocalTextCollectionIngester,
)


def make_cache(tmp_path, source: str) -> CorpusCache:
    manifest = CorpusManifest(
        schema_version="1.0",
        corpus_name="test-corpus",
        run_id="2026-05-23T120000Z",
        created_at="2026-05-23T12:00:00Z",
        source=source,
    )
    return CorpusCache.create(base_dir=tmp_path, manifest=manifest)


def test_protocol_adapter_preserves_original_and_normalizes_text(tmp_path) -> None:
    source_dir = tmp_path / "protocols"
    source_dir.mkdir()
    (source_dir / "transformation.md").write_text("# Transformation\nUse fresh cells.")
    cache = make_cache(tmp_path / "cache", "lab_protocols")

    docs = list(
        LocalTextCollectionIngester(
            str(source_dir),
            "lab_protocols",
            cache=cache,
            sensitivity="internal",
            owner="RLA Lab",
        ).fetch()
    )

    assert docs[0].source == "protocol"
    assert "fresh cells" in docs[0].full_text
    assert (cache.root / docs[0].metadata["raw_asset_path"]).exists()
    assert cache.read_jsonl("normalized/documents.jsonl")[0]["sensitivity"] == "internal"


def test_table_adapter_summarizes_inventory_rows(tmp_path) -> None:
    source_dir = tmp_path / "inventory"
    source_dir.mkdir()
    (source_dir / "strains.csv").write_text("strain,genotype,location\nYL1,ku70-,Box A\n")
    cache = make_cache(tmp_path / "cache", "inventories")

    docs = list(
        LocalTableCollectionIngester(
            str(source_dir),
            "inventories",
            cache=cache,
            sensitivity="confidential",
        ).fetch()
    )

    assert docs[0].source == "inventory"
    assert "Columns: strain, genotype, location" in docs[0].full_text
    assert "Row 1: strain: YL1" in docs[0].full_text
    assert cache.validate()["ok"] is True
