"""
pipelines/ingestion/datasheet_fulltext.py
-------------------------------------------
Index the full text a datasheet run already fetched.

The acquisition ladder pays for this text once — six routes, per-host rate
limits, robots checks, a circuit breaker — and writes it to
`<run>/fulltext/<stem>.json` with section labels intact. Until now the corpus
could not see any of it. This ingester reads those files and turns them into
documents, making no network calls at all: everything it needs is already on
disk.

Sections survive as far as `document_chunks.section_label`, which is what lets a
citation say "Methods" rather than "chunk 7".

Usage:
    ingester = DatasheetFullTextIngester.from_config("configs/datasheet.fulltext.rlalab.toml")
    for doc in ingester.fetch():
        process(doc)
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from pathlib import Path

from pipelines.acquisition.cache_layout import cache_paths
from pipelines.corpus_cache import PARSER_VERSIONS, CorpusCache
from pipelines.discovery.relevance import STUDIES
from pipelines.ingestion.base import BaseIngester
from pipelines.ingestion.datasheet_manifest import (
    ManifestRow,
    read_manifest,
    resolve_manifest_path,
    select_rows,
)
from pipelines.processing.normalizer import NormalizedDocument

logger = logging.getLogger(__name__)

# How the ladder's `source_format` maps onto documents.full_text_source.
_FULL_TEXT_SOURCE = {"xml": "pmc_jats", "pdf": "pdf_text"}

# The manifest is copied into the corpus cache so a cached run stays replayable
# on its own, without the datasheet run directory it was read from.
MANIFEST_COPY_PATH = "raw/datasheet/manifest.csv"
FULLTEXT_CACHE_DIR = "raw/datasheet/fulltext"


def text_document(row: ManifestRow, payload: dict, *, asset_path: str | None) -> NormalizedDocument:
    """Build a document from one `fulltext/<stem>.json` payload plus its manifest row.

    The payload owns the text; the manifest row owns the bibliography. Neither
    has both: extraction sees only the file it was handed, and the manifest has
    no abstract column.
    """
    sections = [
        {
            "label": section.get("label") or "other",
            "heading": section.get("heading"),
            "text": section.get("text") or "",
        }
        for section in payload.get("sections", [])
        if (section.get("text") or "").strip()
    ]
    full_text = "\n\n".join(
        f"## {section['heading'] or section['label']}\n{section['text']}" for section in sections
    )

    if row.pmid:
        document_id = f"pmid:{row.pmid}"
    elif row.doi:
        document_id = f"doi:{row.doi}"
    else:
        document_id = f"pmc:{row.pmc_id}"

    warnings = list(payload.get("warnings") or [])
    source_format = payload.get("source_format")

    return NormalizedDocument(
        document_id=document_id,
        source="pmc" if source_format == "xml" else "pdf",
        title=payload.get("title") or row.title,
        abstract=payload.get("abstract"),
        full_text=full_text or None,
        journal=row.journal,
        year=row.year,
        doi=row.doi,
        pmid=row.pmid,
        pmc_id=row.pmc_id,
        url=row.url or (f"https://doi.org/{row.doi}" if row.doi else None),
        license=row.license,
        publisher=row.publisher,
        oa_status=row.oa_status,
        doc_type=row.doc_type,
        is_review=row.is_review,
        is_retracted=row.is_retracted,
        preprint_of_doi=row.version_of_record_doi if row.is_preprint else None,
        full_text_source=_FULL_TEXT_SOURCE.get(source_format or "", "abstract_only"),
        sections=sections,
        metadata={
            "found_in": list(row.found_in),
            "relevance": row.relevance,
            "source_format": source_format,
            "fidelity_warnings": warnings,
            "asset_path": asset_path,
            "section_labels": [section["label"] for section in sections],
            "access_status": "licensed-access" if source_format == "pdf" else "open-access",
            "source_system": "datasheet_fulltext",
            "parser_version": PARSER_VERSIONS["datasheet_fulltext"],
        },
    )


class DatasheetFullTextIngester(BaseIngester):
    source_name = "datasheet_fulltext"

    def __init__(
        self,
        run_dir: str | Path,
        *,
        manifest_path: str | Path | None = None,
        min_relevance: str = STUDIES,
        include_reviews: bool = False,
        include_retracted: bool = False,
        cache: CorpusCache | None = None,
    ) -> None:
        self.run_dir = Path(run_dir)
        self.manifest_path = Path(manifest_path) if manifest_path else resolve_manifest_path(
            self.run_dir, None
        )
        self.min_relevance = min_relevance
        self.include_reviews = include_reviews
        self.include_retracted = include_retracted
        self.cache = cache

    @classmethod
    def from_config(
        cls,
        config_path: str,
        cache: CorpusCache | None = None,
    ) -> "DatasheetFullTextIngester":
        from pipelines.config import load_pipeline_config

        cfg = load_pipeline_config(config_path)
        datasheet_cfg = cfg.get("datasheet", {})
        run_dir = datasheet_cfg.get("run_dir")
        if not run_dir:
            raise ValueError("source='datasheet_fulltext' requires [datasheet].run_dir")
        return cls(
            run_dir=run_dir,
            manifest_path=datasheet_cfg.get("manifest_csv"),
            min_relevance=str(datasheet_cfg.get("min_relevance", STUDIES)),
            include_reviews=bool(datasheet_cfg.get("include_reviews", False)),
            include_retracted=bool(datasheet_cfg.get("include_retracted", False)),
            cache=cache,
        )

    def get_config_summary(self) -> dict:
        return {
            "source": self.source_name,
            "run_dir": str(self.run_dir),
            "manifest_path": str(self.manifest_path),
            "min_relevance": self.min_relevance,
        }

    def fetch(self) -> Iterator[NormalizedDocument]:
        rows = select_rows(
            read_manifest(self.manifest_path),
            min_relevance=self.min_relevance,
            include_reviews=self.include_reviews,
            include_retracted=self.include_retracted,
        )
        logger.info("datasheet fulltext: %d selected rows in %s", len(rows), self.run_dir)

        if self.cache is not None:
            # The manifest is copied in because the extracted-text payloads carry
            # no bibliography: without it a cache cannot be replayed or moved to
            # another machine, and the datasheet run it came from may be gone.
            self.cache.write_bytes(
                MANIFEST_COPY_PATH, self.manifest_path.read_bytes()
            )

        found = 0
        missing = 0
        for row in rows:
            identifier = row.identifier
            if not identifier:
                continue
            asset_base, text_path = cache_paths(self.run_dir, identifier)
            if not text_path.is_file():
                missing += 1
                continue
            try:
                payload = json.loads(text_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                logger.warning("datasheet fulltext: unreadable %s: %s", text_path, exc)
                self._write_error(row, text_path, str(exc))
                continue

            doc = text_document(row, payload, asset_path=self._asset_path(asset_base))
            if not doc.full_text and not doc.abstract:
                self._write_error(row, text_path, "extracted document has no text")
                continue

            found += 1
            if self.cache is not None:
                self.cache.write_bytes(
                    f"{FULLTEXT_CACHE_DIR}/{text_path.name}",
                    text_path.read_bytes(),
                )
                self.cache.write_document(
                    doc,
                    raw_asset_path=f"{FULLTEXT_CACHE_DIR}/{text_path.name}",
                    access_status=doc.metadata["access_status"],
                    parser_version=PARSER_VERSIONS["datasheet_fulltext"],
                )
            yield doc

        logger.info(
            "datasheet fulltext: %d documents indexed, %d selected rows had no fetched text",
            found,
            missing,
        )
        if self.cache is not None:
            self.cache.refresh_counts_from_artifacts()

    @staticmethod
    def _asset_path(asset_base: Path) -> str | None:
        for suffix in (".xml", ".pdf"):
            candidate = asset_base.with_suffix(suffix)
            if candidate.is_file():
                return str(candidate)
        return None

    def _write_error(self, row: ManifestRow, text_path: Path, message: str) -> None:
        if self.cache is None:
            return
        self.cache.write_document_error(
            {
                "document_id": f"doi:{row.doi}" if row.doi else f"pmid:{row.pmid}",
                "source": self.source_name,
                "error_type": "fulltext_unreadable",
                "message": message,
                "path": str(text_path),
            }
        )
