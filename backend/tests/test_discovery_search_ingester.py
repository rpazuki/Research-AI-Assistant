"""Tests for the multi-source discovery ingester.

No network: `discover` is replaced with a function returning a fixed
`DiscoveryResult`, so what is under test is the mapping from a merged candidate
to a corpus document, and the audit artifacts written alongside it.
"""

import json

import pytest

from pipelines.corpus_cache import CorpusCache, CorpusManifest
from pipelines.discovery.canonicalize import Candidate
from pipelines.discovery.discover import DiscoveryResult
from pipelines.ingestion import discovery_search
from pipelines.ingestion.discovery_search import (
    DiscoverySearchIngester,
    candidate_from_cache_record,
    candidate_to_document,
    _candidate_to_cache_record,
)


def make_cache(tmp_path) -> CorpusCache:
    manifest = CorpusManifest(
        schema_version="1.0",
        corpus_name="test-discovery",
        run_id="2026-08-06T120000Z",
        created_at="2026-08-06T12:00:00Z",
        source="discovery_search",
    )
    return CorpusCache.create(base_dir=tmp_path, manifest=manifest)


def make_candidate(**overrides) -> Candidate:
    defaults = dict(
        doi="10.1016/j.ymben.2020.01.001",
        pmid="31234567",
        pmc_id="PMC7654321",
        title="Engineering Yarrowia lipolytica for lipid production",
        abstract="We engineered the strain.",
        journal="Metabolic Engineering",
        publisher="Elsevier",
        year=2020,
        published_date="2020-03-15",
        oa_status="hybrid",
        license="cc-by",
        found_in=("pubmed", "crossref"),
        doc_type="primary",
        relevance="studies",
        relevance_reason="organism in title",
        mesh_terms=("Yarrowia",),
        keywords=("lipids",),
        dedupe_group="doi:10.1016/j.ymben.2020.01.001",
    )
    defaults.update(overrides)
    return Candidate(**defaults)


# ── Candidate → document mapping ──────────────────────────────────────────────


def test_maps_every_bibliographic_field_onto_the_document() -> None:
    doc = candidate_to_document(make_candidate())

    assert doc.source == "discovery"
    assert doc.title == "Engineering Yarrowia lipolytica for lipid production"
    assert doc.abstract == "We engineered the strain."
    assert doc.journal == "Metabolic Engineering"
    assert doc.year == 2020
    assert doc.publication_date.isoformat() == "2020-03-15"
    assert doc.doi == "10.1016/j.ymben.2020.01.001"
    assert doc.pmc_id == "PMC7654321"
    assert doc.mesh_terms == ["Yarrowia"]
    assert doc.keywords == ["lipids"]
    assert doc.publisher == "Elsevier"
    assert doc.oa_status == "hybrid"
    assert doc.doc_type == "primary"
    assert doc.full_text_source == "abstract_only"


def test_document_id_prefers_pmid_so_pubmed_and_discovery_share_a_row() -> None:
    """`documents.document_id` is UNIQUE: one paper must not enter twice under
    two identifiers just because two sources found it."""
    assert candidate_to_document(make_candidate()).document_id == "pmid:31234567"


def test_document_id_falls_back_through_doi_then_pmcid() -> None:
    assert candidate_to_document(make_candidate(pmid=None)).document_id == (
        "doi:10.1016/j.ymben.2020.01.001"
    )
    assert candidate_to_document(make_candidate(pmid=None, doi=None)).document_id == (
        "pmc:PMC7654321"
    )


def test_identifierless_candidate_still_gets_a_stable_id() -> None:
    """canonicalise() keeps records with no registrar identifier as their own
    candidates, so this path is reachable and must not collide across runs."""
    bare = make_candidate(pmid=None, doi=None, pmc_id=None)

    first = candidate_to_document(bare).document_id
    second = candidate_to_document(bare).document_id

    assert first == second
    assert first.startswith("discovery:")


def test_retraction_and_review_flags_reach_the_document() -> None:
    doc = candidate_to_document(make_candidate(is_retracted=True, is_review=True))

    # Retrieval filters on is_retracted; carrying the flag is how a retracted
    # paper stays in the corpus for audit while staying out of chat answers.
    assert doc.is_retracted is True
    assert doc.is_review is True


def test_preprint_records_its_version_of_record_only_when_it_is_a_preprint() -> None:
    preprint = candidate_to_document(
        make_candidate(is_preprint=True, version_of_record_doi="10.1016/vor")
    )
    published = candidate_to_document(
        make_candidate(is_preprint=False, version_of_record_doi="10.1016/vor")
    )

    assert preprint.preprint_of_doi == "10.1016/vor"
    assert published.preprint_of_doi is None


