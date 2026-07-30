"""Tests for S2 discovery: query building, source parsing, canonicalisation,
doc-type, relevance, retraction and the manifest CSV.

Offline. Payload fixtures are trimmed from real API responses. The live recall
measurement against the 706-DOI curated set is a separate script
(`pipelines/discovery/measure_recall.py`), not a unit test — it costs a few hundred
upstream requests.
"""

from __future__ import annotations

import httpx
import pytest

from pipelines.discovery import doctype, relevance, retraction
from pipelines.discovery.canonicalize import (
    Candidate,
    canonicalise,
    collapse_preprints,
    doi_class,
    flag_possible_duplicates,
    group_records,
    merge_records,
)
from pipelines.discovery.discover import ALL_SOURCES, discover, included_candidates
from pipelines.discovery.http import HttpSettings
from pipelines.discovery.manifest_csv import COLUMNS, NOT_REPORTED, write_manifest_csv
from pipelines.discovery.query_builder import (
    crossref_queries,
    europepmc_query,
    openalex_filter,
    pubmed_query,
)
from pipelines.discovery.sources import crossref, europepmc, openalex, pubmed
from pipelines.discovery.sources.base import (
    SourceQuery,
    SourceRecord,
    normalise_doi,
    normalise_title,
)

NO_THROTTLE = HttpSettings(backoff_base_s=0.0, throttle=False)

YARROWIA = SourceQuery(
    organism_terms=("Yarrowia lipolytica", "Candida lipolytica"),
    year_from=2016,
    year_to=2026,
)


@pytest.fixture(autouse=True)
def _no_throttle(monkeypatch):
    """Mocked transports must not pay the real per-host sleeps."""
    monkeypatch.setattr("pipelines.discovery.http._throttle", lambda _url: None)


def record(**overrides) -> SourceRecord:
    data = {"source": "pubmed", "doi": "10.1/a", "title": "A paper"}
    data.update(overrides)
    return SourceRecord(**data)


# ── DOI and title normalisation ───────────────────────────────────────────────


@pytest.mark.parametrize(
    "raw",
    [
        "10.1021/ACSOMEGA.6C03958",
        "https://doi.org/10.1021/acsomega.6c03958",
        "http://dx.doi.org/10.1021/acsomega.6c03958",
        "doi:10.1021/acsomega.6c03958",
        " 10.1021/acsomega.6c03958. ",
    ],
)
def test_every_source_spelling_of_a_doi_normalises_to_one_key(raw: str) -> None:
    """OpenAlex returns URLs, Crossref bare DOIs, PubMed XML sometimes a trailing
    period. Without this the same paper counts three times and the discovery gap
    looks closed when it is not."""
    assert normalise_doi(raw) == "10.1021/acsomega.6c03958"


@pytest.mark.parametrize("raw", ["", None, "not-a-doi", "12.345/x", "PMC123456"])
def test_non_dois_are_rejected_rather_than_stored(raw) -> None:
    assert normalise_doi(raw) is None


def test_title_keys_ignore_case_and_punctuation() -> None:
    assert normalise_title("Lipid Production in Y. lipolytica!") == normalise_title(
        "lipid production in y lipolytica"
    )


# ── Query building ────────────────────────────────────────────────────────────


def test_pubmed_query_ors_synonyms_and_bounds_the_date() -> None:
    built = pubmed_query(YARROWIA)
    assert '"Yarrowia lipolytica"[Title/Abstract]' in built
    assert '"Candida lipolytica"[Title/Abstract]' in built
    assert " OR " in built
    assert '"2016/01/01"[Date - Publication] : "2026/12/31"[Date - Publication]' in built


def test_organism_and_product_groups_are_anded_not_ored() -> None:
    """An organism-plus-product seed must be narrower than either alone."""
    built = pubmed_query(
        SourceQuery(organism_terms=("Yarrowia lipolytica",), product_terms=("hesperetin",))
    )
    assert built.count(" AND ") >= 1
    organism_group, product_group = built.split(" AND ")[0], built.split(" AND ")[1]
    assert "Yarrowia" in organism_group
    assert "hesperetin" in product_group


def test_europepmc_query_includes_preprints_by_default() -> None:
    """Europe PMC's PPR source is the only term-searchable route to bioRxiv."""
    assert "SRC:MED" not in europepmc_query(YARROWIA)
    assert "(SRC:MED OR SRC:PMC)" in europepmc_query(YARROWIA, include_preprints=False)


def test_openalex_filter_ors_phrases_in_one_request() -> None:
    built = openalex_filter(YARROWIA)
    assert "title_and_abstract.search:Yarrowia lipolytica|Candida lipolytica" in built
    assert "from_publication_date:2016-01-01" in built


def test_crossref_gets_one_query_per_term_because_it_cannot_or_phrases() -> None:
    assert crossref_queries(YARROWIA) == ["Yarrowia lipolytica", "Candida lipolytica"]


def test_a_query_with_no_terms_is_refused() -> None:
    with pytest.raises(ValueError):
        pubmed_query(SourceQuery())


# ── PubMed parsing ────────────────────────────────────────────────────────────

