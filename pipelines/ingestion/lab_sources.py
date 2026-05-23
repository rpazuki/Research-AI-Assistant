"""
Local lab-data ingestion adapters.

These adapters ingest files that have already been exported to local storage.
They do not connect to ELN/LIMS systems, inventories, cloud drives, or remote
services. Keep acquisition/export workflows separate from indexing.
"""

from __future__ import annotations

import csv
import mimetypes
import shutil
from collections.abc import Iterator
from pathlib import Path

from pipelines.corpus_cache import CorpusCache, PARSER_VERSIONS, sha256_file
from pipelines.ingestion.base import BaseIngester
from pipelines.processing.normalizer import NormalizedDocument

TEXT_SUFFIXES = {".md", ".markdown", ".txt"}
TABLE_SUFFIXES = {".csv", ".tsv"}

SOURCE_LABELS = {
    "lab_protocols": "protocol",
    "eln_lims": "eln_lims",
    "inventories": "inventory",
    "omics_summaries": "omics_summary",
}


class LocalTextCollectionIngester(BaseIngester):
    """Ingest local Markdown/text documents such as protocols and SOPs."""

    def __init__(
        self,
        directory: str,
        source_name: str,
        *,
        cache: CorpusCache | None = None,
        access_status: str = "internal",
        sensitivity: str = "internal",
        owner: str | None = None,
        retention_policy: str = "internal-project-storage",
    ) -> None:
        self.directory = Path(directory)
        if not self.directory.is_dir():
            raise ValueError(f"Local text directory not found: {directory}")
        self.source_name = source_name
        self.cache = cache
        self.access_status = access_status
        self.sensitivity = sensitivity
        self.owner = owner
        self.retention_policy = retention_policy

    def get_config_summary(self) -> dict:
        return {
            "source": self.source_name,
            "directory": str(self.directory),
            "file_count": len(self._files()),
        }

    def fetch(self) -> Iterator[NormalizedDocument]:
        for path in self._files():
            doc = self._parse_file(path)
            if self.cache is not None:
                self.cache.write_document(
                    doc,
                    raw_asset_path=doc.metadata["raw_asset_path"],
                    access_status=self.access_status,
                    parser_version=PARSER_VERSIONS["local_text"],
                )
            yield doc

    def _files(self) -> list[Path]:
        return sorted(
            path for path in self.directory.rglob("*") if path.is_file() and path.suffix.lower() in TEXT_SUFFIXES
        )

    def _parse_file(self, path: Path) -> NormalizedDocument:
        content_hash = sha256_file(path)
        raw_relative_path = f"raw/lab/originals/{content_hash}{path.suffix.lower()}"
        extracted_relative_path = f"raw/lab/extracted/{content_hash}.txt"

        if self.cache is not None:
            raw_path = self.cache.root / raw_relative_path
            if not raw_path.exists():
                raw_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(path, raw_path)
                self.cache.record_asset(
                    document_id=f"{self.source_name}:{content_hash}",
                    asset_type=f"{self.source_name}_original",
                    relative_path=raw_relative_path,
                    source_url=str(path.resolve()),
                    access_status=self.access_status,
                    license=self.access_status,
                    terms_note="Local lab-exported file",
                    parser_version=PARSER_VERSIONS["local_text"],
                    source_system=self.source_name,
                    access_method="local-export",
                    sensitivity=self.sensitivity,
                    retention_policy=self.retention_policy,
                    owner=self.owner,
                    extra={"original_filename": path.name, "mime_type": mimetypes.guess_type(path.name)[0]},
                )

        text = path.read_text(errors="replace").strip()
        if self.cache is not None:
            self.cache.write_bytes(extracted_relative_path, text.encode("utf-8"))

        return NormalizedDocument(
            document_id=f"{self.source_name}:{content_hash}",
            source=SOURCE_LABELS.get(self.source_name, self.source_name),
            title=path.stem,
            full_text=text,
            url=str(path.resolve()),
            license=self.access_status,
            metadata={
                "filename": path.name,
                "content_sha256": content_hash,
                "source_system": self.source_name,
                "raw_asset_path": raw_relative_path,
                "extracted_text_path": extracted_relative_path,
                "access_status": self.access_status,
                "access_method": "local-export",
                "sensitivity": self.sensitivity,
                "retention_policy": self.retention_policy,
                "owner": self.owner,
                "parser_version": PARSER_VERSIONS["local_text"],
            },
        )


