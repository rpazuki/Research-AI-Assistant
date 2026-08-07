"""
pipelines/processing/chunker.py
---------------------------------
Text chunker for indexing.

Produces chunks with configurable size, overlap, and splitting strategy.
Uses sentence-aware splitting to avoid mid-sentence breaks.

Chunk types:
    'abstract'    — from abstract-only ingestion
    'fulltext'    — from PMC or PDF full-text ingestion
    'title_abstract' — title + abstract combined (for short abstracts)
"""

from dataclasses import dataclass
from typing import Literal

from pipelines.processing.normalizer import NormalizedDocument


@dataclass
class Chunk:
    document_id: str
    chunk_index: int
    chunk_type: str
    content: str
    token_count: int | None = None
    # Which part of the paper this text came from: title|abstract|introduction|
    # methods|results|discussion|supplementary. Only sources that know the answer
    # set it; retrieval already reads the column and shows it in citations.
    section_label: str | None = None


ChunkMode = Literal["abstract", "fulltext"]


class Chunker:
    def __init__(
        self,
        chunk_size: int = 512,
        chunk_overlap: int = 64,
        mode: ChunkMode = "abstract",
    ) -> None:
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.mode = mode

    def chunk_document(self, doc: NormalizedDocument) -> list[Chunk]:
        """
        Chunk a NormalizedDocument into overlapping text segments.

        Returns an empty list if no indexable text is available.
        """
        text = doc.text_for_indexing(mode=self.mode)
        if not text.strip():
            return []

        chunk_type = "abstract" if self.mode == "abstract" else "fulltext"
        raw_chunks = self._split_text(text)

        return [
            Chunk(
                document_id=doc.document_id,
                chunk_index=i,
                chunk_type=chunk_type,
                content=chunk,
                token_count=self._approx_token_count(chunk),
            )
            for i, chunk in enumerate(raw_chunks)
        ]

    def chunk_sections(
        self,
        document_id: str,
        sections: list[tuple[str | None, str]],
        *,
        chunk_type: str = "fulltext",
    ) -> list[Chunk]:
        """Chunk a document whose sections are already known, label intact.

        Each `(label, text)` pair is split on its own so no chunk ever straddles
        Methods and Results — a chunk that did could not honestly claim either
        label, and section-level citation is the whole point. `chunk_index` runs
        continuously across sections so it stays the document-wide ordering.
        """
        chunks: list[Chunk] = []
        for label, text in sections:
            if not text or not text.strip():
                continue
            for piece in self._split_text(text):
                chunks.append(
                    Chunk(
                        document_id=document_id,
                        chunk_index=len(chunks),
                        chunk_type=chunk_type,
                        content=piece,
                        token_count=self._approx_token_count(piece),
                        section_label=label,
                    )
                )
        return chunks

    def _split_text(self, text: str) -> list[str]:
        """
        Sentence-aware text splitter.

        Splits on sentence boundaries (periods, question marks, exclamation marks)
        and assembles chunks up to chunk_size words with chunk_overlap word overlap.

        Note: 'words' is used as a proxy for tokens. For exact token counts,
        integrate the tokenizer from the embedding model.
        """
        # Simple sentence split (replace with spacy or nltk for better accuracy)
        import re
        sentences = re.split(r'(?<=[.!?])\s+', text)

        chunks = []
        current_words: list[str] = []
        overlap_buffer: list[str] = []

        for sentence in sentences:
            sentence_words = sentence.split()
            if not sentence_words:
                continue

            if len(current_words) + len(sentence_words) > self.chunk_size:
                if current_words:
                    chunks.append(" ".join(current_words))
                # Overlap: keep last chunk_overlap words
                overlap_buffer = current_words[-self.chunk_overlap:] if self.chunk_overlap > 0 else []
                current_words = overlap_buffer + sentence_words
            else:
                current_words.extend(sentence_words)

        if current_words:
            chunks.append(" ".join(current_words))

        return [c.strip() for c in chunks if c.strip()]

    @staticmethod
    def _approx_token_count(text: str) -> int:
        """Approximate token count as word count (rough proxy, ~1.3 tokens/word)."""
        return int(len(text.split()) * 1.3)