PUBMED_XML = """<?xml version="1.0"?>
<PubmedArticleSet>
  <PubmedArticle>
    <MedlineCitation>
      <PMID>42428839</PMID>
      <Article>
        <Journal><Title>ACS Omega</Title>
          <JournalIssue><PubDate><Year>2026</Year><Month>Jan</Month></PubDate></JournalIssue>
        </Journal>
        <ArticleTitle>Engineering of <i>Yarrowia lipolytica</i> for hesperetin</ArticleTitle>
        <Abstract>
          <AbstractText Label="RESULTS">Titre reached 488.7 mg/L.</AbstractText>
          <AbstractText Label="CONCLUSIONS">Y. lipolytica is suitable.</AbstractText>
        </Abstract>
        <PublicationTypeList>
          <PublicationType>Journal Article</PublicationType>
        </PublicationTypeList>
      </Article>
      <MeshHeadingList>
        <MeshHeading><DescriptorName>Yarrowia</DescriptorName></MeshHeading>
      </MeshHeadingList>
      <KeywordList><Keyword>metabolic engineering</Keyword></KeywordList>
    </MedlineCitation>
    <PubmedData>
      <ArticleIdList>
        <ArticleId IdType="pubmed">42428839</ArticleId>
        <ArticleId IdType="doi">10.1021/acsomega.6c03958</ArticleId>
        <ArticleId IdType="pmc">PMC13347637</ArticleId>
      </ArticleIdList>
    </PubmedData>
  </PubmedArticle>
  <PubmedArticle>
    <MedlineCitation>
      <PMID>111</PMID>
      <Article>
        <Journal><Title>J Retracted</Title></Journal>
        <ArticleTitle>A retracted Yarrowia study</ArticleTitle>
        <PublicationTypeList>
          <PublicationType>Journal Article</PublicationType>
          <PublicationType>Retracted Publication</PublicationType>
        </PublicationTypeList>
      </Article>
    </MedlineCitation>
  </PubmedArticle>
  <PubmedArticle>
    <MedlineCitation>
      <PMID>222</PMID>
      <Article>
        <Journal><Title>J Notices</Title></Journal>
        <ArticleTitle>Retraction of: A retracted Yarrowia study</ArticleTitle>
        <PublicationTypeList>
          <PublicationType>Retraction of Publication</PublicationType>
        </PublicationTypeList>
      </Article>
    </MedlineCitation>
  </PubmedArticle>
</PubmedArticleSet>
"""


REFERENCE_LIST_XML = """<?xml version="1.0"?>
<PubmedArticleSet>
  <PubmedArticle>
    <MedlineCitation>
      <PMID>39552760</PMID>
      <Article>
        <Journal><Title>Synthetic and systems biotechnology</Title>
          <JournalIssue><PubDate><Year>2025</Year></PubDate></JournalIssue>
        </Journal>
        <ArticleTitle>Systematic metabolic engineering of Yarrowia lipolytica</ArticleTitle>
        <ELocationID EIdType="doi">10.1016/j.synbio.2024.10.004</ELocationID>
        <PublicationTypeList><PublicationType>Journal Article</PublicationType></PublicationTypeList>
      </Article>
    </MedlineCitation>
    <PubmedData>
      <ArticleIdList>
        <ArticleId IdType="pubmed">39552760</ArticleId>
        <ArticleId IdType="doi">10.1016/j.synbio.2024.10.004</ArticleId>
        <ArticleId IdType="pmc">PMC11564786</ArticleId>
      </ArticleIdList>
      <ReferenceList>
        <Reference>
          <Citation>Some cited paper</Citation>
          <ArticleIdList>
            <ArticleId IdType="doi">10.1039/d3gc01661g</ArticleId>
            <ArticleId IdType="pubmed">11111111</ArticleId>
          </ArticleIdList>
        </Reference>
        <Reference>
          <Citation>Another cited paper</Citation>
          <ArticleIdList>
            <ArticleId IdType="doi">10.1105/tpc.002477</ArticleId>
          </ArticleIdList>
        </Reference>
      </ReferenceList>
    </PubmedData>
  </PubmedArticle>
</PubmedArticleSet>
"""


def test_identifiers_come_from_the_record_not_its_reference_list() -> None:
    """Regression: efetch embeds every reference with its own ArticleIdList, so a
    descendant search takes the last *cited* paper's DOI. That mislabelled most
    PMC-deposited records, and gold-recall measurement is what exposed it —
    the papers had been found, then filed under a DOI they do not own."""
    parsed = pubmed.parse_efetch_xml(REFERENCE_LIST_XML)

    assert len(parsed) == 1
    assert parsed[0].doi == "10.1016/j.synbio.2024.10.004"
    assert parsed[0].pmid == "39552760"
    assert parsed[0].pmc_id == "PMC11564786"


def test_a_doi_held_only_as_an_elocation_id_is_still_read() -> None:
    xml = REFERENCE_LIST_XML.replace(
        '<ArticleId IdType="doi">10.1016/j.synbio.2024.10.004</ArticleId>', ""
    )
    assert pubmed.parse_efetch_xml(xml)[0].doi == "10.1016/j.synbio.2024.10.004"


