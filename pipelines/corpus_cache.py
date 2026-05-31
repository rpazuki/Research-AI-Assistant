"""
Durable corpus cache utilities.

The cache is a portable, run-scoped artifact under:

    data/corpora/<corpus_name>/<run_id>/

It stores raw assets, normalized documents, chunks, asset provenance, and a
self-describing manifest so the vector database can be rebuilt without
repeating upstream downloads.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from pipelines.processing.chunker import Chunk
from pipelines.processing.normalizer import AuthorRecord, NormalizedDocument

SCHEMA_VERSION = "1.0"
PARSER_VERSIONS = {
    "pubmed": "pubmed-v1",
    "pmc_jats": "pmc-jats-v1",
    "pdf": "pdf-v1",
    "local_text": "local-text-v1",
    "local_table": "local-table-v1",
}
ACCESS_STATUSES = {
    "metadata-only",
    "open-access",
    "open-access-candidate",
    "licensed-access",
    "internal",
    "restricted",
    "unavailable",
    "failed",
    "candidate",
}
SENSITIVITY_VALUES = {
    "public",
    "internal",
    "licensed",
    "confidential",
    "personal-data",
    "restricted",
}


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def make_run_id(now: datetime | None = None) -> str:
    value = now or utc_now()
    return value.strftime("%Y-%m-%dT%H%M%SZ")


def sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _json_default(value: Any) -> str:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


def _parse_datetime(value: str | None) -> datetime:
    if not value:
        return utc_now()
    normalized = value.replace("Z", "+00:00")
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is not None:
        return parsed.astimezone(timezone.utc).replace(tzinfo=None)
    return parsed


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    return date.fromisoformat(value)


def _author_to_dict(author: AuthorRecord | dict[str, Any]) -> dict[str, Any]:
    if isinstance(author, AuthorRecord):
        return asdict(author)
    return {
        "last_name": author.get("last_name", ""),
        "fore_name": author.get("fore_name", ""),
        "initials": author.get("initials", ""),
        "orcid": author.get("orcid"),
    }


@dataclass
class CorpusManifest:
    schema_version: str
    corpus_name: str
    run_id: str
    created_at: str
    source: str
    query: str | None = None
    date_from: str | None = None
    date_to: str | None = None
    embedding_model: str = "pubmedbert"
    chunk_size: int | None = None
    chunk_overlap: int | None = None
    parser_versions: dict[str, str] = field(default_factory=lambda: dict(PARSER_VERSIONS))
    counts: dict[str, int] = field(
        default_factory=lambda: {
            "pmids": 0,
            "raw_records": 0,
            "normalized_documents": 0,
            "chunks": 0,
            "errors": 0,
        }
    )

    @classmethod
    def from_config(
        cls,
        cfg: dict[str, Any],
        *,
        run_id: str | None = None,
    ) -> "CorpusManifest":
        corpus = cfg["corpus"]
        pubmed = cfg.get("pubmed", {})
        chunking = cfg.get("chunking", {})
        created_at = utc_now()
        return cls(
            schema_version=SCHEMA_VERSION,
            corpus_name=corpus["name"],
            run_id=run_id or make_run_id(created_at),
            created_at=created_at.isoformat().replace("+00:00", "Z"),
            source=corpus["source"],
            query=pubmed.get("query", "").strip() or None,
            date_from=f"{pubmed['year_from']}-01-01" if "year_from" in pubmed else None,
            date_to=f"{pubmed['year_to']}-12-31" if "year_to" in pubmed else None,
            embedding_model=corpus.get("embedding_model", "pubmedbert"),
            chunk_size=chunking.get("chunk_size"),
            chunk_overlap=chunking.get("chunk_overlap"),
        )


class CorpusCache:
    """Run-scoped filesystem cache with explicit data-contract helpers."""

    def __init__(self, root: Path, manifest: CorpusManifest | None = None) -> None:
        self.root = root
        self.manifest = manifest

    @classmethod
    def create(
        cls,
        *,
        base_dir: str | Path = "data/corpora",
        manifest: CorpusManifest,
    ) -> "CorpusCache":
        root = Path(base_dir) / manifest.corpus_name / manifest.run_id
        cache = cls(root=root, manifest=manifest)
        cache.ensure_layout()
        cache.write_manifest()
        return cache

    @classmethod
    def open(cls, root: str | Path) -> "CorpusCache":
        cache = cls(root=Path(root))
        cache.manifest = cache.read_manifest()
        cache.ensure_layout()
        return cache

    def ensure_layout(self) -> None:
        for relative in [
            "config",
            "raw/pubmed/esearch",
            "raw/pubmed/efetch",
            "raw/pmc/xml",
            "raw/pmc/pdf",
            "raw/doi/discovery",
            "raw/pdf/originals",
            "raw/pdf/extracted",
            "raw/licensed/originals",
            "raw/lab/originals",
            "raw/lab/extracted",
            "normalized",
            "chunks",
            "assets",
            "reports",
            "acquisition",
        ]:
            (self.root / relative).mkdir(parents=True, exist_ok=True)

    def copy_config(self, config_path: str | Path) -> None:
        destination = self.root / "config" / "corpus.toml"
        shutil.copy2(config_path, destination)

    def write_manifest(self) -> None:
        if self.manifest is None:
            raise ValueError("Cannot write manifest before it is set")
        self.write_json("manifest.json", asdict(self.manifest))

    def read_manifest(self) -> CorpusManifest:
        data = self.read_json("manifest.json")
        return CorpusManifest(**data)

    def update_counts(self, **counts: int) -> None:
        if self.manifest is None:
            self.manifest = self.read_manifest()
        self.manifest.counts.update({key: int(value) for key, value in counts.items()})
        self.write_manifest()

    def read_json(self, relative_path: str | Path) -> dict[str, Any]:
        with open(self.root / relative_path) as handle:
            return json.load(handle)

    def write_json(self, relative_path: str | Path, data: dict[str, Any]) -> Path:
        path = self.root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w") as handle:
            json.dump(data, handle, indent=2, sort_keys=True, default=_json_default)
            handle.write("\n")
        return path

    def append_jsonl(self, relative_path: str | Path, records: Iterable[dict[str, Any]]) -> None:
        path = self.root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a") as handle:
            for record in records:
                handle.write(json.dumps(record, sort_keys=True, default=_json_default))
                handle.write("\n")

    def read_jsonl(self, relative_path: str | Path) -> list[dict[str, Any]]:
        path = self.root / relative_path
        if not path.exists():
            return []
        records: list[dict[str, Any]] = []
        with open(path) as handle:
            for line in handle:
                if line.strip():
                    records.append(json.loads(line))
        return records

    def count_jsonl(self, relative_path: str | Path) -> int:
        path = self.root / relative_path
        if not path.exists():
            return 0
        count = 0
        with open(path) as handle:
            for line in handle:
                if line.strip():
                    count += 1
        return count

    def refresh_counts_from_artifacts(self) -> None:
        """Refresh manifest counts from accumulated cache artifacts.

        This keeps a reused cache directory honest after append-style runs.
        """
        if self.manifest is None:
            self.manifest = self.read_manifest()

        pmids: set[str] = set()
        documents_path = self.root / "normalized/documents.jsonl"
        if documents_path.exists():
            with open(documents_path) as handle:
                for line in handle:
                    if not line.strip():
                        continue
                    record = json.loads(line)
                    pmid = record.get("pmid")
                    if pmid:
                        pmids.add(str(pmid))

        raw_records = (
            len(list((self.root / "raw/pubmed/efetch").glob("*.xml")))
            + len(list((self.root / "raw/pmc/xml").glob("*.xml")))
            + len(list((self.root / "raw/pdf/extracted").glob("*.txt")))
            + len(list((self.root / "raw/lab/extracted").glob("*.txt")))
        )
        self.manifest.counts.update(
            {
                "pmids": len(pmids),
                "raw_records": raw_records,
                "normalized_documents": self.count_jsonl("normalized/documents.jsonl"),
                "chunks": self.count_jsonl("chunks/chunks.jsonl"),
                "errors": self.count_jsonl("normalized/documents.errors.jsonl"),
            }
        )
        self.write_manifest()

    def write_bytes(self, relative_path: str | Path, content: bytes) -> Path:
        path = self.root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        return path

    def relative_path(self, path: Path) -> str:
        return path.relative_to(self.root).as_posix()

    def record_asset(
        self,
        *,
        document_id: str | None,
        asset_type: str,
        relative_path: str,
        source_url: str | None = None,
        access_status: str,
        license: str | None = None,
        terms_note: str | None = None,
        parser_version: str | None = None,
        retrieved_at: datetime | None = None,
        source_system: str | None = None,
        access_method: str | None = None,
        sensitivity: str | None = None,
        retention_policy: str | None = None,
        owner: str | None = None,
        extra: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        path = self.root / relative_path
        digest = sha256_file(path)
        record = {
            "asset_id": f"sha256:{digest}",
            "document_id": document_id,
            "asset_type": asset_type,
            "relative_path": relative_path,
            "source_url": source_url,
            "sha256": digest,
            "bytes": path.stat().st_size,
            "retrieved_at": (retrieved_at or utc_now()).isoformat().replace("+00:00", "Z"),
            "access_status": access_status,
            "license": license,
            "terms_note": terms_note,
            "parser_version": parser_version,
            "source_system": source_system,
            "access_method": access_method,
            "sensitivity": sensitivity,
            "retention_policy": retention_policy,
            "owner": owner,
        }
        if extra:
            record.update(extra)
        self.append_jsonl("assets/asset_manifest.jsonl", [record])
        return record

    def write_document(self, doc: NormalizedDocument, **cache_metadata: Any) -> dict[str, Any]:
        record = document_to_cache_record(
            doc,
            source_run_id=self.manifest.run_id if self.manifest else None,
            **cache_metadata,
        )
        self.append_jsonl("normalized/documents.jsonl", [record])
        return record

    def write_document_error(self, error: dict[str, Any]) -> None:
        self.append_jsonl("normalized/documents.errors.jsonl", [error])

    def read_documents(self) -> list[NormalizedDocument]:
        return [document_from_cache_record(record) for record in self.read_jsonl("normalized/documents.jsonl")]

    def write_chunks(self, chunks: Iterable[Chunk], *, embedding_model: str) -> int:
        records = [chunk_to_cache_record(chunk, embedding_model=embedding_model, source_run_id=self.manifest.run_id if self.manifest else None) for chunk in chunks]
        self.append_jsonl("chunks/chunks.jsonl", records)
        return len(records)

    def read_chunks(self) -> list[Chunk]:
        return [chunk_from_cache_record(record) for record in self.read_jsonl("chunks/chunks.jsonl")]

    def validate(self) -> dict[str, Any]:
        """Validate that a cache is portable enough for local-only re-indexing."""
        errors: list[str] = []
        warnings: list[str] = []
        manifest_path = self.root / "manifest.json"
        if not manifest_path.exists():
            errors.append("manifest.json is missing")

        asset_records = self.read_jsonl("assets/asset_manifest.jsonl")
        for record in asset_records:
            relative_path = record.get("relative_path")
            if not relative_path:
                errors.append("asset record is missing relative_path")
                continue
            asset_path = self.root / relative_path
            if not asset_path.exists():
                errors.append(f"asset file is missing: {relative_path}")
                continue
            actual_sha = sha256_file(asset_path)
            if record.get("sha256") != actual_sha:
                errors.append(f"asset checksum mismatch: {relative_path}")
            if record.get("access_status") not in ACCESS_STATUSES:
                warnings.append(f"unknown access_status for {relative_path}: {record.get('access_status')}")
            sensitivity = record.get("sensitivity")
            if sensitivity and sensitivity not in SENSITIVITY_VALUES:
                warnings.append(f"unknown sensitivity for {relative_path}: {sensitivity}")

        document_records = self.read_jsonl("normalized/documents.jsonl")
        for record in document_records:
            if not record.get("cache_id"):
                errors.append(f"document is missing cache_id: {record.get('document_id')}")
            if not record.get("sha256"):
                errors.append(f"document is missing sha256: {record.get('document_id')}")
            if record.get("access_status") not in ACCESS_STATUSES:
                warnings.append(
                    f"unknown access_status for {record.get('document_id')}: {record.get('access_status')}"
                )

        return {
            "ok": not errors,
            "errors": errors,
            "warnings": warnings,
            "counts": {
                "assets": len(asset_records),
                "documents": len(document_records),
                "chunks": len(self.read_jsonl("chunks/chunks.jsonl")),
            },
        }


def document_to_cache_record(
    doc: NormalizedDocument,
    *,
    source_run_id: str | None,
    raw_asset_path: str | None = None,
    access_status: str | None = None,
    retrieved_at: datetime | None = None,
    parser_version: str | None = None,
    sha256: str | None = None,
    cache_id: str | None = None,
) -> dict[str, Any]:
    db = doc.to_db_dict()
    record = {
        **db,
        "authors": [_author_to_dict(author) for author in doc.authors],
        "publication_date": doc.publication_date.isoformat() if doc.publication_date else None,
        "ingested_at": doc.ingested_at.isoformat(),
        "source_run_id": source_run_id,
        "raw_asset_path": raw_asset_path,
        "access_status": access_status or doc.metadata.get("access_status") or doc.license or "metadata-only",
        "retrieved_at": (retrieved_at or utc_now()).isoformat().replace("+00:00", "Z"),
        "parser_version": parser_version,
        "source_system": doc.metadata.get("source_system") or doc.source,
        "source_url": doc.url,
        "access_method": doc.metadata.get("access_method"),
        "sensitivity": doc.metadata.get("sensitivity"),
        "retention_policy": doc.metadata.get("retention_policy"),
        "owner": doc.metadata.get("owner"),
    }
    canonical = json.dumps(record, sort_keys=True, default=_json_default).encode()
    digest = sha256 or sha256_bytes(canonical)
    record["sha256"] = digest
    record["cache_id"] = cache_id or f"sha256:{digest}"
    return record


def document_from_cache_record(record: dict[str, Any]) -> NormalizedDocument:
    authors = [
        AuthorRecord(
            last_name=author.get("last_name", ""),
            fore_name=author.get("fore_name", ""),
            initials=author.get("initials", ""),
            orcid=author.get("orcid"),
        )
        for author in record.get("authors", [])
    ]
    metadata = dict(record.get("metadata") or {})
    for key in [
        "cache_id",
        "source_run_id",
        "raw_asset_path",
        "sha256",
        "access_status",
        "retrieved_at",
        "parser_version",
        "source_system",
        "source_url",
        "access_method",
        "sensitivity",
        "retention_policy",
        "owner",
    ]:
        if key in record:
            metadata[key] = record[key]
    return NormalizedDocument(
        document_id=record["document_id"],
        source=record["source"],
        title=record.get("title"),
        abstract=record.get("abstract"),
        full_text=record.get("full_text"),
        authors=authors,
        journal=record.get("journal"),
        publication_date=_parse_date(record.get("publication_date")),
        year=record.get("year"),
        doi=record.get("doi"),
        pmid=record.get("pmid"),
        pmc_id=record.get("pmc_id"),
        mesh_terms=record.get("mesh_terms") or [],
        keywords=record.get("keywords") or [],
        url=record.get("url"),
        license=record.get("license"),
        ingested_at=_parse_datetime(record.get("ingested_at")),
        metadata=metadata,
    )


def chunk_to_cache_record(
    chunk: Chunk,
    *,
    embedding_model: str,
    source_run_id: str | None,
) -> dict[str, Any]:
    return {
        "source_run_id": source_run_id,
        "document_id": chunk.document_id,
        "chunk_index": chunk.chunk_index,
        "chunk_type": chunk.chunk_type,
        "content": chunk.content,
        "token_count": chunk.token_count,
        "embedding_model": embedding_model,
        "embedding_status": "pending",
    }


def chunk_from_cache_record(record: dict[str, Any]) -> Chunk:
    return Chunk(
        document_id=record["document_id"],
        chunk_index=record["chunk_index"],
        chunk_type=record.get("chunk_type", "abstract"),
        content=record["content"],
        token_count=record.get("token_count"),
    )


def load_toml(path: str | Path) -> dict[str, Any]:
    try:
        import tomllib
    except ImportError:
        import tomli as tomllib  # type: ignore

    with open(path, "rb") as handle:
        return tomllib.load(handle)


def create_cache_from_config(
    config_path: str | Path,
    *,
    base_dir: str | Path = "data/corpora",
    run_id: str | None = None,
) -> CorpusCache:
    cfg = load_toml(config_path)
    manifest = CorpusManifest.from_config(cfg, run_id=run_id)
    cache = CorpusCache.create(base_dir=base_dir, manifest=manifest)
    cache.copy_config(config_path)
    return cache


def write_acquisition_queue(
    documents: Iterable[NormalizedDocument],
    output_path: Path,
    *,
    cache: CorpusCache | None = None,
    include_cached_fulltext: bool = False,
) -> int:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    seen: set[tuple[str, str]] = set()
    with open(output_path, "w") as handle:
        for doc in documents:
            candidates = full_text_candidates(
                doc,
                cache=cache,
                include_cached_fulltext=include_cached_fulltext,
            )
            for candidate in candidates:
                key = (candidate["document_id"], candidate["route"])
                if key in seen:
                    continue
                seen.add(key)
                handle.write(json.dumps(candidate, sort_keys=True))
                handle.write("\n")
                count += 1
    return count


def _safe_pmc_id(pmc_id: str) -> str:
    clean = pmc_id.strip()
    if clean.upper().startswith("PMC"):
        return f"PMC{clean[3:]}"
    return f"PMC{clean}"


def cached_pmc_xml_exists(cache: CorpusCache | None, pmc_id: str | None) -> bool:
    if cache is None or not pmc_id:
        return False
    return (cache.root / "raw" / "pmc" / "xml" / f"{_safe_pmc_id(str(pmc_id))}.xml").exists()


def full_text_candidates(
    doc: NormalizedDocument,
    *,
    cache: CorpusCache | None = None,
    include_cached_fulltext: bool = False,
) -> list[dict[str, Any]]:
    if (
        doc.pmc_id
        and not include_cached_fulltext
        and cached_pmc_xml_exists(cache, doc.pmc_id)
    ):
        return []

    candidates: list[dict[str, Any]] = []
    if doc.pmc_id:
        safe_pmc_id = _safe_pmc_id(doc.pmc_id)
        candidates.append(
            {
                "document_id": doc.document_id,
                "pmid": doc.pmid,
                "pmc_id": safe_pmc_id,
                "doi": doc.doi,
                "candidate_url": f"https://pmc.ncbi.nlm.nih.gov/articles/{safe_pmc_id}/",
                "candidate_pdf_url": f"https://pmc.ncbi.nlm.nih.gov/articles/{safe_pmc_id}/pdf/",
                "route": "pmcid",
                "access_status": "open-access-candidate",
                "priority": "high",
                "notes": "PMCID present in source metadata; check PMC OA availability before download.",
            }
        )
    if doc.doi:
        doi_url = f"https://doi.org/{doc.doi}"
        candidates.append(
            {
                "document_id": doc.document_id,
                "pmid": doc.pmid,
                "pmc_id": doc.pmc_id,
                "doi": doc.doi,
                "candidate_url": doi_url,
                "candidate_pdf_url": None,
                "route": "doi",
                "access_status": "candidate",
                "priority": "normal",
                "notes": "DOI landing page discovered; classify OA or licensed access before acquisition.",
            }
        )
    return candidates


def _cmd_create(args: argparse.Namespace) -> None:
    cache = create_cache_from_config(args.config, base_dir=args.base_dir, run_id=args.run_id)
    print(cache.root)


def main() -> None:
    parser = argparse.ArgumentParser(description="Manage RLALab corpus cache artifacts")
    subparsers = parser.add_subparsers(dest="command", required=True)

    create = subparsers.add_parser("create", help="Create a cache layout and manifest")
    create.add_argument("--config", required=True)
    create.add_argument("--base-dir", default="data/corpora")
    create.add_argument("--run-id")
    create.set_defaults(func=_cmd_create)

    validate = subparsers.add_parser("validate", help="Validate a cache for transfer/local re-indexing")
    validate.add_argument("--cache", required=True)
    validate.set_defaults(func=lambda args: print(json.dumps(CorpusCache.open(args.cache).validate(), indent=2)))

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
