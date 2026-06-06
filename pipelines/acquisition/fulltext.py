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
    cached_pmc_xml_exists,
    sha256_file,
    utc_now,
    write_acquisition_queue,
)
from pipelines.config import load_pipeline_defaults

DEFAULT_LICENSED_ACCESS_METHODS = {
    "imperial-library",
    "imperial-vpn",
    "shibboleth",
    "publisher-tdm",
    "author-provided",
    "manual-upload",
}

DEFAULT_ALLOWED_ASSET_TYPES = {
    ".pdf": "licensed_pdf",
    ".xml": "licensed_xml",
    ".txt": "licensed_text",
}

BATCH_FIELDS = [
    "file",
    "document_id",
    "access_method",
    "access_status",
    "source_url",
    "license",
    "terms_note",
    "acquired_by",
    "sensitivity",
    "retention_policy",
    "owner",
    "notes",
]


def acquisition_config() -> dict[str, Any]:
    return load_pipeline_defaults().get("acquisition", {})


def licensed_access_methods() -> set[str]:
    configured = acquisition_config().get("allowed_access_methods")
    return set(configured or DEFAULT_LICENSED_ACCESS_METHODS)


def allowed_asset_types() -> dict[str, str]:
    configured = acquisition_config().get("allowed_asset_suffixes")
    if not configured:
        return dict(DEFAULT_ALLOWED_ASSET_TYPES)
    return {
        suffix.lower(): DEFAULT_ALLOWED_ASSET_TYPES.get(suffix.lower(), "licensed_file")
        for suffix in configured
    }


def acquisition_default(name: str, fallback: str) -> str:
    value = acquisition_config().get(name)
    return str(value) if value else fallback


def acquisition_guidance() -> str:
    return (
        "Use an approved Imperial/library route in a normal browser session. "
        "Do not store Imperial, Shibboleth, publisher, or personal credentials. "
        "Do not bypass paywalls, DRM, CAPTCHAs, publisher controls, or terms of use. "
        "Register only files that have already been acquired legally for internal use."
    )


def ensure_allowed_access_method(access_method: str) -> None:
    allowed_methods = licensed_access_methods()
    if access_method not in allowed_methods:
        allowed = ", ".join(sorted(allowed_methods))
        raise ValueError(f"Unknown access method '{access_method}'. Allowed: {allowed}")


def _filter_cached_fulltext_records(
    cache: CorpusCache,
    records: list[dict[str, Any]],
    *,
    include_cached_fulltext: bool,
) -> list[dict[str, Any]]:
    if include_cached_fulltext:
        return records
    return [
        record
        for record in records
        if not cached_pmc_xml_exists(cache, record.get("pmc_id"))
    ]


def read_queue(
    cache: CorpusCache,
    *,
    include_cached_fulltext: bool = False,
    refresh: bool = False,
) -> list[dict[str, Any]]:
    queue_path = cache.root / "reports" / "acquisition_queue.jsonl"
    if refresh or not queue_path.exists():
        documents = cache.read_documents()
        write_acquisition_queue(
            documents,
            queue_path,
            cache=cache,
            include_cached_fulltext=include_cached_fulltext,
        )
    return _filter_cached_fulltext_records(
        cache,
        cache.read_jsonl("reports/acquisition_queue.jsonl"),
        include_cached_fulltext=include_cached_fulltext,
    )


def export_review_csv(
    cache: CorpusCache,
    output_path: Path,
    *,
    include_cached_fulltext: bool = False,
    refresh_queue: bool = False,
) -> int:
    """Write a spreadsheet-friendly review file from the acquisition queue."""
    records = read_queue(
        cache,
        include_cached_fulltext=include_cached_fulltext,
        refresh=refresh_queue,
    )
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
    configured_asset_types = allowed_asset_types()
    asset_type = configured_asset_types.get(suffix)
    if asset_type is None:
        allowed = ", ".join(sorted(configured_asset_types))
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


