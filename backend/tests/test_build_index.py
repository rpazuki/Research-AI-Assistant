from pipelines.indexing.build_index import validate_index_embedding


class DummyEmbedder:
    def __init__(self, model_name: str, dimensions: int) -> None:
        self.model_name = model_name
        self.dimensions = dimensions


def test_validate_index_embedding_accepts_pubmedbert_dimensions() -> None:
    validate_index_embedding(DummyEmbedder("pubmedbert", 768))


def test_validate_index_embedding_rejects_non_matching_dimensions() -> None:
    try:
        validate_index_embedding(DummyEmbedder("minilm", 384))
    except ValueError as exc:
        assert "768-dimensional" in str(exc)
        assert "minilm" in str(exc)
    else:
        raise AssertionError("Expected validate_index_embedding to reject non-768 dimensions")