def test_unparseable_published_date_is_dropped_not_guessed() -> None:
    assert candidate_to_document(make_candidate(published_date="Spring 2020")).publication_date is None


def test_metadata_holds_only_json_primitives() -> None:
    """documents.metadata is json.dumps'd with the default encoder during upsert;
    a tuple survives that, but a non-serialisable value would abort the run."""
    doc = candidate_to_document(make_candidate())

    json.dumps(doc.metadata)
    assert doc.metadata["found_in"] == ["pubmed", "crossref"]
    assert doc.metadata["relevance"] == "studies"
    assert doc.metadata["parser_version"] == "discovery-v1"


def test_url_falls_back_to_the_doi_resolver() -> None:
    assert candidate_to_document(make_candidate(url=None)).url == (
        "https://doi.org/10.1016/j.ymben.2020.01.001"
    )


# ── fetch() ───────────────────────────────────────────────────────────────────


def install_fake_discover(monkeypatch, result: DiscoveryResult) -> list[dict]:
    calls: list[dict] = []

    def fake_discover(query, **kwargs):
        calls.append({"query": query, **kwargs})
        return result

    monkeypatch.setattr(discovery_search, "discover", fake_discover)
    return calls


def test_fetch_yields_included_candidates_and_writes_the_audit_trail(tmp_path, monkeypatch) -> None:
    cache = make_cache(tmp_path)
    kept = make_candidate()
    dropped = make_candidate(
        doi="10.1/off", pmid="222", pmc_id=None, relevance="off_topic", title="Unrelated"
    )
    result = DiscoveryResult(
        candidates=[kept, dropped],
        source_record_counts={"pubmed": 1, "crossref": 1},
        total_source_records=2,
    )
    install_fake_discover(monkeypatch, result)

    ingester = DiscoverySearchIngester(
        organism_terms=["Yarrowia lipolytica"], cache=cache
    )
    docs = list(ingester.fetch())

    assert [doc.document_id for doc in docs] == ["pmid:31234567"]

    # Every candidate is in the audit artifacts, including the one that was
    # dropped: an exclusion nobody can see is an exclusion nobody can dispute.
    candidates = cache.read_jsonl("raw/discovery/candidates.jsonl")
    assert {row["doi"] for row in candidates} == {kept.doi, dropped.doi}

    manifest_csv = (cache.root / "reports" / "discovery_manifest.csv").read_text()
    assert "Unrelated" in manifest_csv
    assert manifest_csv.splitlines()[0].startswith("doi,pmid,pmc_id,title")

    summary = json.loads((cache.root / "raw" / "discovery" / "summary.json").read_text())
    assert summary["total_source_records"] == 2

    assets = cache.read_jsonl("assets/asset_manifest.jsonl")
    assert assets[0]["asset_type"] == "discovery_candidates"
    assert assets[0]["access_status"] == "metadata-only"


def test_fetch_writes_normalized_documents_and_validates(tmp_path, monkeypatch) -> None:
    cache = make_cache(tmp_path)
    install_fake_discover(monkeypatch, DiscoveryResult(candidates=[make_candidate()]))

    list(DiscoverySearchIngester(organism_terms=["Yarrowia"], cache=cache).fetch())

    records = cache.read_jsonl("normalized/documents.jsonl")
    assert records[0]["document_id"] == "pmid:31234567"
    assert records[0]["publisher"] == "Elsevier"
    assert cache.validate()["ok"] is True


def test_fetch_passes_configured_sources_and_flags_to_discover(tmp_path, monkeypatch) -> None:
    calls = install_fake_discover(monkeypatch, DiscoveryResult(candidates=[]))

    ingester = DiscoverySearchIngester(
        organism_terms=["Yarrowia"],
        product_terms=["citric acid"],
        year_from=2016,
        year_to=2026,
        sources=("pubmed", "openalex"),
        max_records_per_source=42,
        include_mentions=True,
        check_retraction_notices=True,
    )
    list(ingester.fetch())

    assert calls[0]["sources"] == ("pubmed", "openalex")
    assert calls[0]["include_mentions"] is True
    assert calls[0]["check_retraction_notices"] is True
    query = calls[0]["query"]
    assert query.organism_terms == ("Yarrowia",)
    assert query.product_terms == ("citric acid",)
    assert query.max_records_per_source == 42


