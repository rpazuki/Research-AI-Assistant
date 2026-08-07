"""Tests for the three ingesters that consume a finished datasheet run.

Each builds a real run directory in tmp_path — a manifest CSV written by the
production writer, plus the `fulltext/<stem>.json` payloads the acquisition
ladder produces — so the tests exercise the same file layout the backend writes
rather than a hand-drawn approximation of it.
"""

import json

import pytest

from pipelines.acquisition.cache_layout import cache_paths, manifest_csv_path, safe_stem
from pipelines.corpus_cache import CorpusCache, CorpusManifest
from pipelines.discovery.canonicalize import Candidate
from pipelines.discovery.manifest_csv import write_manifest_csv
from pipelines.ingestion.datasheet_fulltext import DatasheetFullTextIngester, text_document
from pipelines.ingestion.datasheet_manifest import (
    DatasheetManifestIngester,
    parse_manifest_row,
    read_manifest,
    resolve_manifest_path,
    row_to_metadata_document,
    select_rows,
)
from pipelines.ingestion.datasheet_rows import (
    DatasheetRowsIngester,
    row_to_document,
    row_to_text,
)


def make_cache(tmp_path, source: str) -> CorpusCache:
    manifest = CorpusManifest(
        schema_version="1.0",
        corpus_name="test-datasheet",
        run_id="2026-08-06T120000Z",
        created_at="2026-08-06T12:00:00Z",
        source=source,
    )
    return CorpusCache.create(base_dir=tmp_path / "corpus", manifest=manifest)


