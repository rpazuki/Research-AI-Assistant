"""
pipelines/ingestion/pdf_local.py
----------------------------------
Local PDF ingester for lab preprints, theses, and internal reports.

Uses pypdf for text extraction. For scanned PDFs, add an OCR step
(e.g. pytesseract or AWS Textract).

Usage:
    ingester = LocalPDFIngester(pdf_dir="./data/pdfs")
    for doc in ingester.fetch():
        process(doc)
"""

import logging
import shutil
from collections.abc import Iterator
from pathlib import Path

from pipelines.corpus_cache import CorpusCache, PARSER_VERSIONS, sha256_file
from pipelines.ingestion.base import BaseIngester
from pipelines.processing.normalizer import NormalizedDocument

logger = logging.getLogger(__name__)


class LocalPDFIngester(BaseIngester):
    source_name = "pdf"

    def __init__(self, pdf_dir: str, cache: CorpusCache | None = None) -> None:
        self.pdf_dir = Path(pdf_dir)
        if not self.pdf_dir.is_dir():
            raise ValueError(f"PDF directory not found: {pdf_dir}")
        self.cache = cache

    def get_config_summary(self) -> dict:
        pdf_count = len(list(self.pdf_dir.glob("*.pdf")))
        return {"source": self.source_name, "pdf_dir": str(self.pdf_dir), "pdf_count": pdf_count}

    def fetch(self) -> Iterator[NormalizedDocument]:
        """Yield NormalizedDocument for each PDF in pdf_dir."""
        try:
            import pypdf
        except ImportError:
            raise RuntimeError("pypdf not installed. Run: pip install pypdf")

        pdf_files = sorted(self.pdf_dir.glob("*.pdf"))
        logger.info(f"Found {len(pdf_files)} PDFs in {self.pdf_dir}")

        for pdf_path in pdf_files:
            try:
                doc = self._parse_pdf(pdf_path, pypdf)
                if doc is not None:
                    if self.cache is not None:
                        content_hash = doc.metadata["content_sha256"]
                        self.cache.write_document(
                            doc,
                            raw_asset_path=f"raw/pdf/originals/{content_hash}.pdf",
                            access_status="internal",
                            parser_version=PARSER_VERSIONS["pdf"],
                        )
                    yield doc
            except Exception as exc:
                logger.error(f"Failed to parse {pdf_path.name}: {exc}")

    def _parse_pdf(self, pdf_path: Path, pypdf) -> NormalizedDocument | None:
        """Extract text and metadata from a single PDF."""
        file_hash = sha256_file(pdf_path)
        original_relative_path = f"raw/pdf/originals/{file_hash}.pdf"
        extracted_text_relative_path = f"raw/pdf/extracted/{file_hash}.txt"
        page_text_relative_path = f"raw/pdf/extracted/{file_hash}.pages.json"

        if self.cache is not None:
            original_cache_path = self.cache.root / original_relative_path
            if not original_cache_path.exists():
                original_cache_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(pdf_path, original_cache_path)
                self.cache.record_asset(
                    document_id=f"pdf:{file_hash}",
                    asset_type="pdf_original",
                    relative_path=original_relative_path,
                    source_url=str(pdf_path.resolve()),
                    access_status="internal",
                    license="internal",
                    terms_note="Local lab PDF",
                )

        with open(pdf_path, "rb") as f:
            reader = pypdf.PdfReader(f)
            meta = reader.metadata or {}

            pages_text = []
            for page in reader.pages:
                text = page.extract_text() or ""
                pages_text.append(text)

        full_text = "\n\n".join(pages_text).strip()
        if not full_text:
            logger.warning(f"{pdf_path.name}: no text extracted (may be scanned)")
            if self.cache is not None:
                self.cache.write_document_error(
                    {
                        "document_id": f"pdf:{file_hash}",
                        "source": "pdf",
                        "filename": pdf_path.name,
                        "content_sha256": file_hash,
                        "parser_version": PARSER_VERSIONS["pdf"],
                        "text_extraction_status": "no-text",
                        "ocr_status": "needed",
                        "error": "No text extracted by pypdf; OCR required before indexing.",
                    }
                )
            return None

        if self.cache is not None:
            text_path = self.cache.write_bytes(extracted_text_relative_path, full_text.encode("utf-8"))
            self.cache.record_asset(
                document_id=f"pdf:{file_hash}",
                asset_type="pdf_extracted_text",
                relative_path=self.cache.relative_path(text_path),
                source_url=str(pdf_path.resolve()),
                access_status="internal",
                license="internal",
                parser_version=PARSER_VERSIONS["pdf"],
            )
            pages_payload = [
                {"page_index": index, "text": text}
                for index, text in enumerate(pages_text)
            ]
            self.cache.write_json(
                page_text_relative_path,
                {"pages": pages_payload, "source_pdf": original_relative_path},
            )

        doc_id = f"pdf:{file_hash}"

        title = str(meta.get("/Title", pdf_path.stem)) or pdf_path.stem
        pypdf_version = getattr(pypdf, "__version__", "unknown")
        pdf_metadata = {str(key): str(value) for key, value in dict(meta).items()}

        return NormalizedDocument(
            document_id=doc_id,
            source="pdf",
            title=title,
            full_text=full_text,
            url=str(pdf_path.resolve()),
            license="internal",
            metadata={
                "filename": pdf_path.name,
                "original_filename": pdf_path.name,
                "content_sha256": file_hash,
                "page_count": len(pages_text),
                "extraction_library": "pypdf",
                "extraction_library_version": pypdf_version,
                "parser_version": PARSER_VERSIONS["pdf"],
                "text_extraction_status": "extracted",
                "ocr_status": "not-needed",
                "raw_asset_path": original_relative_path,
                "extracted_text_path": extracted_text_relative_path,
                "page_text_path": page_text_relative_path,
                "detected_title": title,
                "pdf_metadata": pdf_metadata,
                "access_status": "internal",
            },
        )