def test_fetch_refuses_a_query_with_no_terms() -> None:
    with pytest.raises(ValueError):
        list(DiscoverySearchIngester(organism_terms=[]).fetch())


def test_candidates_without_abstracts_are_indexed_and_counted(tmp_path, monkeypatch, caplog) -> None:
    """Crossref-only rows routinely have no abstract. They are still useful, but
    the count must be visible rather than a silent quality drop."""
    cache = make_cache(tmp_path)
    install_fake_discover(
        monkeypatch, DiscoveryResult(candidates=[make_candidate(abstract=None)])
    )

    with caplog.at_level("WARNING"):
        docs = list(DiscoverySearchIngester(organism_terms=["Yarrowia"], cache=cache).fetch())

    assert len(docs) == 1
    assert "no abstract" in caplog.text


def test_source_failures_are_logged_not_swallowed(tmp_path, monkeypatch, caplog) -> None:
    install_fake_discover(
        monkeypatch,
        DiscoveryResult(candidates=[], source_errors={"crossref": "503 from upstream"}),
    )

    with caplog.at_level("WARNING"):
        list(DiscoverySearchIngester(organism_terms=["Yarrowia"]).fetch())

    assert "crossref" in caplog.text


# ── Cache round trip ──────────────────────────────────────────────────────────


def test_candidate_survives_a_cache_round_trip() -> None:
    original = make_candidate()

    restored = candidate_from_cache_record(_candidate_to_cache_record(original))

    assert restored == original


def test_cache_record_drops_unserialisable_extras() -> None:
    record = _candidate_to_cache_record(make_candidate(extra={"client": object()}))

    json.dumps(record)
    assert record["extra"] == {}


# ── from_config ───────────────────────────────────────────────────────────────


def write_config(tmp_path, monkeypatch, body: str):
    defaults = tmp_path / "pipeline.defaults.yaml"
    defaults.write_text("defaults:\n  discovery:\n    max_records_per_source: 100\nenvironments:\n  local: {}\n")
    monkeypatch.setenv("PIPELINE_CONFIG_FILE", str(defaults))
    config = tmp_path / "discovery.toml"
    config.write_text(body)
    return config


def test_from_config_reads_terms_sources_and_contact_addresses(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("NCBI_EMAIL", "lab@imperial.ac.uk")
    monkeypatch.setenv("NCBI_API_KEY", "key-123")
    monkeypatch.delenv("CROSSREF_MAILTO", raising=False)
    monkeypatch.delenv("OPENALEX_MAILTO", raising=False)
    config = write_config(
        tmp_path,
        monkeypatch,
        """
[corpus]
name = "rlalab-discovery-v1"
source = "discovery_search"

[discovery]
organism_terms = ["Yarrowia lipolytica"]
product_terms = ["citric acid"]
year_from = 2016
year_to = 2026
sources = ["pubmed", "crossref"]
include_mentions = true
""".strip(),
    )

    ingester = DiscoverySearchIngester.from_config(str(config))

    assert ingester.organism_terms == ["Yarrowia lipolytica"]
    assert ingester.product_terms == ["citric acid"]
    assert ingester.sources == ("pubmed", "crossref")
    assert ingester.year_from == 2016
    assert ingester.include_mentions is True
    assert ingester.max_records_per_source == 100  # from the defaults file
    assert ingester.credentials.ncbi_email == "lab@imperial.ac.uk"
    assert ingester.credentials.ncbi_api_key == "key-123"
    # Both polite-pool addresses fall back to the NCBI one, which is the address
    # guaranteed to be configured.
    assert ingester.credentials.crossref_mailto == "lab@imperial.ac.uk"
    assert ingester.credentials.openalex_mailto == "lab@imperial.ac.uk"


def test_from_config_prefers_explicit_mailto_env_over_the_ncbi_fallback(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("NCBI_EMAIL", "lab@imperial.ac.uk")
    monkeypatch.setenv("CROSSREF_MAILTO", "crossref@imperial.ac.uk")
    monkeypatch.setenv("OPENALEX_MAILTO", "openalex@imperial.ac.uk")
    config = write_config(
        tmp_path,
        monkeypatch,
        """
[corpus]
name = "c"
source = "discovery_search"

[discovery]
organism_terms = ["Yarrowia"]
""".strip(),
    )

    ingester = DiscoverySearchIngester.from_config(str(config))

    assert ingester.credentials.crossref_mailto == "crossref@imperial.ac.uk"
    assert ingester.credentials.openalex_mailto == "openalex@imperial.ac.uk"