def test_pubmed_parsing_keeps_inline_markup_content() -> None:
    """Italicised organism names are the norm in titles; `element.text` alone would
    truncate the title at the first `<i>` and lose the term the filter looks for."""
    records = pubmed.parse_efetch_xml(PUBMED_XML)

    assert "Yarrowia lipolytica" in records[0].title
    assert records[0].doi == "10.1021/acsomega.6c03958"
    assert records[0].pmc_id == "PMC13347637"
    assert records[0].year == 2026


def test_structured_abstract_labels_are_kept() -> None:
    """Where a term appears is signal for the relevance pass."""
    records = pubmed.parse_efetch_xml(PUBMED_XML)
    assert "RESULTS:" in records[0].abstract
    assert "488.7 mg/L" in records[0].abstract


def test_a_retracted_paper_is_flagged_and_its_notice_is_dropped() -> None:
    """The notice is not a corpus candidate; the retracted paper is, flagged."""
    records = pubmed.parse_efetch_xml(PUBMED_XML)

    assert len(records) == 2
    retracted = [item for item in records if item.pmid == "111"]
    assert retracted and retracted[0].is_retracted
    assert all(item.pmid != "222" for item in records)


def test_pubmed_search_pages_through_efetch_batches(monkeypatch) -> None:
    monkeypatch.setattr(pubmed, "BATCH_SIZE", 2)
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        if "esearch" in str(request.url):
            return httpx.Response(200, json={"esearchresult": {"count": "3", "idlist": ["1", "2", "3"]}})
        return httpx.Response(200, text=PUBMED_XML)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        records = list(pubmed.search(YARROWIA, client=client, settings=NO_THROTTLE))

    assert len([call for call in calls if "efetch" in call]) == 2
    assert len(records) == 4  # two batches x two keepable records


# ── Europe PMC parsing ────────────────────────────────────────────────────────


def test_europepmc_strips_escaped_markup_from_titles() -> None:
    parsed = europepmc.parse_result(
        {
            "id": "42338746",
            "source": "MED",
            "pmid": "42338746",
            "doi": "10.1093/nargab/lqag064",
            "title": "Genome of &lt;i&gt;Yarrowia lipolytica&lt;/i&gt;.",
            "abstractText": "We assembled <b>MATA</b> strains.",
            "pubYear": "2026",
            "isOpenAccess": "Y",
            "license": "cc by-nc",
        }
    )

    assert parsed.title == "Genome of Yarrowia lipolytica."
    assert parsed.abstract == "We assembled MATA strains."
    assert parsed.oa_status == "open"


def test_a_preprint_source_marks_the_record_as_a_preprint() -> None:
    assert europepmc.parse_result({"id": "PPR1", "source": "PPR", "doi": "10.1101/x"}).is_preprint


def test_a_comment_correction_retraction_is_detected() -> None:
    parsed = europepmc.parse_result(
        {
            "id": "1",
            "source": "MED",
            "doi": "10.1/x",
            "commentCorrectionList": {
                "commentCorrection": [{"type": "Retraction in", "id": "999"}]
            },
        }
    )
    assert parsed.is_retracted
    assert "Retraction in" in parsed.retraction_note


def test_europepmc_stops_when_the_cursor_repeats() -> None:
    """A repeated cursorMark is Europe PMC's end-of-results; without the check the
    client re-requests the last page forever."""
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(
            200,
            json={
                "resultList": {"result": [{"id": "1", "source": "MED", "doi": "10.1/x"}]},
                "nextCursorMark": "SAME",
            },
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        records = list(europepmc.search(YARROWIA, client=client, settings=NO_THROTTLE))

    assert len(calls) == 2
    assert len(records) == 2


def test_the_per_source_cap_is_honoured() -> None:
    query = SourceQuery(organism_terms=("Yarrowia lipolytica",), max_records_per_source=3)

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "resultList": {
                    "result": [
                        {"id": str(index), "source": "MED", "doi": f"10.1/{index}"}
                        for index in range(10)
                    ]
                },
                "nextCursorMark": "next",
            },
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        assert len(list(europepmc.search(query, client=client, settings=NO_THROTTLE))) == 3


# ── Crossref and OpenAlex parsing ─────────────────────────────────────────────


def test_crossref_jats_abstracts_are_flattened() -> None:
    parsed = crossref.parse_item(
        {
            "DOI": "10.1002/bbb.2687",
            "title": ["Lipid production"],
            "abstract": "<jats:p>Yarrowia lipolytica was grown.</jats:p>",
            "container-title": ["Biofuels, Bioproducts and Biorefining"],
            "publisher": "Wiley",
            "type": "journal-article",
            "issued": {"date-parts": [[2024, 5, 1]]},
        }
    )

    assert parsed.abstract == "Yarrowia lipolytica was grown."
    assert parsed.journal == "Biofuels, Bioproducts and Biorefining"
    assert parsed.year == 2024


def test_crossref_update_to_flags_a_retraction() -> None:
    """Reaches the non-PubMed journals where a quarter of this corpus lives."""
    parsed = crossref.parse_item(
        {
            "DOI": "10.1/x",
            "update-to": [{"type": "retraction", "DOI": "10.1/notice"}],
        }
    )
    assert parsed.is_retracted


