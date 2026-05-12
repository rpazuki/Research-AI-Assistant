from pipelines.ingestion.pmc_fulltext import _extract_article_text, _extract_metadata


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
