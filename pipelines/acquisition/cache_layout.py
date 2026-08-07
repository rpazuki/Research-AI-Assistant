"""Where a datasheet run keeps the files it fetched.

Both sides of the fence need this. The backend writes assets and extracted text
here during acquisition; the ingestion pipeline reads them back to index a
finished run, and can only find `fulltext/<stem>.json` if it derives the stem
the same way. Keeping the rule in `pipelines` puts it on the side both can
import — the backend imports pipelines, never the reverse.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

ASSET_DIR_NAME = "assets"
TEXT_DIR_NAME = "fulltext"
DISCOVERY_DIR_NAME = "discovery"
MANIFEST_CSV_NAME = "manifest.csv"


def safe_stem(identifier: str) -> str:
    """A filesystem-safe, collision-free name for a DOI.

    DOIs contain slashes and arbitrary punctuation; a hash suffix keeps two DOIs
    that sanitise to the same string apart.
    """
    cleaned = "".join(char if char.isalnum() or char in "-._" else "_" for char in identifier)
    digest = hashlib.sha256(identifier.encode("utf-8")).hexdigest()[:10]
    return f"{cleaned[:80]}-{digest}"


def cache_paths(cache_root: Path, doi_or_id: str) -> tuple[Path, Path]:
    """Where an asset and its extracted text live for this run.

    The asset path has no suffix: the caller appends `.xml` or `.pdf` once the
    content format is known.
    """
    stem = safe_stem(doi_or_id)
    return (cache_root / ASSET_DIR_NAME / stem, cache_root / TEXT_DIR_NAME / f"{stem}.json")


def manifest_csv_path(cache_root: Path) -> Path:
    """The discovery manifest written next to the run's assets.

    Written at the end of phase A so a run directory describes itself: the CSV
    is the only place the stems in `assets/` and `fulltext/` can be mapped back
    to DOIs, since `safe_stem` is deliberately one-way.
    """
    return cache_root / DISCOVERY_DIR_NAME / MANIFEST_CSV_NAME