def test_crossref_stops_paging_a_term_whose_pages_stop_mentioning_it() -> None:
    """The measured case: `Candida lipolytica` reports 27,471 Crossref results
    because the index scores the words separately. Without an early stop, one noisy
    synonym consumes the whole source budget and later terms get nothing."""
    pages: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        pages.append(1)
        return httpx.Response(
            200,
            json={
                "message": {
                    "total-results": 27471,
                    "items": [
                        {"DOI": f"10.1/noise{index}", "title": ["Something unrelated entirely"]}
                        for index in range(200)
                    ],
                }
            },
        )

    query = SourceQuery(organism_terms=("Candida lipolytica",), max_records_per_source=9000)
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        records = list(crossref.search(query, client=client, settings=NO_THROTTLE))

    assert len(pages) == crossref.MAX_BARREN_PAGES
    assert len(records) == 200 * crossref.MAX_BARREN_PAGES


def test_a_noisy_synonym_cannot_starve_the_other_terms() -> None:
    seen_terms: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        term = dict(request.url.params).get("query.bibliographic", "")
        seen_terms.append(term)
        return httpx.Response(
            200,
            json={
                "message": {
                    "total-results": 50000,
                    # Mentions the term, so the barren-page stop does not fire; only
                    # the per-term budget can end this walk.
                    "items": [
                        {"DOI": f"10.1/{term[:4]}{index}", "title": [f"About {term}"]}
                        for index in range(200)
                    ],
                }
            },
        )

    query = SourceQuery(
        organism_terms=("Yarrowia lipolytica", "Candida lipolytica"), max_records_per_source=4000
    )
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        list(crossref.search(query, client=client, settings=NO_THROTTLE))

    assert set(seen_terms) == {"Yarrowia lipolytica", "Candida lipolytica"}


def test_crossref_posted_content_is_a_preprint() -> None:
    assert crossref.parse_item({"DOI": "10.1101/x", "type": "posted-content"}).is_preprint


def test_openalex_abstracts_are_rebuilt_from_the_inverted_index() -> None:
    text = openalex.reconstruct_abstract({"Yarrowia": [0, 4], "lipolytica": [1], "grows": [2], "well": [3]})
    assert text == "Yarrowia lipolytica grows well Yarrowia"


def test_a_missing_inverted_index_is_not_an_empty_abstract() -> None:
    assert openalex.reconstruct_abstract(None) is None
    assert openalex.reconstruct_abstract({}) is None


def test_openalex_carries_retraction_and_oa_status() -> None:
    parsed = openalex.parse_work(
        {
            "doi": "https://doi.org/10.1038/nbt.3763",
            "title": "Lipid production",
            "publication_year": 2017,
            "is_retracted": True,
            "open_access": {"oa_status": "closed"},
            "ids": {"pmid": "https://pubmed.ncbi.nlm.nih.gov/28092657"},
            "primary_location": {"source": {"display_name": "Nature Biotechnology"}},
        }
    )

    assert parsed.doi == "10.1038/nbt.3763"
    assert parsed.pmid == "28092657"
    assert parsed.is_retracted
    assert parsed.oa_status == "closed"
    assert parsed.journal == "Nature Biotechnology"


# ── Canonicalisation ──────────────────────────────────────────────────────────


def test_the_same_paper_from_four_sources_becomes_one_candidate() -> None:
    records = [
        record(source="pubmed", doi="10.1/x", pmid="1", abstract="From PubMed", journal="ACS Omega"),
        record(source="crossref", doi="https://doi.org/10.1/X", publisher="ACS"),
        record(source="openalex", doi="10.1/x", oa_status="green"),
        record(source="europepmc", doi="10.1/x", pmc_id="PMC1"),
    ]

    candidates = canonicalise(records)

    assert len(candidates) == 1
    merged = candidates[0]
    assert merged.found_in == ("pubmed", "europepmc", "crossref", "openalex")
    assert merged.abstract == "From PubMed"  # curated source wins
    assert merged.publisher == "ACS"  # only Crossref had it
    assert merged.oa_status == "green"
    assert merged.pmc_id == "PMC1"


def test_ten_duplicate_curations_of_one_doi_collapse_to_one_row() -> None:
    """The measured shape of the curated Excel: 723 rows over 706 unique DOIs, the
    difference being 10 accidental re-curations."""
    records = [record(source="crossref", doi="10.1/dup", title=f"Curation {index}") for index in range(11)]
    assert len(canonicalise(records)) == 1


def test_records_are_joined_transitively_through_a_shared_identifier() -> None:
    """Crossref may give only a DOI and PubMed only a PMID; a third record carrying
    both is what proves they are the same paper."""
    groups = group_records(
        [
            record(source="crossref", doi="10.1/x", pmid=None),
            record(source="pubmed", doi=None, pmid="555", title="Different title"),
            record(source="europepmc", doi="10.1/x", pmid="555"),
        ]
    )

    assert len(groups) == 1
    assert len(groups[0]) == 3


def test_records_with_no_identifier_at_all_stay_separate() -> None:
    groups = group_records([record(doi=None, title=None), record(doi=None, title=None)])
    assert len(groups) == 2


