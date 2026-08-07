"""
pipelines/ingestion/datasheet_rows.py
---------------------------------------
Extracted datasheet rows as retrievable documents.

A datasheet row is a curated claim about one paper — strain, product, titre,
carbon source, cultivation mode — and it is the unit a researcher actually asks
about ("which strains reached over 50 g/L of citric acid?"). So each row becomes
its own document rather than each file: a row carries its own DOI, and a
question answered from it must cite that paper, not the spreadsheet.

Input is any CSV/TSV whose header matches the datasheet template — the phase-E
export when it exists, and the curators' own spreadsheet saved as CSV until
then. Column labels come from `pipelines/extraction/default_template.py`, so a
template change reaches this ingester without an edit here.

Usage:
    ingester = DatasheetRowsIngester.from_config("configs/datasheet.rows.rlalab.toml")
    for doc in ingester.fetch():
        process(doc)
"""

from __future__ import annotations

import csv
import logging
from collections.abc import Iterator
from pathlib import Path

from pipelines.corpus_cache import PARSER_VERSIONS, CorpusCache, sha256_bytes
from pipelines.discovery.manifest_csv import NOT_REPORTED
from pipelines.extraction.default_template import PROVENANCE_COLUMNS
from pipelines.ingestion.base import BaseIngester
from pipelines.processing.normalizer import NormalizedDocument

logger = logging.getLogger(__name__)

ROWS_CACHE_PATH = "raw/datasheet/rows/rows.jsonl"

# Provenance columns are bibliography, not content: they identify the paper the
# row is about and must not be repeated inside the indexed text.
_PROVENANCE_KEYS = {column["key"] for column in PROVENANCE_COLUMNS} | {"doi_url", "link"}

_EMPTY_VALUES = {"", "-", "n/a", "na", "none", "not reported", "not applicable"}


