from datetime import date

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