def test_a_shared_title_never_merges_two_records() -> None:
    """Owner decision, 2026-07-30: ingesting a preprint and its published version
    twice is strictly better than merging two distinct works once. A title is a
    string a publisher chose, so it cannot be an identity."""
    groups = group_records(
        [
            record(source="crossref", doi=None, title="Lipid Production in Yarrowia!", year=2020),
            record(source="openalex", doi=None, title="lipid production in yarrowia", year=2020),
        ]
    )
    assert len(groups) == 2


def test_four_peer_review_reports_stay_four_candidates() -> None:
    """Measured false merge: `Review for "..."` titles collapsed four distinct review
    objects into one row."""
    reports = [
        record(source="crossref", doi=f"10.1002/btpr.3201/v{version}/review{index}",
               title='Review for "Metabolic engineering of Yarrowia lipolytica"')
        for version in (1, 2)
        for index in (1, 2)
    ]
    assert len(canonicalise(reports)) == 4


def test_two_book_front_matter_sections_stay_two_candidates() -> None:
    """Measured false merge: both were titled "Front Matter"."""
    sections = [
        record(source="crossref", doi="10.1016/b978-0-443-22092-0.00300-5", title="Front Matter"),
        record(source="crossref", doi="10.1016/b978-0-443-22092-0.00301-7", title="Front Matter"),
    ]
    assert len(canonicalise(sections)) == 2


def test_a_paper_and_its_data_deposit_stay_separate() -> None:
    """Measured harm: merging pulled a figshare/Zenodo record into the paper's row,
    whose `dataset` type then reclassified the *paper* as `other` and dropped it
    from acquisition — and the row could end up carrying the deposit's DOI."""
    paper = record(
        source="crossref",
        doi="10.1186/s12934-026-02986-z",
        title="Phenotyping transcription factors-related genotypes",
        types=("journal-article",),
    )
    deposit = record(
        source="openalex",
        doi="10.6084/m9.figshare.c.8443127",
        title="Phenotyping transcription factors-related genotypes",
        types=("dataset",),
    )

    candidates = canonicalise([paper, deposit])
    assert len(candidates) == 2

    by_doi = {candidate.doi: candidate for candidate in candidates}
    assert by_doi["10.1186/s12934-026-02986-z"].types == ("journal-article",)
    assert doctype.classify(types=by_doi["10.1186/s12934-026-02986-z"].types).doc_type == doctype.PRIMARY
    assert doctype.classify(types=by_doi["10.6084/m9.figshare.c.8443127"].types).doc_type == doctype.OTHER


def test_a_dataset_doi_never_becomes_a_rows_identity() -> None:
    """If a deposit and a paper *do* share a strong identifier, the citable DOI wins."""
    merged = merge_records(
        [
            record(source="openalex", doi="10.5281/zenodo.19188735", pmid="123", title="A paper"),
            record(source="crossref", doi="10.1016/j.biortech.2025.133540", pmid="123", title="A paper"),
        ]
    )
    assert merged.doi == "10.1016/j.biortech.2025.133540"


def test_pmcid_is_a_strong_identifier() -> None:
    groups = group_records(
        [
            record(source="pubmed", doi=None, pmid=None, pmc_id="PMC13347637", title="A"),
            record(source="europepmc", doi=None, pmid=None, pmc_id="PMC13347637", title="B"),
        ]
    )
    assert len(groups) == 1


def test_possible_duplicates_are_flagged_in_both_directions_not_merged() -> None:
    """The cross-year preprint pairs the old title rule could not catch: recorded as
    a suspicion for a human, with the evidence, and left as two rows."""
    published = Candidate(
        doi="10.1016/j.synbio.2026.01.017",
        title="Integrated protein and metabolic engineering enable lupeol production",
        year=2026,
        doc_type="primary",
    )
    preprint = Candidate(
        doi="10.2139/ssrn.5675827",
        title="Integrated protein and metabolic engineering enable lupeol production",
        year=2025,
        doc_type="primary",
        is_preprint=True,
    )

    flagged = flag_possible_duplicates([published, preprint])

    assert flagged == 2
    assert published.possible_duplicate_of == ("10.2139/ssrn.5675827",)
    assert preprint.possible_duplicate_of == ("10.1016/j.synbio.2026.01.017",)
    assert "years [2025, 2026]" in published.duplicate_evidence


def test_generic_titles_are_not_flagged_as_duplicates() -> None:
    """Front matter and issue information collide by the dozen; a flag on them would
    train a curator to ignore the flag."""
    rows = [
        Candidate(doi="10.1/a", title="Front Matter", doc_type="primary"),
        Candidate(doi="10.1/b", title="Front Matter", doc_type="primary"),
        Candidate(doi="10.1/c", title="Editorial Board and Table of Contents", doc_type="primary"),
        Candidate(doi="10.1/d", title="Editorial Board and Table of Contents", doc_type="primary"),
    ]
    assert flag_possible_duplicates(rows) == 0


def test_candidates_already_classified_other_are_not_flagged() -> None:
    rows = [
        Candidate(doi="10.1/a", title="A sufficiently long shared review title here", doc_type="other"),
        Candidate(doi="10.1/b", title="A sufficiently long shared review title here", doc_type="other"),
    ]
    assert flag_possible_duplicates(rows) == 0


