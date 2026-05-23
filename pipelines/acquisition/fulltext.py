"""
Licensed/manual full-text acquisition workflow.

This module is intentionally separate from ingestion and indexing. It never
logs in, stores credentials, bypasses access controls, or bulk-downloads
publisher content. It records queue decisions and manually acquired files that
an authorized lab member has already downloaded through approved routes.
"""

from __future__ import annotations

import argparse
import csv
import json
import shutil
from pathlib import Path
from typing import Any

from pipelines.corpus_cache import (
    CorpusCache,
    SENSITIVITY_VALUES,
    sha256_file,
    utc_now,
    write_acquisition_queue,
)

LICENSED_ACCESS_METHODS = {
    "imperial-library",
    "imperial-vpn",
    "shibboleth",
    "publisher-tdm",
    "author-provided",
    "manual-upload",
}

ALLOWED_ASSET_TYPES = {
    ".pdf": "licensed_pdf",
    ".xml": "licensed_xml",
    ".txt": "licensed_text",
}


def acquisition_guidance() -> str:
    return (
        "Use an approved Imperial/library route in a normal browser session. "
        "Do not store Imperial, Shibboleth, publisher, or personal credentials. "
        "Do not bypass paywalls, DRM, CAPTCHAs, publisher controls, or terms of use. "
        "Register only files that have already been acquired legally for internal use."
    )


def ensure_allowed_access_method(access_method: str) -> None:
    if access_method not in LICENSED_ACCESS_METHODS:
        allowed = ", ".join(sorted(LICENSED_ACCESS_METHODS))
        raise ValueError(f"Unknown access method '{access_method}'. Allowed: {allowed}")


def read_queue(cache: CorpusCache) -> list[dict[str, Any]]:
    queue_path = cache.root / "reports" / "acquisition_queue.jsonl"
    if not queue_path.exists():
        documents = cache.read_documents()
        write_acquisition_queue(documents, queue_path)
    return cache.read_jsonl("reports/acquisition_queue.jsonl")


def export_review_csv(cache: CorpusCache, output_path: Path) -> int:
    """Write a spreadsheet-friendly review file from the acquisition queue."""
    records = read_queue(cache)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "document_id",
        "pmid",
        "pmc_id",
        "doi",
        "route",
        "candidate_url",
        "candidate_pdf_url",
        "access_status",
        "priority",
        "review_decision",
        "access_method",
        "reviewer",
        "notes",
    ]
    with open(output_path, "w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for record in records:
            writer.writerow({field: record.get(field, "") for field in fields})
    return len(records)


def register_manual_asset(
    cache: CorpusCache,
    *,
    file_path: Path,
    document_id: str,
    access_status: str,
    access_method: str,
    source_url: str | None = None,
    license: str | None = None,
    terms_note: str | None = None,
    acquired_by: str | None = None,
    sensitivity: str = "licensed",
    retention_policy: str = "internal-project-storage",
    owner: str | None = None,
    notes: str | None = None,
) -> dict[str, Any]:
    """Copy a manually acquired full-text asset into the cache and record provenance."""
    ensure_allowed_access_method(access_method)
    if sensitivity not in SENSITIVITY_VALUES:
        allowed = ", ".join(sorted(SENSITIVITY_VALUES))
        raise ValueError(f"Unknown sensitivity '{sensitivity}'. Allowed: {allowed}")
    if not file_path.is_file():
        raise FileNotFoundError(file_path)

    suffix = file_path.suffix.lower()
    asset_type = ALLOWED_ASSET_TYPES.get(suffix)
    if asset_type is None:
        allowed = ", ".join(sorted(ALLOWED_ASSET_TYPES))
        raise ValueError(f"Unsupported full-text asset type '{suffix}'. Allowed: {allowed}")

    digest = sha256_file(file_path)
    relative_path = f"raw/licensed/originals/{digest}{suffix}"
    destination = cache.root / relative_path
    destination.parent.mkdir(parents=True, exist_ok=True)
    if not destination.exists():
        shutil.copy2(file_path, destination)

    record = cache.record_asset(
        document_id=document_id,
        asset_type=asset_type,
        relative_path=relative_path,
        source_url=source_url,
        access_status=access_status,
        license=license,
        terms_note=terms_note,
        source_system="imperial-library",
        access_method=access_method,
        sensitivity=sensitivity,
        retention_policy=retention_policy,
        owner=owner,
        extra={
            "original_filename": file_path.name,
            "acquired_by": acquired_by,
            "registered_at": utc_now().isoformat().replace("+00:00", "Z"),
            "notes": notes,
            "workflow": "manual-licensed-fulltext",
            "download_performed_by_pipeline": False,
        },
    )
    cache.append_jsonl(
        "acquisition/registered_assets.jsonl",
        [
            {
                "document_id": document_id,
                "asset_id": record["asset_id"],
                "relative_path": relative_path,
                "access_status": access_status,
                "access_method": access_method,
                "registered_at": record["registered_at"],
                "guidance": acquisition_guidance(),
            }
        ],
    )
    return record


def _cmd_export_review(args: argparse.Namespace) -> None:
    cache = CorpusCache.open(args.cache)
    output = Path(args.output) if args.output else cache.root / "acquisition" / "review_queue.csv"
    count = export_review_csv(cache, output)
    print(json.dumps({"records": count, "output": str(output), "guidance": acquisition_guidance()}))


def _cmd_register_asset(args: argparse.Namespace) -> None:
    cache = CorpusCache.open(args.cache)
    record = register_manual_asset(
        cache,
        file_path=Path(args.file),
        document_id=args.document_id,
        access_status=args.access_status,
        access_method=args.access_method,
        source_url=args.source_url,
        license=args.license,
        terms_note=args.terms_note,
        acquired_by=args.acquired_by,
        sensitivity=args.sensitivity,
        retention_policy=args.retention_policy,
        owner=args.owner,
        notes=args.notes,
    )
    print(json.dumps(record, indent=2, sort_keys=True))


def main() -> None:
    parser = argparse.ArgumentParser(description="Credential-free full-text acquisition workflow")
    subparsers = parser.add_subparsers(dest="command", required=True)

    review = subparsers.add_parser("export-review", help="Export acquisition queue for manual review")
    review.add_argument("--cache", required=True)
    review.add_argument("--output")
    review.set_defaults(func=_cmd_export_review)

    register = subparsers.add_parser("register-asset", help="Register a manually acquired full-text file")
    register.add_argument("--cache", required=True)
    register.add_argument("--file", required=True)
    register.add_argument("--document-id", required=True)
    register.add_argument("--access-status", default="licensed-access")
    register.add_argument("--access-method", required=True, choices=sorted(LICENSED_ACCESS_METHODS))
    register.add_argument("--source-url")
    register.add_argument("--license")
    register.add_argument("--terms-note")
    register.add_argument("--acquired-by")
    register.add_argument("--sensitivity", default="licensed", choices=sorted(SENSITIVITY_VALUES))
    register.add_argument("--retention-policy", default="internal-project-storage")
    register.add_argument("--owner")
    register.add_argument("--notes")
    register.set_defaults(func=_cmd_register_asset)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
