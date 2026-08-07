"""Tests for the chunker, including section-labelled chunking.

`section_label` is the reason full-text ingestion is worth more than abstract
ingestion: it is what lets a citation name the Methods section a claim came
from. It reaches the database only if it survives every hop, so it is asserted
at each one here and in test_corpus_cache.py.
"""

from pipelines.processing.chunker import Chunk, Chunker
from pipelines.processing.normalizer import NormalizedDocument


def make_document(**overrides) -> NormalizedDocument:
    defaults = dict(
        document_id="pmid:1",
        source="pubmed",
        title="Engineering Yarrowia lipolytica",
        abstract="We raised the titre. The strain grew well.",
        mesh_terms=["Yarrowia"],
    )
    defaults.update(overrides)
    return NormalizedDocument(**defaults)


def test_abstract_mode_indexes_title_abstract_and_mesh() -> None:
    chunks = Chunker(mode="abstract").chunk_document(make_document())

    assert len(chunks) == 1
    assert chunks[0].chunk_type == "abstract"
    assert "Engineering Yarrowia lipolytica" in chunks[0].content
    assert "MeSH: Yarrowia" in chunks[0].content
    assert chunks[0].section_label is None


def test_document_with_no_text_produces_no_chunks() -> None:
    assert Chunker().chunk_document(make_document(title=None, abstract=None, mesh_terms=[])) == []


def test_long_text_is_split_with_overlap() -> None:
    sentences = " ".join(f"Sentence number {index} here." for index in range(100))
    chunks = Chunker(chunk_size=20, chunk_overlap=4).chunk_document(
        make_document(abstract=sentences, mesh_terms=[])
    )

    assert len(chunks) > 1
    assert [chunk.chunk_index for chunk in chunks] == list(range(len(chunks)))
    first_tail = chunks[0].content.split()[-4:]
    assert chunks[1].content.split()[:4] == first_tail


def test_chunk_sections_stamps_each_chunk_with_its_section() -> None:
    chunks = Chunker(chunk_size=1000).chunk_sections(
        "pmid:1",
        [("methods", "Strains were grown in YPD."), ("results", "Titre reached 50 g/L.")],
    )

    assert [chunk.section_label for chunk in chunks] == ["methods", "results"]
    assert [chunk.chunk_index for chunk in chunks] == [0, 1]
    assert chunks[0].chunk_type == "fulltext"


def test_a_chunk_never_straddles_two_sections() -> None:
    """A chunk spanning Methods and Results could not honestly carry either
    label, which would make section-level citation meaningless."""
    chunks = Chunker(chunk_size=1000).chunk_sections(
        "pmid:1", [("methods", "Grown in YPD."), ("results", "Titre 50 g/L.")]
    )

    assert all(
        ("YPD" in chunk.content) != ("Titre" in chunk.content) for chunk in chunks
    )


def test_chunk_index_stays_continuous_when_a_section_splits() -> None:
    long_methods = " ".join(f"Step {index} was performed." for index in range(60))
    chunks = Chunker(chunk_size=20, chunk_overlap=0).chunk_sections(
        "pmid:1", [("methods", long_methods), ("results", "Titre reached 50 g/L.")]
    )

    assert [chunk.chunk_index for chunk in chunks] == list(range(len(chunks)))
    assert chunks[-1].section_label == "results"
    assert len([chunk for chunk in chunks if chunk.section_label == "methods"]) > 1


def test_empty_sections_are_skipped() -> None:
    chunks = Chunker().chunk_sections(
        "pmid:1", [("methods", "   "), (None, ""), ("results", "Titre reached 50 g/L.")]
    )

    assert [chunk.section_label for chunk in chunks] == ["results"]


def test_chunk_defaults_to_no_section_label() -> None:
    assert Chunk(document_id="pmid:1", chunk_index=0, chunk_type="abstract", content="x").section_label is None