def make_run_dir(tmp_path, candidates: list[Candidate], included_dois: set[str] | None = None):
    """A datasheet run directory with the manifest its discovery phase writes."""
    run_dir = tmp_path / "run"
    path = manifest_csv_path(run_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    if included_dois is None:
        included_dois = {candidate.doi for candidate in candidates if candidate.doi}
    path.write_text(write_manifest_csv(candidates, included_dois=included_dois))
    return run_dir


def make_candidate(**overrides) -> Candidate:
    defaults = dict(
        doi="10.1016/j.ymben.2020.01.001",
        pmid="31234567",
        pmc_id="PMC7654321",
        title="Engineering Yarrowia lipolytica",
        journal="Metabolic Engineering",
        publisher="Elsevier",
        year=2020,
        found_in=("pubmed", "crossref"),
        doc_type="primary",
        relevance="studies",
        oa_status="hybrid",
        license="cc-by",
    )
    defaults.update(overrides)
    return Candidate(**defaults)


def write_fulltext(run_dir, identifier: str, payload: dict) -> None:
    _asset_base, text_path = cache_paths(run_dir, identifier)
    text_path.parent.mkdir(parents=True, exist_ok=True)
    text_path.write_text(json.dumps(payload), encoding="utf-8")


SAMPLE_PAYLOAD = {
    "source_format": "xml",
    "title": "Engineering Yarrowia lipolytica",
    "abstract": "We engineered Po1g-Δku70.",
    "warnings": ["greek character loss suspected"],
    "sections": [
        {"label": "methods", "heading": "Materials and Methods", "text": "Strains were grown."},
        {"label": "results", "heading": "Results", "text": "Titre reached 50 g/L."},
        {"label": "other", "heading": "Acknowledgements", "text": "   "},
    ],
}


# ── Manifest parsing ──────────────────────────────────────────────────────────


def test_not_reported_is_read_as_absent_not_as_a_value() -> None:
    row = parse_manifest_row(
        {"doi": "10.1/x", "pmid": "Not reported", "year": "Not reported", "is_review": "no"}
    )

    assert row.pmid is None
    assert row.year is None
    assert row.is_review is False


def test_manifest_round_trips_through_the_production_writer(tmp_path) -> None:
    run_dir = make_run_dir(tmp_path, [make_candidate()])

    rows = read_manifest(manifest_csv_path(run_dir))

    assert len(rows) == 1
    assert rows[0].doi == "10.1016/j.ymben.2020.01.001"
    assert rows[0].pmid == "31234567"
    assert rows[0].pmc_id == "PMC7654321"
    assert rows[0].found_in == ("pubmed", "crossref")
    assert rows[0].included is True
    assert rows[0].publisher == "Elsevier"


def test_missing_manifest_names_where_it_should_have_come_from(tmp_path) -> None:
    with pytest.raises(FileNotFoundError) as excinfo:
        read_manifest(tmp_path / "nope" / "manifest.csv")

    assert "discovery phase" in str(excinfo.value)


def test_resolve_manifest_path_requires_a_run_dir_or_an_explicit_path() -> None:
    with pytest.raises(ValueError):
        resolve_manifest_path(None, None)


# ── Row selection ─────────────────────────────────────────────────────────────


def test_selection_respects_the_runs_own_inclusion_decision(tmp_path) -> None:
    kept = make_candidate()
    excluded = make_candidate(doi="10.1/excluded", pmid="99", pmc_id=None)
    run_dir = make_run_dir(tmp_path, [kept, excluded], included_dois={kept.doi})

    selected = select_rows(read_manifest(manifest_csv_path(run_dir)))

    assert [row.doi for row in selected] == [kept.doi]


def test_reviews_and_retractions_are_excluded_by_default_and_admissible_on_request(tmp_path) -> None:
    review = make_candidate(doi="10.1/review", pmid="1", pmc_id=None, is_review=True)
    retracted = make_candidate(doi="10.1/retracted", pmid="2", pmc_id=None, is_retracted=True)
    run_dir = make_run_dir(tmp_path, [review, retracted])
    rows = read_manifest(manifest_csv_path(run_dir))

    assert select_rows(rows) == []
    assert [row.doi for row in select_rows(rows, include_reviews=True)] == ["10.1/review"]
    assert [row.doi for row in select_rows(rows, include_retracted=True)] == ["10.1/retracted"]


def test_min_relevance_mentions_admits_what_studies_excludes(tmp_path) -> None:
    mention = make_candidate(doi="10.1/mention", pmid="3", pmc_id=None, relevance="mentions")
    run_dir = make_run_dir(tmp_path, [mention])
    rows = read_manifest(manifest_csv_path(run_dir))

    assert select_rows(rows, min_relevance="studies") == []
    assert len(select_rows(rows, min_relevance="mentions")) == 1


# ── datasheet_manifest ────────────────────────────────────────────────────────


class RecordingIngester:
    """Stands in for the PMC / PubMed ingesters, recording what it was asked for."""

    def __init__(self, docs, calls, key):
        self.docs = docs
        self.calls = calls
        self.key = key

    def fetch(self):
        yield from self.docs


def install_fetchers(monkeypatch, ingester, *, pmc_docs=(), pubmed_docs=()):
    calls: dict[str, list] = {"pmc": [], "pubmed": []}

    def fake_pmc(ids):
        calls["pmc"].append(list(ids))
        return iter(pmc_docs)

    def fake_pubmed(ids):
        calls["pubmed"].append(list(ids))
        return iter(pubmed_docs)

    monkeypatch.setattr(ingester, "_fetch_pmc", fake_pmc)
    monkeypatch.setattr(ingester, "_fetch_pubmed", fake_pubmed)
    return calls


def requested(calls: dict[str, list], key: str) -> list[str]:
    return [identifier for call in calls[key] for identifier in call]


def test_manifest_routes_pmcids_to_full_text_and_the_rest_to_abstracts(tmp_path, monkeypatch) -> None:
    from pipelines.processing.normalizer import NormalizedDocument

    with_pmc = make_candidate()
    pmid_only = make_candidate(doi="10.1/b", pmid="222", pmc_id=None)
    run_dir = make_run_dir(tmp_path, [with_pmc, pmid_only])

    ingester = DatasheetManifestIngester(manifest_csv_path(run_dir))
    calls = install_fetchers(
        monkeypatch,
        ingester,
        pmc_docs=[
            NormalizedDocument(document_id="pmc:PMC7654321", source="pmc", pmc_id="PMC7654321")
        ],
    )
    list(ingester.fetch())

    assert requested(calls, "pmc") == ["PMC7654321"]
    # The PMC row is not fetched a second time as an abstract: it has full text.
    assert requested(calls, "pubmed") == ["222"]


def test_fetch_fulltext_false_sends_everything_to_pubmed(tmp_path, monkeypatch) -> None:
    run_dir = make_run_dir(tmp_path, [make_candidate()])

    ingester = DatasheetManifestIngester(manifest_csv_path(run_dir), fetch_fulltext=False)
    calls = install_fetchers(monkeypatch, ingester)
    list(ingester.fetch())

    assert requested(calls, "pmc") == []
    assert requested(calls, "pubmed") == ["31234567"]


def test_unretrievable_full_text_falls_back_to_the_abstract(tmp_path, monkeypatch) -> None:
    """A PMCID is not a promise: the OA subset is smaller than the set of
    deposited articles, and a paper the run judged relevant must not vanish
    because its full text was not served."""
    run_dir = make_run_dir(tmp_path, [make_candidate()])

    ingester = DatasheetManifestIngester(manifest_csv_path(run_dir))
    calls = install_fetchers(monkeypatch, ingester, pmc_docs=())  # PMC returns nothing
    list(ingester.fetch())

    assert calls["pubmed"] == [["31234567"]]


def test_metadata_only_rows_are_skipped_by_default_and_the_count_is_logged(
    tmp_path, monkeypatch, caplog
) -> None:
    doi_only = make_candidate(doi="10.1/c", pmid=None, pmc_id=None)
    run_dir = make_run_dir(tmp_path, [doi_only])

    ingester = DatasheetManifestIngester(manifest_csv_path(run_dir))
    install_fetchers(monkeypatch, ingester)
    with caplog.at_level("WARNING"):
        docs = list(ingester.fetch())

    assert docs == []
    assert "skipped 1 selected rows" in caplog.text


def test_metadata_only_rows_can_be_indexed_on_request(tmp_path, monkeypatch) -> None:
    cache = make_cache(tmp_path, "datasheet_manifest")
    doi_only = make_candidate(doi="10.1/c", pmid=None, pmc_id=None, title="Title only")
    run_dir = make_run_dir(tmp_path, [doi_only])

    ingester = DatasheetManifestIngester(
        manifest_csv_path(run_dir), skip_metadata_only=False, cache=cache
    )
    install_fetchers(monkeypatch, ingester)
    docs = list(ingester.fetch())

    assert [doc.document_id for doc in docs] == ["doi:10.1/c"]
    assert docs[0].metadata["metadata_only"] is True
    assert cache.read_jsonl("normalized/documents.jsonl")[0]["title"] == "Title only"


def test_metadata_document_carries_the_bibliography_but_no_body(tmp_path) -> None:
    run_dir = make_run_dir(tmp_path, [make_candidate(pmid=None, pmc_id=None)])
    row = read_manifest(manifest_csv_path(run_dir))[0]

    doc = row_to_metadata_document(row)

    assert doc.abstract is None
    assert doc.full_text is None
    assert doc.publisher == "Elsevier"
    assert doc.url == "https://doi.org/10.1016/j.ymben.2020.01.001"


def test_pubmed_fetch_without_credentials_fails_loudly(tmp_path) -> None:
    run_dir = make_run_dir(tmp_path, [make_candidate(pmc_id=None)])
    ingester = DatasheetManifestIngester(
        manifest_csv_path(run_dir), pubmed_email=None, pubmed_api_key=None
    )

    with pytest.raises(ValueError) as excinfo:
        list(ingester.fetch())

    assert "NCBI_EMAIL" in str(excinfo.value)


# ── datasheet_fulltext ────────────────────────────────────────────────────────


def test_fulltext_document_keeps_sections_and_their_labels(tmp_path) -> None:
    run_dir = make_run_dir(tmp_path, [make_candidate()])
    row = read_manifest(manifest_csv_path(run_dir))[0]

    doc = text_document(row, SAMPLE_PAYLOAD, asset_path="assets/x.xml")

    assert [section["label"] for section in doc.sections] == ["methods", "results"]
    assert "Titre reached 50 g/L." in doc.full_text
    assert doc.abstract == "We engineered Po1g-Δku70."
    assert doc.full_text_source == "pmc_jats"
    assert doc.metadata["fidelity_warnings"] == ["greek character loss suspected"]
    assert doc.journal == "Metabolic Engineering"  # bibliography from the manifest row


def test_pdf_sourced_text_is_labelled_as_licensed_access(tmp_path) -> None:
    run_dir = make_run_dir(tmp_path, [make_candidate()])
    row = read_manifest(manifest_csv_path(run_dir))[0]

    doc = text_document(row, {**SAMPLE_PAYLOAD, "source_format": "pdf"}, asset_path=None)

    assert doc.source == "pdf"
    assert doc.full_text_source == "pdf_text"
    assert doc.metadata["access_status"] == "licensed-access"


def test_fulltext_ingester_reads_a_real_run_directory(tmp_path) -> None:
    cache = make_cache(tmp_path, "datasheet_fulltext")
    candidate = make_candidate()
    run_dir = make_run_dir(tmp_path, [candidate])
    write_fulltext(run_dir, candidate.doi, SAMPLE_PAYLOAD)

    docs = list(DatasheetFullTextIngester(run_dir, cache=cache).fetch())

    assert [doc.document_id for doc in docs] == ["pmid:31234567"]
    # The manifest is copied in so the corpus cache stays replayable on its own.
    assert (cache.root / "raw" / "datasheet" / "manifest.csv").exists()
    assert (cache.root / "raw" / "datasheet" / "fulltext").glob("*.json")
    cached = cache.read_jsonl("normalized/documents.jsonl")[0]
    assert [section["label"] for section in cached["sections"]] == ["methods", "results"]
    assert cache.validate()["ok"] is True


def test_rows_without_fetched_text_are_counted_not_faked(tmp_path, caplog) -> None:
    run_dir = make_run_dir(tmp_path, [make_candidate()])  # no fulltext written

    with caplog.at_level("INFO"):
        docs = list(DatasheetFullTextIngester(run_dir).fetch())

    assert docs == []
    assert "1 selected rows had no fetched text" in caplog.text


def test_unreadable_payload_becomes_an_error_record(tmp_path) -> None:
    cache = make_cache(tmp_path, "datasheet_fulltext")
    candidate = make_candidate()
    run_dir = make_run_dir(tmp_path, [candidate])
    _asset_base, text_path = cache_paths(run_dir, candidate.doi)
    text_path.parent.mkdir(parents=True, exist_ok=True)
    text_path.write_text("{not json", encoding="utf-8")

    docs = list(DatasheetFullTextIngester(run_dir, cache=cache).fetch())

    assert docs == []
    errors = cache.read_jsonl("normalized/documents.errors.jsonl")
    assert errors[0]["error_type"] == "fulltext_unreadable"


def test_payload_with_no_text_is_recorded_rather_than_indexed(tmp_path) -> None:
    cache = make_cache(tmp_path, "datasheet_fulltext")
    candidate = make_candidate()
    run_dir = make_run_dir(tmp_path, [candidate])
    write_fulltext(
        run_dir, candidate.doi, {"source_format": "pdf", "sections": [], "warnings": []}
    )

    docs = list(DatasheetFullTextIngester(run_dir, cache=cache).fetch())

    assert docs == []
    assert cache.read_jsonl("normalized/documents.errors.jsonl")[0]["error_type"] == (
        "fulltext_unreadable"
    )


def test_stems_are_derived_the_same_way_the_backend_wrote_them() -> None:
    """The one-way stem is the contract between the two sides; if it drifts, the
    ingester silently finds nothing."""
    identifier = "10.1016/j.ymben.2020.01.001"
    asset_base, text_path = cache_paths(__import__("pathlib").Path("/run"), identifier)

    assert text_path.name == f"{safe_stem(identifier)}.json"
    assert asset_base.name == safe_stem(identifier)


# ── datasheet_rows ────────────────────────────────────────────────────────────


DATASHEET_ROW = {
    "Date": "2020-03-15",
    "Standard Product Class": "Organic Acids",
    "Compounds": "citric acid",
    "Concentration/Yield": "50 g/L",
    "strain used/RLA collection strain": "Po1g-Δku70",
    "carbon source": "glucose",
    "Comments": "Not reported",
    "Article": "Engineering Yarrowia lipolytica",
    "doi": "10.1016/j.ymben.2020.01.001",
    "pmid": "31234567",
    "journal": "Metabolic Engineering",
    "year": "2020",
}


def test_row_text_keeps_the_science_and_drops_the_bibliography() -> None:
    text = row_to_text(DATASHEET_ROW)

    assert "Compounds: citric acid" in text
    assert "strain used/RLA collection strain: Po1g-Δku70" in text
    # Provenance columns identify the paper; repeating them inside the indexed
    # text adds nothing retrievable and dilutes the chunk.
    assert "doi:" not in text
    assert "journal:" not in text
    # 'Not reported' is an empty cell, not a finding.
    assert "Comments" not in text


def test_row_becomes_a_citable_document() -> None:
    doc = row_to_document(
        DATASHEET_ROW, row_index=3, template_name="default", source_path=__import__("pathlib").Path("d.csv")
    )

    assert doc.source == "datasheet_row"
    assert doc.doi == "10.1016/j.ymben.2020.01.001"
    assert doc.pmid == "31234567"
    assert doc.year == 2020
    assert doc.title == "Datasheet row: Engineering Yarrowia lipolytica"
    assert doc.document_id.startswith("datasheet_row:")


def test_two_rows_about_one_paper_stay_two_documents() -> None:
    """Several rows legitimately describe the same article — different product,
    different condition. Merging them onto one id would keep only the last."""
    path = __import__("pathlib").Path("d.csv")
    first = row_to_document(DATASHEET_ROW, row_index=0, template_name="default", source_path=path)
    second = row_to_document(DATASHEET_ROW, row_index=1, template_name="default", source_path=path)

    assert first.document_id != second.document_id


def test_row_ids_are_stable_across_rebuilds() -> None:
    path = __import__("pathlib").Path("d.csv")
    args = dict(row_index=0, template_name="default", source_path=path)

    assert row_to_document(DATASHEET_ROW, **args).document_id == (
        row_to_document(DATASHEET_ROW, **args).document_id
    )


def test_identifier_columns_are_matched_case_insensitively() -> None:
    doc = row_to_document(
        {"DOI": "10.1/x", "Article": "T", "Compounds": "citrate"},
        row_index=0,
        template_name="default",
        source_path=__import__("pathlib").Path("d.csv"),
    )

    assert doc.doi == "10.1/x"


def test_empty_row_produces_no_document() -> None:
    assert (
        row_to_document(
            {"doi": "10.1/x", "Compounds": "Not reported"},
            row_index=0,
            template_name="default",
            source_path=__import__("pathlib").Path("d.csv"),
        )
        is None
    )


def test_rows_ingester_reads_a_csv_and_caches_provenance(tmp_path) -> None:
    cache = make_cache(tmp_path, "datasheet_rows")
    csv_path = tmp_path / "rows.csv"
    csv_path.write_text(
        "Article,Compounds,Concentration/Yield,doi,year\n"
        "Engineering Yarrowia,citric acid,50 g/L,10.1/a,2020\n"
        "Engineering Yarrowia,erythritol,20 g/L,10.1/a,2020\n",
        encoding="utf-8",
    )

    docs = list(DatasheetRowsIngester(csv_path, cache=cache).fetch())

    assert len(docs) == 2
    assert docs[0].document_id != docs[1].document_id
    assert "citric acid" in docs[0].full_text
    assets = cache.read_jsonl("assets/asset_manifest.jsonl")
    assert assets[0]["asset_type"] == "datasheet_rows"
    assert assets[0]["sensitivity"] == "internal"
    assert cache.validate()["ok"] is True


def test_rows_ingester_reports_a_missing_file(tmp_path) -> None:
    with pytest.raises(FileNotFoundError):
        list(DatasheetRowsIngester(tmp_path / "absent.csv").fetch())