def test_a_retraction_from_any_source_survives_the_merge() -> None:
    """A false negative here puts a retracted paper in the datasheet."""
    merged = merge_records(
        [
            record(source="pubmed", is_retracted=False),
            record(source="openalex", is_retracted=True, retraction_note="OpenAlex is_retracted"),
        ]
    )
    assert merged.is_retracted
    assert merged.retraction_note == "OpenAlex is_retracted"


def test_a_paper_is_only_a_preprint_if_every_source_says_so() -> None:
    merged = merge_records(
        [
            record(source="europepmc", is_preprint=True, doi="10.1101/x"),
            record(source="crossref", is_preprint=False, doi="10.1101/x"),
        ]
    )
    assert merged.is_preprint is False


def test_a_preprint_is_merged_into_its_version_of_record() -> None:
    """Otherwise the same paper is acquired twice and counted twice."""
    preprint = Candidate(
        doi="10.1101/2020.01.01.000001",
        title="Preprint",
        is_preprint=True,
        found_in=("europepmc",),
        abstract="Yarrowia lipolytica grows",
    )
    published = Candidate(doi="10.1016/j.x.2020.01", title="Published", found_in=("crossref",))

    survivors = collapse_preprints(
        [preprint, published],
        resolve_version_of_record=lambda doi: {"published_doi": "10.1016/j.x.2020.01"},
    )

    assert len(survivors) == 1
    assert survivors[0].doi == "10.1016/j.x.2020.01"
    assert survivors[0].preprint_doi == "10.1101/2020.01.01.000001"
    assert set(survivors[0].found_in) == {"crossref", "europepmc"}


def test_a_preprint_whose_version_of_record_was_not_found_is_kept() -> None:
    """Dropping it would lose the paper entirely; the link is recorded so a refresh
    can promote it later."""
    preprint = Candidate(doi="10.1101/x", is_preprint=True)

    survivors = collapse_preprints(
        [preprint], resolve_version_of_record=lambda doi: {"published_doi": "10.1016/unknown"}
    )

    assert len(survivors) == 1
    assert survivors[0].version_of_record_doi == "10.1016/unknown"


def test_a_preprint_with_no_published_version_is_kept_as_itself() -> None:
    survivors = collapse_preprints(
        [Candidate(doi="10.1101/x", is_preprint=True)], resolve_version_of_record=lambda doi: None
    )
    assert len(survivors) == 1
    assert survivors[0].is_preprint


# ── Doc type ──────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("types", "title", "expected"),
    [
        (("Journal Article",), "Engineering Yarrowia for lipids", doctype.PRIMARY),
        (("Review",), "Yarrowia lipolytica", doctype.REVIEW),
        ((), "A review of Yarrowia lipolytica engineering", doctype.REVIEW),
        ((), "Recent advances in Yarrowia lipolytica", doctype.REVIEW),
        ((), "Systematic review of lipid pathways", doctype.REVIEW),
        (("Published Erratum",), "Erratum", doctype.OTHER),
        (("editorial",), "Editorial", doctype.OTHER),
    ],
)
def test_doc_type_classification(types, title, expected) -> None:
    assert doctype.classify(types=types, title=title).doc_type == expected


def test_reviews_deposited_as_plain_journal_articles_are_still_caught() -> None:
    """Crossref types 702/704 are routinely deposited as `journal-article`, so a
    type check alone misses a large share of reviews — and a review's numbers are
    someone else's results."""
    verdict = doctype.classify(
        types=("journal-article",),
        title="Yarrowia lipolytica as a cell factory: a review",
        abstract="This review summarises progress.",
    )
    assert verdict.is_review
    assert verdict.reason


def test_every_doc_type_verdict_carries_a_reason() -> None:
    assert doctype.classify(types=("Journal Article",), title="X").reason


# ── Relevance ─────────────────────────────────────────────────────────────────

ORGANISM = ("Yarrowia lipolytica",)


def test_a_title_hit_means_the_paper_studies_the_seed() -> None:
    verdict = relevance.judge(
        title="Lipid production in Yarrowia lipolytica", abstract=None, organism_terms=ORGANISM
    )
    assert verdict.relevance == relevance.STUDIES


def test_an_abbreviated_genus_counts_as_the_organism() -> None:
    """Papers write `Y. lipolytica` after first use; without this an abstract naming
    the organism seven times scores as a single passing mention."""
    verdict = relevance.judge(
        title="Engineering a yeast", abstract="Y. lipolytica was grown. Y. lipolytica produced lipids.",
        organism_terms=ORGANISM,
    )
    assert verdict.relevance == relevance.STUDIES
    assert verdict.abstract_hits >= 2


def test_a_single_peripheral_mention_is_only_a_mention() -> None:
    verdict = relevance.judge(
        title="Lipase-catalysed esterification",
        abstract="A commercial lipase from Yarrowia lipolytica was used as a reagent.",
        organism_terms=ORGANISM,
    )
    assert verdict.relevance == relevance.MENTIONS