class LocalTableCollectionIngester(BaseIngester):
    """Ingest local CSV/TSV summaries such as inventories, ELN exports, or omics tables."""

    def __init__(
        self,
        directory: str,
        source_name: str,
        *,
        cache: CorpusCache | None = None,
        access_status: str = "internal",
        sensitivity: str = "internal",
        owner: str | None = None,
        retention_policy: str = "internal-project-storage",
        max_rows: int = 500,
    ) -> None:
        self.directory = Path(directory)
        if not self.directory.is_dir():
            raise ValueError(f"Local table directory not found: {directory}")
        self.source_name = source_name
        self.cache = cache
        self.access_status = access_status
        self.sensitivity = sensitivity
        self.owner = owner
        self.retention_policy = retention_policy
        self.max_rows = max_rows

    def get_config_summary(self) -> dict:
        return {
            "source": self.source_name,
            "directory": str(self.directory),
            "file_count": len(self._files()),
            "max_rows": self.max_rows,
        }

    def fetch(self) -> Iterator[NormalizedDocument]:
        for path in self._files():
            doc = self._parse_file(path)
            if self.cache is not None:
                self.cache.write_document(
                    doc,
                    raw_asset_path=doc.metadata["raw_asset_path"],
                    access_status=self.access_status,
                    parser_version=PARSER_VERSIONS["local_table"],
                )
            yield doc

    def _files(self) -> list[Path]:
        return sorted(
            path for path in self.directory.rglob("*") if path.is_file() and path.suffix.lower() in TABLE_SUFFIXES
        )

    def _parse_file(self, path: Path) -> NormalizedDocument:
        content_hash = sha256_file(path)
        raw_relative_path = f"raw/lab/originals/{content_hash}{path.suffix.lower()}"
        extracted_relative_path = f"raw/lab/extracted/{content_hash}.txt"
        delimiter = "\t" if path.suffix.lower() == ".tsv" else ","
        rows = self._read_rows(path, delimiter)
        text = self._rows_to_text(path, rows)

        if self.cache is not None:
            raw_path = self.cache.root / raw_relative_path
            if not raw_path.exists():
                raw_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(path, raw_path)
                self.cache.record_asset(
                    document_id=f"{self.source_name}:{content_hash}",
                    asset_type=f"{self.source_name}_table_original",
                    relative_path=raw_relative_path,
                    source_url=str(path.resolve()),
                    access_status=self.access_status,
                    license=self.access_status,
                    terms_note="Local lab-exported table",
                    parser_version=PARSER_VERSIONS["local_table"],
                    source_system=self.source_name,
                    access_method="local-export",
                    sensitivity=self.sensitivity,
                    retention_policy=self.retention_policy,
                    owner=self.owner,
                    extra={
                        "original_filename": path.name,
                        "delimiter": "tab" if delimiter == "\t" else "comma",
                        "row_count": len(rows),
                    },
                )
            self.cache.write_bytes(extracted_relative_path, text.encode("utf-8"))

        return NormalizedDocument(
            document_id=f"{self.source_name}:{content_hash}",
            source=SOURCE_LABELS.get(self.source_name, self.source_name),
            title=path.stem,
            full_text=text,
            url=str(path.resolve()),
            license=self.access_status,
            metadata={
                "filename": path.name,
                "content_sha256": content_hash,
                "source_system": self.source_name,
                "raw_asset_path": raw_relative_path,
                "extracted_text_path": extracted_relative_path,
                "row_count": len(rows),
                "indexed_row_count": min(len(rows), self.max_rows),
                "access_status": self.access_status,
                "access_method": "local-export",
                "sensitivity": self.sensitivity,
                "retention_policy": self.retention_policy,
                "owner": self.owner,
                "parser_version": PARSER_VERSIONS["local_table"],
            },
        )

    def _read_rows(self, path: Path, delimiter: str) -> list[dict[str, str]]:
        with open(path, newline="") as handle:
            reader = csv.DictReader(handle, delimiter=delimiter)
            return [dict(row) for row in reader]

    def _rows_to_text(self, path: Path, rows: list[dict[str, str]]) -> str:
        lines = [f"{SOURCE_LABELS.get(self.source_name, self.source_name)} table: {path.stem}"]
        if not rows:
            lines.append("No rows.")
            return "\n".join(lines)

        headers = list(rows[0].keys())
        lines.append("Columns: " + ", ".join(headers))
        for index, row in enumerate(rows[: self.max_rows], start=1):
            values = "; ".join(f"{key}: {value}" for key, value in row.items() if value)
            lines.append(f"Row {index}: {values}")
        if len(rows) > self.max_rows:
            lines.append(f"Rows omitted from text cache: {len(rows) - self.max_rows}")
        return "\n".join(lines)