def read_batch_manifest(manifest_path: Path) -> list[dict[str, Any]]:
    """Read a CSV or JSONL manifest for batch manual-asset registration."""
    suffix = manifest_path.suffix.lower()
    if suffix == ".csv":
        with open(manifest_path, newline="") as handle:
            return [dict(row) for row in csv.DictReader(handle)]

    if suffix in {".jsonl", ".ndjson"}:
        rows: list[dict[str, Any]] = []
        with open(manifest_path) as handle:
            for line_number, line in enumerate(handle, start=1):
                if not line.strip():
                    continue
                row = json.loads(line)
                if not isinstance(row, dict):
                    raise ValueError(f"Manifest line {line_number} must be a JSON object")
                rows.append(row)
        return rows

    raise ValueError("Batch manifest must be .csv, .jsonl, or .ndjson")


def write_batch_template(output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=BATCH_FIELDS)
        writer.writeheader()
        writer.writerow(
            {
                "file": "/path/to/downloaded/article.pdf",
                "document_id": "pmid:12345678",
                "access_method": "imperial-library",
                "access_status": "licensed-access",
                "source_url": "https://doi.org/10.1000/example",
                "license": "licensed-access",
                "terms_note": "Imperial library access for internal project use",
                "acquired_by": "authorized lab member",
                "sensitivity": "licensed",
                "retention_policy": "internal-project-storage",
                "owner": "",
                "notes": "",
            }
        )


def _row_value(row: dict[str, Any], key: str, default: str | None = None) -> str | None:
    value = row.get(key)
    if value is None:
        return default
    value = str(value).strip()
    return value or default


def register_manual_assets_from_manifest(
    cache: CorpusCache,
    *,
    manifest_path: Path,
    base_dir: Path | None = None,
    default_access_method: str | None = None,
    default_access_status: str = "licensed-access",
    default_sensitivity: str = "licensed",
    default_retention_policy: str = "internal-project-storage",
    dry_run: bool = False,
) -> dict[str, Any]:
    """Register many manually acquired assets from a CSV/JSONL manifest."""
    rows = read_batch_manifest(manifest_path)
    base = base_dir or manifest_path.parent
    registered: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []

    for index, row in enumerate(rows, start=1):
        file_value = _row_value(row, "file") or _row_value(row, "file_path") or _row_value(row, "path")
        document_id = _row_value(row, "document_id")
        if not file_value or not document_id:
            errors.append(
                {
                    "row": index,
                    "error": "missing_required_field",
                    "message": "Each row must include file and document_id",
                }
            )
            continue

        file_path = Path(file_value).expanduser()
        if not file_path.is_absolute():
            file_path = base / file_path

        access_method = _row_value(row, "access_method", default_access_method)
        if not access_method:
            errors.append(
                {
                    "row": index,
                    "file": str(file_path),
                    "document_id": document_id,
                    "error": "missing_access_method",
                    "message": "Each row needs access_method or --default-access-method",
                }
            )
            continue

        try:
            if dry_run:
                ensure_allowed_access_method(access_method)
                if not file_path.is_file():
                    raise FileNotFoundError(file_path)
                registered.append(
                    {
                        "row": index,
                        "document_id": document_id,
                        "file": str(file_path),
                        "dry_run": True,
                    }
                )
                continue

            record = register_manual_asset(
                cache,
                file_path=file_path,
                document_id=document_id,
                access_status=_row_value(row, "access_status", default_access_status) or default_access_status,
                access_method=access_method,
                source_url=_row_value(row, "source_url"),
                license=_row_value(row, "license"),
                terms_note=_row_value(row, "terms_note"),
                acquired_by=_row_value(row, "acquired_by"),
                sensitivity=_row_value(row, "sensitivity", default_sensitivity) or default_sensitivity,
                retention_policy=_row_value(row, "retention_policy", default_retention_policy)
                or default_retention_policy,
                owner=_row_value(row, "owner"),
                notes=_row_value(row, "notes"),
            )
            registered.append({"row": index, **record})
        except Exception as exc:
            errors.append(
                {
                    "row": index,
                    "file": str(file_path),
                    "document_id": document_id,
                    "error": type(exc).__name__,
                    "message": str(exc),
                }
            )

    return {
        "registered": len(registered),
        "failed": len(errors),
        "records": registered,
        "errors": errors,
        "dry_run": dry_run,
        "guidance": acquisition_guidance(),
    }