def test_a_product_term_promotes_a_single_mention() -> None:
    verdict = relevance.judge(
        title="Flavonoid biosynthesis in yeast",
        abstract="Yarrowia lipolytica was engineered; hesperetin titre reached 488 mg/L.",
        organism_terms=ORGANISM,
        product_terms=("hesperetin",),
    )
    assert verdict.relevance == relevance.STUDIES


def test_crossref_noise_is_rejected() -> None:
    """The concrete case: a bibliographic query for the organism returned a Russian
    history-of-science article in its first page of hits."""
    verdict = relevance.judge(
        title="The complex response of yeast to stress",
        abstract="We studied Saccharomyces cerevisiae under osmotic stress.",
        organism_terms=ORGANISM,
    )
    assert verdict.relevance == relevance.OFF_TOPIC


def test_no_abstract_and_no_title_hit_is_unknown_not_off_topic() -> None:
    """Calling this off-topic silently drops the paywalled tail — the literature
    multi-source discovery exists to reach."""
    verdict = relevance.judge(title="Some other title", abstract=None, organism_terms=ORGANISM)

    assert verdict.relevance == relevance.UNKNOWN
    assert verdict.needs_adjudication
    assert relevance.is_included(verdict.relevance) is True


def test_mesh_headings_carry_the_verdict_when_there_is_no_abstract() -> None:
    verdict = relevance.judge(
        title="Untitled", abstract=None, organism_terms=ORGANISM, mesh_terms=("Yarrowia lipolytica",)
    )
    assert verdict.relevance == relevance.STUDIES


def test_a_product_term_cannot_rescue_an_off_topic_paper() -> None:
    """A paper that never mentions the organism is not about the organism."""
    verdict = relevance.judge(
        title="Hesperetin from citrus peel",
        abstract="Hesperetin was extracted from citrus. Hesperetin yield was 3%.",
        organism_terms=ORGANISM,
        product_terms=("hesperetin",),
    )
    assert verdict.relevance == relevance.OFF_TOPIC


def test_every_relevance_verdict_carries_a_reason() -> None:
    for kwargs in (
        {"title": "Yarrowia lipolytica", "abstract": None},
        {"title": "x", "abstract": "Yarrowia lipolytica once"},
        {"title": "x", "abstract": "nothing relevant"},
        {"title": "x", "abstract": None},
    ):
        assert relevance.judge(organism_terms=ORGANISM, **kwargs).reason


def test_included_relevance_levels() -> None:
    assert relevance.is_included(relevance.STUDIES)
    assert relevance.is_included(relevance.UNKNOWN)
    assert not relevance.is_included(relevance.MENTIONS)
    assert relevance.is_included(relevance.MENTIONS, include_mentions=True)
    assert not relevance.is_included(relevance.OFF_TOPIC, include_mentions=True)


# ── Retraction ────────────────────────────────────────────────────────────────


def test_metadata_retraction_needs_no_request() -> None:
    verdict = retraction.from_metadata(types=("Journal Article", "Retracted Publication"))
    assert verdict.is_retracted
    assert "Retracted Publication" in verdict.note


def test_a_clean_paper_is_not_flagged() -> None:
    assert retraction.from_metadata(types=("Journal Article",)).is_retracted is False


def test_notice_search_confirms_per_doi_before_flagging() -> None:
    """A batched search cannot say which DOI a notice belongs to, so a hit is
    re-checked individually — flagging the whole batch would libel nine papers."""
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        calls.append(url)
        if "10.1%2Fbad" in url or "10.1/bad" in url:
            return httpx.Response(200, json={"esearchresult": {"idlist": ["999"]}})
        if "OR" in url:  # the batch query
            return httpx.Response(200, json={"esearchresult": {"idlist": ["999"]}})
        return httpx.Response(200, json={"esearchresult": {"idlist": []}})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        found = retraction.search_notices(
            ["10.1/good", "10.1/bad"], client=client, settings=NO_THROTTLE
        )

    assert found == {"10.1/bad": "PubMed retraction notice PMID 999"}


def test_no_notice_search_happens_for_an_empty_list() -> None:
    assert retraction.search_notices([]) == {}


# ── Orchestration ─────────────────────────────────────────────────────────────