def _cell(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = str(value).strip()
    if not cleaned or cleaned.casefold() in _EMPTY_VALUES or cleaned == NOT_REPORTED:
        return None
    return cleaned


def _lookup(row: dict[str, str], *names: str) -> str | None:
    """Case- and punctuation-insensitive column lookup.

    The same column is `doi` in the export and `DOI` in the curators' sheet;
    matching exactly would silently drop the identifier and produce a row nobody
    can cite.
    """
    normalised = {_normalise_key(key): value for key, value in row.items() if key}
    for name in names:
        value = normalised.get(_normalise_key(name))
        if _cell(value) is not None:
            return _cell(value)
    return None


def _normalise_key(key: str) -> str:
    return "".join(char for char in str(key).casefold() if char.isalnum())


def row_to_text(row: dict[str, str]) -> str:
    """Render a row as labelled lines, skipping bibliography and empty cells."""
    lines = []
    for key, value in row.items():
        if not key or _normalise_key(key) in {_normalise_key(k) for k in _PROVENANCE_KEYS}:
            continue
        cleaned = _cell(value)
        if cleaned is None:
            continue
        lines.append(f"{key.strip()}: {cleaned}")
    return "\n".join(lines)


def row_to_document(
    row: dict[str, str],
    *,
    row_index: int,
    template_name: str,
    source_path: Path,
    access_status: str = "internal",
    sensitivity: str = "internal",
    owner: str | None = None,
    retention_policy: str = "internal-project-storage",
) -> NormalizedDocument | None:
    """One datasheet row as a document, or None when the row has no content."""
    text = row_to_text(row)
    if not text.strip():
        return None

    doi = _lookup(row, "doi")
    pmid = _lookup(row, "pmid")
    title = _lookup(row, "article", "title")
    year_raw = _lookup(row, "year")
    try:
        year = int(str(year_raw)[:4]) if year_raw else None
    except ValueError:
        year = None

    # Identity is the row, not the paper: several rows legitimately describe the
    # same article (different product, different condition), and merging them
    # onto one document_id would lose all but the last.
    seed = f"{template_name}|{doi or title or source_path.name}|{row_index}"
    document_id = f"datasheet_row:{sha256_bytes(seed.encode('utf-8'))[:32]}"

    return NormalizedDocument(
        document_id=document_id,
        source="datasheet_row",
        title=f"Datasheet row: {title}" if title else f"Datasheet row {row_index + 1}",
        full_text=text,
        journal=_lookup(row, "journal"),
        year=year,
        doi=doi,
        pmid=pmid,
        url=_lookup(row, "link", "doi_url") or (f"https://doi.org/{doi}" if doi else None),
        license="internal",
        publisher=_lookup(row, "publisher"),
        oa_status=_lookup(row, "oa_status"),
        doc_type=_lookup(row, "doc_type"),
        is_review=(_lookup(row, "is_review") or "").casefold() in {"yes", "true"},
        is_retracted=(_lookup(row, "is_retracted") or "").casefold() in {"yes", "true"},
        full_text_source="abstract_only",
        metadata={
            "row_index": row_index,
            "template": template_name,
            "source_file": source_path.name,
            "acquisition_route": _lookup(row, "acquisition_route"),
            "acquisition_status": _lookup(row, "acquisition_status"),
            "source_system": "datasheet_rows",
            "access_status": access_status,
            "access_method": "local-export",
            "sensitivity": sensitivity,
            "retention_policy": retention_policy,
            "owner": owner,
            "parser_version": PARSER_VERSIONS["datasheet_rows"],
        },
    )


class DatasheetRowsIngester(BaseIngester):
    source_name = "datasheet_rows"

    def __init__(
        self,
        rows_csv: str | Path,
        *,
        template_name: str = "default",
        access_status: str = "internal",
        sensitivity: str = "internal",
        owner: str | None = None,
        retention_policy: str = "internal-project-storage",
        cache: CorpusCache | None = None,
    ) -> None:
        self.rows_csv = Path(rows_csv)
        self.template_name = template_name
        self.access_status = access_status
        self.sensitivity = sensitivity
        self.owner = owner
        self.retention_policy = retention_policy
        self.cache = cache

    @classmethod
    def from_config(
        cls,
        config_path: str,
        cache: CorpusCache | None = None,
    ) -> "DatasheetRowsIngester":
        from pipelines.config import load_pipeline_config

        cfg = load_pipeline_config(config_path)
        datasheet_cfg = cfg.get("datasheet", {})
        rows_csv = datasheet_cfg.get("rows_csv")
        if not rows_csv:
            raise ValueError("source='datasheet_rows' requires [datasheet].rows_csv")
        return cls(
            rows_csv=rows_csv,
            template_name=str(datasheet_cfg.get("template_name", "default")),
            access_status=str(datasheet_cfg.get("access_status", "internal")),
            sensitivity=str(datasheet_cfg.get("sensitivity", "internal")),
            owner=datasheet_cfg.get("owner"),
            retention_policy=str(
                datasheet_cfg.get("retention_policy", "internal-project-storage")
            ),
            cache=cache,
        )

    def get_config_summary(self) -> dict:
        return {
            "source": self.source_name,
            "rows_csv": str(self.rows_csv),
            "template_name": self.template_name,
        }

    def fetch(self) -> Iterator[NormalizedDocument]:
        if not self.rows_csv.is_file():
            raise FileNotFoundError(f"Datasheet rows file not found: {self.rows_csv}")

        delimiter = "\t" if self.rows_csv.suffix.lower() == ".tsv" else ","
        with open(self.rows_csv, newline="", encoding="utf-8-sig") as handle:
            rows = list(csv.DictReader(handle, delimiter=delimiter))

        if self.cache is not None:
            self.cache.write_bytes(
                f"raw/datasheet/rows/{self.rows_csv.name}", self.rows_csv.read_bytes()
            )
            self.cache.record_asset(
                document_id=None,
                asset_type="datasheet_rows",
                relative_path=f"raw/datasheet/rows/{self.rows_csv.name}",
                access_status=self.access_status,
                sensitivity=self.sensitivity,
                retention_policy=self.retention_policy,
                owner=self.owner,
                parser_version=PARSER_VERSIONS["datasheet_rows"],
                source_system="datasheet_rows",
                access_method="local-export",
            )

        emitted = 0
        empty = 0
        for index, row in enumerate(rows):
            doc = row_to_document(
                row,
                row_index=index,
                template_name=self.template_name,
                source_path=self.rows_csv,
                access_status=self.access_status,
                sensitivity=self.sensitivity,
                owner=self.owner,
                retention_policy=self.retention_policy,
            )
            if doc is None:
                empty += 1
                continue
            emitted += 1
            if self.cache is not None:
                # Nested rather than merged so a column called `template` cannot
                # shadow the replay metadata, and replay can rebuild the exact
                # same document_id (which is seeded with both).
                self.cache.append_jsonl(
                    ROWS_CACHE_PATH,
                    [
                        {
                            "row_index": index,
                            "template": self.template_name,
                            "source_file": self.rows_csv.name,
                            "row": dict(row),
                        }
                    ],
                )
                self.cache.write_document(
                    doc,
                    raw_asset_path=f"raw/datasheet/rows/{self.rows_csv.name}",
                    access_status=self.access_status,
                    parser_version=PARSER_VERSIONS["datasheet_rows"],
                )
            yield doc

        logger.info(
            "datasheet rows: %d of %d rows indexed (%d had no content)",
            emitted,
            len(rows),
            empty,
        )
        if self.cache is not None:
            self.cache.refresh_counts_from_artifacts()
