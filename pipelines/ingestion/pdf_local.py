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

import hashlib
import logging
from collections.abc import Iterator
from pathlib import Path

from pipelines.ingestion.base import BaseIngester
from pipelines.processing.normalizer import NormalizedDocument

logger = logging.getLogger(__name__)


class LocalPDFIngester(BaseIngester):
    source_name = "pdf"

    def __init__(self, pdf_dir: str) -> None:
        self.pdf_dir = Path(pdf_dir)
        if not self.pdf_dir.is_dir():
            raise ValueError(f"PDF directory not found: {pdf_dir}")

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
                    yield doc
            except Exception as exc:
                logger.error(f"Failed to parse {pdf_path.name}: {exc}")

    def _parse_pdf(self, pdf_path: Path, pypdf) -> NormalizedDocument | None:
        """Extract text and metadata from a single PDF."""
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
            return None

        # Use a stable document_id based on file content hash
        file_hash = hashlib.md5(pdf_path.read_bytes()).hexdigest()[:12]
        doc_id = f"pdf:{pdf_path.stem}_{file_hash}"

        title = str(meta.get("/Title", pdf_path.stem)) or pdf_path.stem

        return NormalizedDocument(
            document_id=doc_id,
            source="pdf",
            title=title,
            full_text=full_text,
            url=str(pdf_path.resolve()),
            license="internal",
            metadata={"filename": pdf_path.name, "page_count": len(pages_text)},
        )