def _cmd_export_review(args: argparse.Namespace) -> None:
    cache = CorpusCache.open(args.cache)
    output = Path(args.output) if args.output else cache.root / "acquisition" / "review_queue.csv"
    count = export_review_csv(
        cache,
        output,
        include_cached_fulltext=args.include_cached_fulltext,
        refresh_queue=args.refresh_queue,
    )
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


def _cmd_register_batch(args: argparse.Namespace) -> None:
    cache = CorpusCache.open(args.cache)
    result = register_manual_assets_from_manifest(
        cache,
        manifest_path=Path(args.manifest),
        base_dir=Path(args.base_dir) if args.base_dir else None,
        default_access_method=args.default_access_method,
        default_access_status=args.default_access_status,
        default_sensitivity=args.default_sensitivity,
        default_retention_policy=args.default_retention_policy,
        dry_run=args.dry_run,
    )
    print(json.dumps(result, indent=2, sort_keys=True))


def _cmd_batch_template(args: argparse.Namespace) -> None:
    write_batch_template(Path(args.output))
    print(json.dumps({"output": args.output, "fields": BATCH_FIELDS}))


def main() -> None:
    parser = argparse.ArgumentParser(description="Credential-free full-text acquisition workflow")
    subparsers = parser.add_subparsers(dest="command", required=True)

    review = subparsers.add_parser("export-review", help="Export acquisition queue for manual review")
    review.add_argument("--cache", required=True)
    review.add_argument("--output")
    review.add_argument("--refresh-queue", action="store_true", help="Regenerate reports/acquisition_queue.jsonl before exporting")
    review.add_argument(
        "--include-cached-fulltext",
        action="store_true",
        help="Include documents whose PMC XML is already cached under raw/pmc/xml",
    )
    review.set_defaults(func=_cmd_export_review)

    register = subparsers.add_parser("register-asset", help="Register a manually acquired full-text file")
    register.add_argument("--cache", required=True)
    register.add_argument("--file", required=True)
    register.add_argument("--document-id", required=True)
    register.add_argument("--access-status", default=acquisition_default("default_access_status", "licensed-access"))
    register.add_argument("--access-method", required=True, choices=sorted(licensed_access_methods()))
    register.add_argument("--source-url")
    register.add_argument("--license")
    register.add_argument("--terms-note")
    register.add_argument("--acquired-by")
    register.add_argument("--sensitivity", default=acquisition_default("default_sensitivity", "licensed"), choices=sorted(SENSITIVITY_VALUES))
    register.add_argument("--retention-policy", default=acquisition_default("default_retention_policy", "internal-project-storage"))
    register.add_argument("--owner")
    register.add_argument("--notes")
    register.set_defaults(func=_cmd_register_asset)

    batch = subparsers.add_parser("register-batch", help="Register manually acquired full-text files from CSV/JSONL")
    batch.add_argument("--cache", required=True)
    batch.add_argument("--manifest", required=True)
    batch.add_argument("--base-dir", help="Resolve relative manifest file paths from this directory; defaults to manifest directory")
    batch.add_argument("--default-access-method", choices=sorted(licensed_access_methods()))
    batch.add_argument("--default-access-status", default=acquisition_default("default_access_status", "licensed-access"))
    batch.add_argument("--default-sensitivity", default=acquisition_default("default_sensitivity", "licensed"), choices=sorted(SENSITIVITY_VALUES))
    batch.add_argument("--default-retention-policy", default=acquisition_default("default_retention_policy", "internal-project-storage"))
    batch.add_argument("--dry-run", action="store_true", help="Validate manifest rows without copying or recording assets")
    batch.set_defaults(func=_cmd_register_batch)

    template = subparsers.add_parser("batch-template", help="Write a CSV template for register-batch")
    template.add_argument("--output", required=True)
    template.set_defaults(func=_cmd_batch_template)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
