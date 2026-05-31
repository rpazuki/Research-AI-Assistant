from datetime import date

from pipelines.corpus_cache import CorpusCache, CorpusManifest
from pipelines.ingestion.pubmed_abstract import PubMedAbstractIngester


def make_ingester(incremental_from: date | None = None) -> PubMedAbstractIngester:
    return PubMedAbstractIngester(
        query='"Yarrowia lipolytica"[Title/Abstract]',
        year_from=2024,
        year_to=2026,
        email="test@example.com",
        api_key="dummy",
        incremental_from=incremental_from,
    )


def test_build_year_query_without_incremental_date_uses_year_only() -> None:
    ingester = make_ingester()

    query = ingester._build_year_query(2025)

    assert query == '("Yarrowia lipolytica"[Title/Abstract]) AND 2025[PDAT]'


def test_build_year_query_with_incremental_date_adds_publication_bounds() -> None:
    ingester = make_ingester(date(2025, 5, 1))

    query = ingester._build_year_query(2025)

    assert '2025[PDAT]' in query
    assert '2025-05-01"[Date - Publication]' in query
    assert 'Date - Publication' in query


def test_incremental_checkpoint_file_is_scoped_by_date() -> None:
    ingester = make_ingester(date(2025, 5, 1))

    checkpoint = ingester._checkpoint_file_for_year(2025)

    assert checkpoint.name == 'pmids_2025_2025-05-01.json'


def test_incremental_cache_esearch_file_is_scoped_by_date() -> None:
    ingester = make_ingester(date(2025, 5, 1))

    path = ingester._cache_esearch_relative_path_for_year(2025)

    assert path == "raw/pubmed/esearch/pmids_2025_2025-05-01.json"


def test_cached_pubmed_batches_are_keyed_by_pmid_list(tmp_path) -> None:
    manifest = CorpusManifest(
        schema_version="1.0",
        corpus_name="test-corpus",
        run_id="run",
        created_at="2026-05-30T12:00:00Z",
        source="pubmed_abstract",
    )
    cache = CorpusCache.create(base_dir=tmp_path, manifest=manifest)
    ingester = make_ingester(date(2025, 5, 1))
    ingester.cache = cache

    calls: list[list[str]] = []

    def fake_fetch(id_list: list[str]) -> str:
        calls.append(id_list)
        return f"<xml>{','.join(id_list)}</xml>"

    ingester._safe_efetch_xml = fake_fetch  # type: ignore[method-assign]

    first_xml, first_path = ingester._get_or_fetch_batch_xml(["1"], 1)
    second_xml, second_path = ingester._get_or_fetch_batch_xml(["2"], 1)

    assert first_path != second_path
    assert first_xml == "<xml>1</xml>"
    assert second_xml == "<xml>2</xml>"
    assert calls == [["1"], ["2"]]
