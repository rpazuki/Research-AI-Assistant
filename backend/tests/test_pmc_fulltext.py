from pipelines.corpus_cache import CorpusCache, CorpusManifest
from pipelines.ingestion.pmc_fulltext import PMC_OA_BASE, PMCFullTextIngester, _extract_article_text, _extract_metadata


SAMPLE_XML = """<?xml version='1.0' encoding='UTF-8'?>
<OAI-PMH>
  <GetRecord>
    <record>
      <metadata>
        <article>
          <front>
            <article-meta>
              <article-id pub-id-type="pmid">123456</article-id>
              <article-id pub-id-type="doi">10.1000/example</article-id>
              <title-group>
                <article-title>Engineering Yarrowia lipolytica for lipid production</article-title>
              </title-group>
              <abstract>
                <p>Abstract summary.</p>
              </abstract>
              <kwd-group>
                <kwd>lipid production</kwd>
                <kwd>Yarrowia lipolytica</kwd>
              </kwd-group>
              <permissions>
                <license>
                  <license-p>CC-BY</license-p>
                </license>
              </permissions>
            </article-meta>
          </front>
          <body>
            <sec>
              <title>Introduction</title>
              <p>Intro paragraph.</p>
            </sec>
            <sec>
              <title>Methods</title>
              <p>Method paragraph.</p>
            </sec>
          </body>
        </article>
      </metadata>
    </record>
  </GetRecord>
</OAI-PMH>
"""


def test_extract_metadata_from_pmc_xml() -> None:
    metadata = _extract_metadata(SAMPLE_XML)

    assert metadata["title"] == "Engineering Yarrowia lipolytica for lipid production"
    assert metadata["abstract"] == "Abstract summary."
    assert metadata["doi"] == "10.1000/example"
    assert metadata["pmid"] == "123456"
    assert metadata["keywords"] == ["lipid production", "Yarrowia lipolytica"]
    assert metadata["license"] == "CC-BY"


def test_extract_article_text_formats_sections() -> None:
    text = _extract_article_text(SAMPLE_XML)

    assert "Introduction" in text
    assert "Intro paragraph." in text
    assert "Methods" in text
    assert "Method paragraph." in text


def test_oai_url_uses_current_pmc_endpoint() -> None:
    url = PMCFullTextIngester._oai_url("PMC41812577")

    assert url.startswith(PMC_OA_BASE)
    assert "identifier=oai:pubmedcentral.nih.gov:41812577" in url
    assert "metadataPrefix=pmc" in url


def test_fetch_xml_follows_redirects(monkeypatch) -> None:
    created_clients: list[dict] = []

    class FakeResponse:
        status_code = 200
        text = "<xml/>"
        url = "https://pmc.ncbi.nlm.nih.gov/api/oai/v1/mh/?verb=GetRecord"

        def raise_for_status(self) -> None:
            return None

    class FakeClient:
        def __init__(self, **kwargs) -> None:
            created_clients.append(kwargs)

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb) -> None:
            return None

        def get(self, url: str, params=None) -> FakeResponse:
            return FakeResponse()

    monkeypatch.setattr("pipelines.ingestion.pmc_fulltext.httpx.Client", FakeClient)

    xml_text, final_url = PMCFullTextIngester._fetch_xml("https://old.example/oai")

    assert xml_text == "<xml/>"
    assert final_url.startswith("https://pmc.ncbi.nlm.nih.gov")
    assert created_clients[0]["follow_redirects"] is True


def test_resolve_to_pmcid_accepts_direct_pmcid(monkeypatch) -> None:
    calls: list[tuple[str, str | None]] = []

    def fake_convert(identifier: str, idtype: str | None = None) -> dict | None:
        calls.append((identifier, idtype))
        return {"pmcid": "PMC123", "pmid": "456", "requested-id": identifier}

    monkeypatch.setattr(PMCFullTextIngester, "_convert_identifier", fake_convert)

    resolved = PMCFullTextIngester._resolve_to_pmcid("PMC123")

    assert resolved is not None
    assert resolved["pmcid"] == "PMC123"
    assert calls == []


def test_resolve_to_pmcid_converts_pubmed_id(monkeypatch) -> None:
    calls: list[tuple[str, str | None]] = []

    def fake_convert(identifier: str, idtype: str | None = None) -> dict | None:
        calls.append((identifier, idtype))
        return {"pmcid": "PMC9999999", "pmid": "41812577", "requested-id": identifier}

    monkeypatch.setattr(PMCFullTextIngester, "_convert_identifier", fake_convert)

    resolved = PMCFullTextIngester._resolve_to_pmcid("41812577")

    assert resolved is not None
    assert resolved["pmcid"] == "PMC9999999"
    assert calls == [("41812577", None)]


def test_fetch_one_records_error_when_identifier_is_not_in_pmc(tmp_path, monkeypatch) -> None:
    manifest = CorpusManifest(
        schema_version="1.0",
        corpus_name="test-corpus",
        run_id="run",
        created_at="2026-05-30T12:00:00Z",
        source="pmc_fulltext",
    )
    cache = CorpusCache.create(base_dir=tmp_path, manifest=manifest)
    ingester = PMCFullTextIngester(["41812577"], cache=cache)
    monkeypatch.setattr(PMCFullTextIngester, "_resolve_to_pmcid", classmethod(lambda _cls, _identifier: None))

    doc = ingester._fetch_one("41812577")

    errors = cache.read_jsonl("normalized/documents.errors.jsonl")
    assert doc is None
    assert errors[0]["identifier"] == "41812577"
    assert errors[0]["error_type"] == "no_pmc_record"


def test_fetch_one_records_oai_400_as_unavailable(tmp_path, monkeypatch) -> None:
    manifest = CorpusManifest(
        schema_version="1.0",
        corpus_name="test-corpus",
        run_id="run",
        created_at="2026-05-30T12:00:00Z",
        source="pmc_fulltext",
    )
    cache = CorpusCache.create(base_dir=tmp_path, manifest=manifest)
    ingester = PMCFullTextIngester(["PMC13179995"], cache=cache)

    class FakeRequest:
        pass

    class FakeResponse:
        status_code = 400
        text = "<error code='cannotDisseminateFormat'>full text unavailable</error>"
        request = FakeRequest()

    def fake_fetch_xml(_url: str) -> tuple[str, str]:
        raise __import__("httpx").HTTPStatusError("400 Bad Request", request=FakeRequest(), response=FakeResponse())

    monkeypatch.setattr(PMCFullTextIngester, "_fetch_xml", staticmethod(fake_fetch_xml))

    doc = ingester._fetch_one("PMC13179995")

    errors = cache.read_jsonl("normalized/documents.errors.jsonl")
    assert doc is None
    assert errors[0]["pmc_id"] == "PMC13179995"
    assert errors[0]["error_type"] == "pmc_oai_fulltext_unavailable"