def discovery_transport(monkeypatch, *, failing: set[str] = frozenset()) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "eutils" in url and "esearch" in url:
            if "pubmed" in failing:
                return httpx.Response(500)
            return httpx.Response(200, json={"esearchresult": {"count": "1", "idlist": ["1"]}})
        if "eutils" in url and "efetch" in url:
            return httpx.Response(200, text=PUBMED_XML)
        if "europepmc" in url:
            if "europepmc" in failing:
                return httpx.Response(503)
            return httpx.Response(
                200,
                json={
                    "resultList": {
                        "result": [
                            {
                                "id": "1",
                                "source": "MED",
                                "doi": "10.1021/acsomega.6c03958",
                                "title": "Engineering of Yarrowia lipolytica for hesperetin",
                                "abstractText": "Yarrowia lipolytica produced hesperetin.",
                                "pubYear": "2026",
                            }
                        ]
                    }
                },
            )
        if "crossref" in url:
            return httpx.Response(
                200,
                json={
                    "message": {
                        # Real Crossref always reports this; the client uses it to know
                        # when it has walked the whole result set.
                        "total-results": 1,
                        "items": [
                            {
                                "DOI": "10.1002/bbb.2687",
                                "title": ["A review of Yarrowia lipolytica biorefineries"],
                                "abstract": "<jats:p>Yarrowia lipolytica reviewed.</jats:p>",
                                "type": "journal-article",
                                "publisher": "Wiley",
                                "issued": {"date-parts": [[2024]]},
                            }
                        ]
                    }
                },
            )
        if "openalex" in url:
            return httpx.Response(
                200,
                json={
                    "results": [
                        {
                            "doi": "https://doi.org/10.1002/bbb.2687",
                            "title": "A review of Yarrowia lipolytica biorefineries",
                            "publication_year": 2024,
                            "open_access": {"oa_status": "hybrid"},
                        }
                    ],
                    "meta": {"next_cursor": None},
                },
            )
        return httpx.Response(404, text=f"unrouted {url}")

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_discovery_merges_sources_and_reports_a_manifest(monkeypatch) -> None:
    with discovery_transport(monkeypatch) as client:
        result = discover(YARROWIA, client=client, settings=NO_THROTTLE)

    summary = result.summary()
    # pubmed 2 (one retracted), europepmc 1, openalex 1, crossref 2 — Crossref
    # issues one query per term because it cannot OR phrases.
    assert result.source_record_counts == {
        "pubmed": 2,
        "europepmc": 1,
        "crossref": 2,
        "openalex": 1,
    }
    assert summary["total_source_records"] == 6
    assert set(result.source_record_counts) == set(ALL_SOURCES)
    # Three papers: the ACS one (pubmed + europepmc), the review (crossref x2 +
    # openalex), and the retracted one.
    assert summary["candidates"] == 3
    assert summary["duplicates_collapsed"] == 3
    assert summary["queries"]["pubmed"]


def test_one_dead_source_does_not_lose_the_others(monkeypatch) -> None:
    """Partial coverage is reported, never silently treated as 'no results' — a
    missing source changes what a recall number means."""
    with discovery_transport(monkeypatch, failing={"pubmed"}) as client:
        result = discover(YARROWIA, client=client, settings=NO_THROTTLE)

    assert "pubmed" in result.source_errors
    assert result.source_record_counts["pubmed"] == 0
    assert result.candidates  # the other three still produced candidates


def test_reviews_and_retracted_papers_are_flagged_but_kept_in_the_manifest(monkeypatch) -> None:
    with discovery_transport(monkeypatch) as client:
        result = discover(YARROWIA, client=client, settings=NO_THROTTLE)

    reviews = [candidate for candidate in result.candidates if candidate.is_review]
    retracted = [candidate for candidate in result.candidates if candidate.is_retracted]
    assert reviews and retracted

    included = included_candidates(result)
    assert all(not candidate.is_review for candidate in included)
    assert all(not candidate.is_retracted for candidate in included)


def test_discovery_refuses_a_seedless_query() -> None:
    with pytest.raises(ValueError):
        discover(SourceQuery())


# ── Manifest CSV ──────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("doi", "expected"),
    [
        ("10.1186/s12934-026-02986-z", "journal"),
        ("10.1101/2025.08.23.670849", "preprint"),
        ("10.2139/ssrn.5391051", "preprint"),
        ("10.6084/m9.figshare.c.8443127", "dataset"),
        ("10.5281/zenodo.18186940", "dataset"),
        ("10.22028/d291-48099", "repository"),
        (None, "journal"),
    ],
)
def test_doi_classification(doi, expected) -> None:
    assert doi_class(doi) == expected


def test_manifest_csv_carries_the_duplicate_suspicion() -> None:
    candidate = Candidate(
        doi="10.1016/j.synbio.2026.01.017",
        title="Integrated protein and metabolic engineering enable lupeol production",
        possible_duplicate_of=("10.2139/ssrn.5675827",),
        duplicate_evidence="same normalised title as 10.2139/ssrn.5675827 (years [2025, 2026])",
    )

    csv_text = write_manifest_csv([candidate])

    assert "possible_duplicate_of" in csv_text.splitlines()[0]
    assert "10.2139/ssrn.5675827" in csv_text
    assert "years [2025, 2026]" in csv_text


def test_manifest_csv_records_the_decision_and_its_reason() -> None:
    candidate = Candidate(
        doi="10.1/x",
        title="Lipid production in Yarrowia lipolytica",
        found_in=("crossref",),
        relevance="mentions",
        relevance_reason="single abstract mention, not in title",
        doc_type="primary",
    )

    csv_text = write_manifest_csv([candidate], included_dois=set())
    header, row = csv_text.splitlines()[:2]

    assert header.split(",") == list(COLUMNS)
    assert "single abstract mention" in row
    assert ",no," in row  # included = no


def test_empty_cells_use_the_curators_convention() -> None:
    csv_text = write_manifest_csv([Candidate(doi="10.1/x")])
    assert NOT_REPORTED in csv_text


def test_multi_valued_cells_are_joined_readably() -> None:
    csv_text = write_manifest_csv(
        [Candidate(doi="10.1/x", found_in=("pubmed", "crossref"))]
    )
    assert "pubmed; crossref" in csv_text
