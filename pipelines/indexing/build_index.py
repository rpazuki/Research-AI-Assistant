"""
pipelines/indexing/build_index.py
-----------------------------------
Main indexing entry point.

Usage:
    python -m pipelines.indexing.build_index --config configs/corpus.rlalab.toml

    # Incremental update (fetch only articles since last run):
    python -m pipelines.indexing.build_index --config configs/corpus.rlalab.toml --from-date 2025-01-01

    # Test with a small subset (year 2024 only):
    python -m pipelines.indexing.build_index --config configs/corpus.rlalab.toml --year 2024

Flow:
    1. Load config
    2. Initialise ingester (PubMed / PMC / PDF based on config)
    3. Ingest documents → normalize
    4. Upsert documents into Postgres
    5. Chunk each document
    6. Embed chunks in batches (PubMedBERT by default)
    7. Upsert chunks + embeddings into document_chunks
    8. Save manifest record
    9. (After first full load) Create IVFFlat index if not exists

IMPORTANT after first load:
    Run this SQL manually once:
    CREATE INDEX ix_chunks_embedding ON document_chunks
    USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);
"""

import argparse
import asyncio
import inspect
import json
import logging
import sys
import uuid
from datetime import date, datetime, timezone
from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import Any, Callable

# Allow running as a module from the pipelines/ directory
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import asyncpg

from pipelines.ingestion.pubmed_abstract import PubMedAbstractIngester
from pipelines.ingestion.pdf_local import LocalPDFIngester
from pipelines.ingestion.pmc_fulltext import PMCFullTextIngester
from pipelines.ingestion.discovery_search import DiscoverySearchIngester
from pipelines.ingestion.datasheet_fulltext import DatasheetFullTextIngester
from pipelines.ingestion.datasheet_manifest import DatasheetManifestIngester
from pipelines.ingestion.datasheet_rows import DatasheetRowsIngester
from pipelines.ingestion.lab_sources import (
    LocalTableCollectionIngester,
    LocalTextCollectionIngester,
)
from pipelines.corpus_cache import (
    PARSER_VERSIONS,
    CorpusCache,
    CorpusManifest,
    write_acquisition_queue,
)
from pipelines.config import load_pipeline_config
from pipelines.processing.chunker import Chunker
from pipelines.processing.deduplicator import Deduplicator
from pipelines.processing.normalizer import NormalizedDocument

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

LOCAL_TEXT_SOURCES = {"lab_protocols"}
LOCAL_TABLE_SOURCES = {"eln_lims", "inventories", "omics_summaries"}
LOCAL_LAB_SOURCES = LOCAL_TEXT_SOURCES | LOCAL_TABLE_SOURCES

DATASHEET_SOURCES = {"datasheet_manifest", "datasheet_fulltext", "datasheet_rows"}

# Sources whose document is a row about a paper, not the paper itself. See the
# deduplication note in build_index().
ROW_SCOPED_SOURCES = {"datasheet_rows"}

# Which text of a document each source can offer the chunker. Stated per source
# rather than sniffed from the name: `"abstract" in source` silently filed
# `discovery_search` and every `datasheet_*` key under fulltext, and a fulltext
# chunker on an abstract-only document quietly falls back (normalizer.py:71-77)
# with a chunk_type that then lies about where the text came from.
SOURCE_CHUNK_MODES: dict[str, str] = {
    "pubmed_abstract": "abstract",
    "discovery_search": "abstract",
    "datasheet_manifest": "abstract",
    "pmc_fulltext": "fulltext",
    "pdf": "fulltext",
    "datasheet_fulltext": "fulltext",
    "datasheet_rows": "fulltext",
    **{source: "fulltext" for source in LOCAL_LAB_SOURCES},
}


def chunk_mode_for_source(source: str) -> str:
    """Chunk mode for an ingester key, defaulting to fulltext for unknown sources."""
    return SOURCE_CHUNK_MODES.get(source, "fulltext")


def chunks_for_document(chunker: Chunker, doc: NormalizedDocument) -> list:
    """Section-aware where the source knows its sections, whole-document otherwise."""
    sections = [
        (section.get("label"), section.get("text") or "")
        for section in (doc.sections or [])
        if (section.get("text") or "").strip()
    ]
    if not sections:
        return chunker.chunk_document(doc)

    if doc.title:
        sections.insert(0, ("title", doc.title))
    return chunker.chunk_sections(doc.document_id, sections)

ProgressCallback = Callable[[str, dict[str, Any] | None], Any]


async def notify_progress(
    progress_callback: ProgressCallback | None,
    message: str,
    payload: dict[str, Any] | None = None,
) -> None:
    if progress_callback is None:
        return
    result = progress_callback(message, payload or {})
    if inspect.isawaitable(result):
        await result


async def upsert_document(conn, doc: NormalizedDocument, manifest_id: uuid.UUID) -> uuid.UUID:
    """Upsert a document and return its database UUID.

    The conflict clause is deliberately asymmetric. Text fields are overwritten,
    because a later run is by definition the fresher extraction. The bibliographic
    sidecar is merged with COALESCE instead: one paper legitimately arrives from
    several sources, and an abstract-only re-ingest that knows nothing about the
    publisher must not erase what discovery already established. `is_retracted`
    is OR-ed for the same reason in the direction that matters — a retraction is
    never withdrawn by a source that simply did not check.
    """
    d = doc.to_db_dict()
    row = await conn.fetchrow(
        """
        INSERT INTO documents
            (manifest_id, document_id, source, title, abstract, full_text, authors,
             journal, publication_date, year, doi, pmid, pmc_id, mesh_terms, keywords,
             url, license, ingested_at, metadata,
             publisher, oa_status, doc_type, is_review, is_retracted, preprint_of_doi,
             full_text_source, access_route)
        VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,$18,$19,
                $20,$21,$22,$23,$24,$25,$26,$27)
        ON CONFLICT (document_id) DO UPDATE SET
            title = COALESCE(EXCLUDED.title, documents.title),
            abstract = COALESCE(EXCLUDED.abstract, documents.abstract),
            full_text = COALESCE(EXCLUDED.full_text, documents.full_text),
            ingested_at = EXCLUDED.ingested_at,
            publisher = COALESCE(EXCLUDED.publisher, documents.publisher),
            oa_status = COALESCE(EXCLUDED.oa_status, documents.oa_status),
            doc_type = COALESCE(EXCLUDED.doc_type, documents.doc_type),
            is_review = documents.is_review OR EXCLUDED.is_review,
            is_retracted = documents.is_retracted OR EXCLUDED.is_retracted,
            preprint_of_doi = COALESCE(EXCLUDED.preprint_of_doi, documents.preprint_of_doi),
            full_text_source = COALESCE(EXCLUDED.full_text_source, documents.full_text_source),
            access_route = COALESCE(EXCLUDED.access_route, documents.access_route)
        RETURNING id
        """,
        manifest_id, d["document_id"], d["source"], d["title"], d["abstract"],
        d["full_text"], json.dumps(d["authors"]), d["journal"], d["publication_date"],
        d["year"], d["doi"], d["pmid"], d["pmc_id"], d["mesh_terms"],
        d["keywords"], d["url"], d["license"], d["ingested_at"], json.dumps(d["metadata"]),
        d["publisher"], d["oa_status"], d["doc_type"], d["is_review"], d["is_retracted"],
        d["preprint_of_doi"], d["full_text_source"], d["access_route"],
    )
    return row["id"]


async def upsert_chunks_with_embeddings(
    conn,
    doc_db_id: uuid.UUID,
    manifest_id: uuid.UUID,
    chunks,
    embeddings,
    embedding_model_name: str,
    *,
    replace_existing: bool = True,
):
    """Batch upsert chunks with their embeddings."""
    if replace_existing:
        await conn.execute(
            "DELETE FROM document_chunks WHERE document_id=$1 AND embedding_model=$2",
            doc_db_id,
            embedding_model_name,
        )
    for chunk, embedding in zip(chunks, embeddings):
        embedding_str = "[" + ",".join(str(x) for x in embedding) + "]"
        await conn.execute(
            """
            INSERT INTO document_chunks
                (document_id, manifest_id, chunk_index, chunk_type, content,
                 token_count, embedding_model, embedding, section_label)
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8::vector,$9)
            ON CONFLICT DO NOTHING
            """,
            doc_db_id, manifest_id, chunk.chunk_index, chunk.chunk_type,
            chunk.content, chunk.token_count, embedding_model_name, embedding_str,
            getattr(chunk, "section_label", None),
        )


async def load_existing_pubmed_pmids(conn) -> list[str]:
    rows = await conn.fetch("SELECT pmid FROM documents WHERE pmid IS NOT NULL")
    return [row["pmid"] for row in rows if row["pmid"]]


def validate_index_embedding(embedder) -> None:
    if embedder.dimensions != 768:
        raise ValueError(
            "Indexing currently supports only 768-dimensional embeddings stored in document_chunks.embedding. "
            f"Configured model '{embedder.model_name}' produces {embedder.dimensions} dimensions. "
            "Use PubMedBERT for persistent indexing until a multi-dimension embedding table is added."
        )


def load_pmc_ids(cfg: dict, cache: CorpusCache | None = None) -> list[str]:
    pmc_cfg = cfg.get("pmc", {})
    pmc_ids = list(pmc_cfg.get("ids", []))
    if "pmc_id_file" in pmc_cfg:
        with open(pmc_cfg["pmc_id_file"]) as handle:
            pmc_ids.extend(line.strip() for line in handle if line.strip())
    if pmc_cfg.get("from_cached_pubmed_documents") and cache is not None:
        pmc_ids.extend(doc.pmc_id for doc in cache.read_documents() if doc.pmc_id)
    seen: set[str] = set()
    unique_ids: list[str] = []
    for pmc_id in pmc_ids:
        normalized = str(pmc_id).strip()
        if not normalized:
            continue
        if normalized.upper().startswith("PMC"):
            normalized = f"PMC{normalized[3:]}"
        if normalized not in seen:
            seen.add(normalized)
            unique_ids.append(normalized)
    return unique_ids


def documents_from_cached_pubmed_xml(cache: CorpusCache) -> Iterator[NormalizedDocument]:
    for xml_path in sorted((cache.root / "raw/pubmed/efetch").glob("*.xml")):
        records = PubMedAbstractIngester.parse_efetch_xml(xml_path.read_text())
        relative_path = cache.relative_path(xml_path)
        for article_record in records.get("PubmedArticle", []):
            doc = PubMedAbstractIngester._parse_article(article_record)
            if doc is not None:
                cache.write_document(
                    doc,
                    raw_asset_path=relative_path,
                    access_status="metadata-only",
                    parser_version="pubmed-v1",
                )
                yield doc


def documents_from_cached_pmc_xml(cache: CorpusCache) -> Iterator[NormalizedDocument]:
    for xml_path in sorted((cache.root / "raw/pmc/xml").glob("*.xml")):
        pmc_id = xml_path.stem if xml_path.stem.startswith("PMC") else f"PMC{xml_path.stem}"
        doc = PMCFullTextIngester.parse_xml(xml_path.read_text(), pmc_id)
        cache.write_document(
            doc,
            raw_asset_path=cache.relative_path(xml_path),
            access_status="open-access",
            parser_version="pmc-jats-v1",
        )
        yield doc


def documents_from_cached_discovery(cache: CorpusCache) -> Iterator[NormalizedDocument]:
    """Replay a discovery run from its cached candidates, with no network calls.

    The inclusion filter is not re-applied here: `raw/discovery/candidates.jsonl`
    holds every candidate including the ones that were judged off-topic, and the
    manifest CSV next to it records why. Re-deciding inclusion at replay time
    would silently change the corpus without changing the run that produced it,
    so only the rows the original run kept are replayed — those are exactly the
    ones written to `normalized/documents.jsonl`, which `documents_from_cache`
    prefers. This path is the fallback for a cache that has raw records only.
    """
    from pipelines.discovery.discover import DiscoveryResult, included_candidates
    from pipelines.ingestion.discovery_search import (
        candidate_from_cache_record,
        candidate_to_document,
    )

    candidates = [
        candidate_from_cache_record(record)
        for record in cache.read_jsonl("raw/discovery/candidates.jsonl")
    ]
    # Reuse the live path's filter rather than restating it: an inclusion rule
    # that exists in two places is an inclusion rule that will disagree with
    # itself. Defaults only — replay must not widen what the run decided.
    for candidate in included_candidates(DiscoveryResult(candidates=candidates)):
        doc = candidate_to_document(candidate)
        cache.write_document(
            doc,
            raw_asset_path="raw/discovery/candidates.jsonl",
            access_status="metadata-only",
            parser_version=PARSER_VERSIONS["discovery"],
        )
        yield doc


def documents_from_cached_datasheet_manifest(cache: CorpusCache) -> Iterator[NormalizedDocument]:
    """Replay a manifest-driven run from whatever it fetched.

    The ingester delegates to the PMC and PubMed ingesters, so its raw assets are
    theirs — there is nothing datasheet-shaped to re-parse here.
    """
    yield from documents_from_cached_pmc_xml(cache)
    yield from documents_from_cached_pubmed_xml(cache)


def documents_from_cached_datasheet_fulltext(cache: CorpusCache) -> Iterator[NormalizedDocument]:
    """Rebuild section-labelled documents from the copied text payloads."""
    import json as _json

    from pipelines.acquisition.cache_layout import safe_stem
    from pipelines.ingestion.datasheet_fulltext import (
        FULLTEXT_CACHE_DIR,
        MANIFEST_COPY_PATH,
        text_document,
    )
    from pipelines.ingestion.datasheet_manifest import read_manifest, select_rows

    manifest_path = cache.root / MANIFEST_COPY_PATH
    rows = {
        safe_stem(row.identifier): row
        for row in select_rows(read_manifest(manifest_path))
        if row.identifier
    }

    for text_path in sorted((cache.root / FULLTEXT_CACHE_DIR).glob("*.json")):
        row = rows.get(text_path.stem)
        if row is None:
            # The stem is a one-way hash of an identifier, so a payload with no
            # manifest row cannot be attributed to a paper. Indexing it would
            # produce an uncitable document.
            logger.warning("cached full text has no manifest row: %s", text_path.name)
            continue
        payload = _json.loads(text_path.read_text(encoding="utf-8"))
        doc = text_document(row, payload, asset_path=None)
        cache.write_document(
            doc,
            raw_asset_path=cache.relative_path(text_path),
            access_status=doc.metadata["access_status"],
            parser_version=PARSER_VERSIONS["datasheet_fulltext"],
        )
        yield doc


def documents_from_cached_datasheet_rows(cache: CorpusCache) -> Iterator[NormalizedDocument]:
    from pipelines.ingestion.datasheet_rows import ROWS_CACHE_PATH, row_to_document

    for record in cache.read_jsonl(ROWS_CACHE_PATH):
        doc = row_to_document(
            dict(record.get("row") or {}),
            row_index=int(record.get("row_index", 0)),
            template_name=str(record.get("template", "default")),
            # The original filename, not the cache path: it seeds the row's
            # document_id, so replay must pass what the live run passed.
            source_path=Path(str(record.get("source_file") or ROWS_CACHE_PATH)),
        )
        if doc is None:
            continue
        cache.write_document(
            doc,
            raw_asset_path=ROWS_CACHE_PATH,
            access_status=doc.metadata.get("access_status", "internal"),
            parser_version=PARSER_VERSIONS["datasheet_rows"],
        )
        yield doc


def documents_from_cached_pdf_text(cache: CorpusCache) -> Iterator[NormalizedDocument]:
    for text_path in sorted((cache.root / "raw/pdf/extracted").glob("*.txt")):
        content_hash = text_path.stem
        full_text = text_path.read_text().strip()
        if not full_text:
            continue
        yield NormalizedDocument(
            document_id=f"pdf:{content_hash}",
            source="pdf",
            title=content_hash,
            full_text=full_text,
            license="internal",
            metadata={
                "content_sha256": content_hash,
                "extracted_text_path": cache.relative_path(text_path),
                "access_status": "internal",
                "parser_version": "pdf-v1",
                "text_extraction_status": "cached",
                "ocr_status": "not-needed",
            },
        )


def documents_from_cached_lab_text(cache: CorpusCache, source: str) -> Iterator[NormalizedDocument]:
    for text_path in sorted((cache.root / "raw/lab/extracted").glob("*.txt")):
        content_hash = text_path.stem
        full_text = text_path.read_text().strip()
        if not full_text:
            continue
        yield NormalizedDocument(
            document_id=f"{source}:{content_hash}",
            source=source,
            title=content_hash,
            full_text=full_text,
            license="internal",
            metadata={
                "content_sha256": content_hash,
                "source_system": source,
                "extracted_text_path": cache.relative_path(text_path),
                "access_status": "internal",
                "access_method": "local-export",
                "sensitivity": "internal",
                "parser_version": "local-text-v1",
            },
        )


def documents_from_cache(cache: CorpusCache, source: str) -> list[NormalizedDocument]:
    documents = cache.read_documents()
    if documents:
        return documents

    if source == "pubmed_abstract":
        documents = list(documents_from_cached_pubmed_xml(cache))
    elif source == "pmc_fulltext":
        documents = list(documents_from_cached_pmc_xml(cache))
    elif source == "discovery_search":
        documents = list(documents_from_cached_discovery(cache))
    elif source == "datasheet_manifest":
        documents = list(documents_from_cached_datasheet_manifest(cache))
    elif source == "datasheet_fulltext":
        documents = list(documents_from_cached_datasheet_fulltext(cache))
    elif source == "datasheet_rows":
        documents = list(documents_from_cached_datasheet_rows(cache))
    elif source == "pdf":
        documents = list(documents_from_cached_pdf_text(cache))
    elif source in LOCAL_LAB_SOURCES:
        documents = list(documents_from_cached_lab_text(cache, source))
    else:
        raise ValueError(f"Unknown cache source: {source}")

    if not documents:
        raise FileNotFoundError(
            f"No cached normalized documents or raw assets found in {cache.root}"
        )
    cache.update_counts(normalized_documents=len(documents))
    return documents


def cached_chunks_by_document(cache: CorpusCache | None) -> dict[str, list]:
    if cache is None:
        return {}
    chunks_by_doc: dict[str, list] = {}
    for chunk in cache.read_chunks():
        chunks_by_doc.setdefault(chunk.document_id, []).append(chunk)
    return chunks_by_doc


def batched(items: list, batch_size: int) -> Iterator[list]:
    if batch_size < 1:
        raise ValueError("batch_size must be at least 1")
    for start in range(0, len(items), batch_size):
        yield items[start : start + batch_size]


def open_or_create_cache_from_path(config_path: str | Path, cache_path: str | Path) -> CorpusCache:
    cfg = load_pipeline_config(config_path)
    root = Path(cache_path)
    manifest = CorpusManifest.from_config(cfg, run_id=root.name)
    cache = CorpusCache.open_or_create(root=root, manifest=manifest)
    cache.copy_config(config_path)
    return cache


def create_cache_from_pipeline_config(config_path: str | Path) -> CorpusCache:
    cfg = load_pipeline_config(config_path)
    manifest = CorpusManifest.from_config(cfg)
    cache = CorpusCache.create(manifest=manifest)
    cache.copy_config(config_path)
    return cache


def local_source_config(cfg: dict, source: str) -> dict:
    source_cfg = cfg.get(source, {})
    shared_cfg = cfg.get("local", {})
    return {**shared_cfg, **source_cfg}


def embedding_batch_size_for_source(cfg: dict, source: str) -> int:
    indexing_cfg = cfg.get("indexing", {})
    by_source = indexing_cfg.get("embedding_batch_size_by_source", {})
    return int(by_source.get(source, indexing_cfg.get("embedding_batch_size", 2)))


async def build_index(
    config_path: str,
    from_date: date | None = None,
    year: int | None = None,
    cache_path: str | None = None,
    use_cache: bool = True,
    local_only: bool = False,
    write_queue: bool = False,
    include_cached_fulltext: bool = False,
    progress_callback: ProgressCallback | None = None,
):
    """Main indexing pipeline."""
    import os
    from dotenv import load_dotenv

    load_dotenv()
    cfg = load_pipeline_config(config_path)
    await notify_progress(progress_callback, "Loaded ingestion config", {"config_path": config_path})

    corpus_cfg = cfg["corpus"]
    source = corpus_cfg["source"]
    embedding_model_name = corpus_cfg.get("embedding_model", "pubmedbert")
    cache = open_or_create_cache_from_path(config_path, cache_path) if cache_path else None
    if local_only and cache is None:
        raise ValueError("--local-only requires --cache so no new empty cache is created")
    if cache is None and use_cache:
        cache = create_cache_from_pipeline_config(config_path)
    elif cache is not None:
        logger.info(f"Using corpus cache: {cache.root}")
    if cache is not None and not cache_path:
        logger.info(f"Created corpus cache: {cache.root}")
    await notify_progress(
        progress_callback,
        "Prepared corpus cache",
        {"cache_path": str(cache.root) if cache is not None else None, "source": source},
    )

    runtime_cfg = cfg.get("runtime", {})
    db_url = runtime_cfg.get("database_url") or os.environ["DATABASE_URL"]
    db_url = db_url.replace("+asyncpg", "")  # asyncpg needs no driver prefix
    # Use asyncpg directly for bulk inserts (faster than SQLAlchemy ORM)
    conn = await asyncpg.connect(db_url.replace("postgresql+asyncpg", "postgresql"))
    await notify_progress(progress_callback, "Connected to database", None)

    # Load embedding model
    if embedding_model_name == "pubmedbert":
        from app.embeddings.pubmedbert import PubMedBERTEmbedding
        embedder = PubMedBERTEmbedding()
    elif embedding_model_name == "minilm":
        from app.embeddings.minilm import MiniLMEmbedding
        embedder = MiniLMEmbedding()
    else:
        raise ValueError(f"Unknown embedding model: {embedding_model_name}")

    validate_index_embedding(embedder)
    await notify_progress(
        progress_callback,
        "Loaded embedding model",
        {"embedding_model": embedder.model_name, "dimensions": embedder.dimensions},
    )

    # Create manifest
    manifest_id = uuid.uuid4()
    manifest_name = corpus_cfg["name"]
    now = datetime.now(timezone.utc)

    await conn.execute(
        """
        INSERT INTO ingestion_manifests (id, name, source, embedding_model, created_at)
        VALUES ($1, $2, $3, $4, $5)
        """,
        manifest_id, manifest_name, source, embedding_model_name, now,
    )
    logger.info(f"Created manifest {manifest_id} ({manifest_name})")
    await notify_progress(
        progress_callback,
        "Created ingestion manifest",
        {"manifest_id": str(manifest_id), "manifest_name": manifest_name},
    )

    # Chunker
    chunk_cfg = cfg.get("chunking", {})
    indexing_cfg = cfg.get("indexing", {})
    chunker = Chunker(
        chunk_size=chunk_cfg.get("chunk_size", 512),
        chunk_overlap=chunk_cfg.get("chunk_overlap", 64),
        mode=chunk_mode_for_source(source),
    )
    embedding_batch_size = embedding_batch_size_for_source(cfg, source)
    progress_interval_documents = int(runtime_cfg.get("progress_interval_documents", 100))
    cached_chunks = cached_chunks_by_document(cache)

    if local_only:
        if cache is None:
            raise ValueError("--local-only requires --cache or an enabled corpus cache")
        documents: Iterable[NormalizedDocument] = documents_from_cache(cache, source)
    else:
        if source == "pubmed_abstract":
            ingester = PubMedAbstractIngester.from_config(
                config_path,
                incremental_from=from_date,
                cache=cache,
            )
            if year is not None:
                ingester.year_from = year
                ingester.year_to = year
            documents = ingester.fetch()
        elif source == "pmc_fulltext":
            pmc_ids = load_pmc_ids(cfg, cache=cache)
            if not pmc_ids:
                raise ValueError(
                    "source='pmc_fulltext' requires [pmc].ids, [pmc].pmc_id_file, "
                    "or [pmc].from_cached_pubmed_documents with --cache"
                )
            documents = PMCFullTextIngester(
                pmc_ids=pmc_ids,
                sleep_s=cfg.get("pmc", {}).get("sleep_between_batches_s", 0.5),
                http_attempts=cfg.get("pmc", {}).get("http", {}).get("attempts", 4),
                http_timeout_s=cfg.get("pmc", {}).get("http", {}).get("timeout_s", 30),
                retry_backoff_base_s=cfg.get("pmc", {}).get("http", {}).get("retry_backoff_base_s", 2.0),
                retry_backoff_max_s=cfg.get("pmc", {}).get("http", {}).get("retry_backoff_max_s", 30.0),
                cache=cache,
            ).fetch()
        elif source == "discovery_search":
            documents = DiscoverySearchIngester.from_config(config_path, cache=cache).fetch()
        elif source == "datasheet_manifest":
            documents = DatasheetManifestIngester.from_config(config_path, cache=cache).fetch()
        elif source == "datasheet_fulltext":
            documents = DatasheetFullTextIngester.from_config(config_path, cache=cache).fetch()
        elif source == "datasheet_rows":
            documents = DatasheetRowsIngester.from_config(config_path, cache=cache).fetch()
        elif source == "pdf":
            documents = LocalPDFIngester(
                pdf_dir=cfg.get("pdf", {}).get("dir", "./data/pdfs"),
                cache=cache,
            ).fetch()
        elif source in LOCAL_TEXT_SOURCES:
            local_cfg = local_source_config(cfg, source)
            documents = LocalTextCollectionIngester(
                directory=local_cfg.get("dir", f"./data/{source}"),
                source_name=source,
                cache=cache,
                access_status=local_cfg.get("access_status", "internal"),
                sensitivity=local_cfg.get("sensitivity", "internal"),
                owner=local_cfg.get("owner"),
                retention_policy=local_cfg.get("retention_policy", "internal-project-storage"),
                text_suffixes=local_cfg.get("text_suffixes"),
            ).fetch()
        elif source in LOCAL_TABLE_SOURCES:
            local_cfg = local_source_config(cfg, source)
            documents = LocalTableCollectionIngester(
                directory=local_cfg.get("dir", f"./data/{source}"),
                source_name=source,
                cache=cache,
                access_status=local_cfg.get("access_status", "internal"),
                sensitivity=local_cfg.get("sensitivity", "internal"),
                owner=local_cfg.get("owner"),
                retention_policy=local_cfg.get("retention_policy", "internal-project-storage"),
                max_rows=local_cfg.get("max_rows", 500),
                table_suffixes=local_cfg.get("table_suffixes"),
            ).fetch()
        else:
            raise ValueError(f"Unknown source: {source}")
    await notify_progress(
        progress_callback,
        "Started document ingestion",
        {"mode": "local_only" if local_only else "source"},
    )

    doc_count = 0
    chunk_count = 0
    dedup_cfg = cfg.get("deduplication", {})
    dedup_enabled = bool(dedup_cfg.get("enabled", True))
    # Row-scoped sources describe one paper many times on purpose: a datasheet
    # holds a row per product and per condition, all sharing the paper's PMID and
    # title. Matching on either would keep the first row and silently drop the
    # rest — the exact data the source exists to make answerable. Their identity
    # is the row hash in document_id, which still dedupes an accidental re-read.
    row_scoped = source in ROW_SCOPED_SOURCES
    deduplicator = Deduplicator(
        title_threshold=float(dedup_cfg.get("title_threshold", 0.92)),
        match_on_pmid=bool(dedup_cfg.get("match_on_pmid", True)) and not row_scoped,
        match_on_document_id=bool(dedup_cfg.get("match_on_document_id", True)),
        match_on_title=bool(dedup_cfg.get("match_on_title", True)) and not row_scoped,
    )

    if dedup_enabled and from_date is not None and source == "pubmed_abstract":
        deduplicator.load_existing_pmids(await load_existing_pubmed_pmids(conn))

    try:
        processed_docs: list[NormalizedDocument] = []
        for doc in documents:
            if dedup_enabled and deduplicator.is_duplicate(doc):
                continue

            # Upsert document
            doc_db_id = await upsert_document(conn, doc, manifest_id)
            if dedup_enabled:
                deduplicator.register(doc)
            doc_count += 1
            if write_queue:
                processed_docs.append(doc)

            # Chunk
            chunks = cached_chunks.get(doc.document_id) or chunks_for_document(chunker, doc)
            if not chunks:
                continue
            if cache is not None and doc.document_id not in cached_chunks:
                cache.write_chunks(chunks, embedding_model=embedding_model_name)

            replace_existing_chunks = True
            for chunk_batch in batched(chunks, embedding_batch_size):
                chunk_texts = [c.content for c in chunk_batch]

                import asyncio
                embeddings = await asyncio.to_thread(embedder.embed_documents, chunk_texts)

                await upsert_chunks_with_embeddings(
                    conn,
                    doc_db_id,
                    manifest_id,
                    chunk_batch,
                    embeddings,
                    embedder.model_name,
                    replace_existing=replace_existing_chunks,
                )
                replace_existing_chunks = False
            chunk_count += len(chunks)

            if progress_interval_documents > 0 and doc_count % progress_interval_documents == 0:
                logger.info(f"Processed {doc_count} documents, {chunk_count} chunks")
                await notify_progress(
                    progress_callback,
                    f"Processed {doc_count} documents",
                    {"document_count": doc_count, "chunk_count": chunk_count},
                )

        if write_queue and cache is not None:
            queue_path = cache.root / "reports" / "acquisition_queue.jsonl"
            queue_count = write_acquisition_queue(
                processed_docs,
                queue_path,
                cache=cache,
                include_cached_fulltext=include_cached_fulltext,
            )
            logger.info(f"Wrote {queue_count} acquisition candidates to {queue_path}")
            await notify_progress(
                progress_callback,
                "Wrote acquisition queue",
                {"queue_path": str(queue_path), "queue_count": queue_count},
            )

    finally:
        # Update manifest with final counts
        await conn.execute(
            "UPDATE ingestion_manifests SET document_count=$1, chunk_count=$2 WHERE id=$3",
            doc_count, chunk_count, manifest_id,
        )
        await conn.close()
        if cache is not None:
            cache.update_counts(normalized_documents=doc_count, chunks=chunk_count)
            cache.refresh_counts_from_artifacts()
        logger.info(f"Indexing complete: {doc_count} documents, {chunk_count} chunks")
        logger.info(
            "REMINDER: If this is the first load, create the IVFFlat index:\n"
            "  CREATE INDEX ix_chunks_embedding ON document_chunks\n"
            f"  USING ivfflat (embedding vector_cosine_ops) WITH (lists = {indexing_cfg.get('ivfflat_lists', 100)});"
        )

    await notify_progress(
        progress_callback,
        "Indexing complete",
        {
            "manifest_id": str(manifest_id),
            "document_count": doc_count,
            "chunk_count": chunk_count,
            "cache_path": str(cache.root) if cache is not None else None,
        },
    )
    return {
        "manifest_id": str(manifest_id),
        "document_count": doc_count,
        "chunk_count": chunk_count,
        "cache_path": str(cache.root) if cache is not None else None,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Build or update the RLALab vector index")
    parser.add_argument("--config", required=True, help="Path to corpus TOML config")
    parser.add_argument("--from-date", help="Incremental mode: fetch articles from this date (YYYY-MM-DD)")
    parser.add_argument("--year", type=int, help="Limit to a single year (for testing)")
    parser.add_argument("--cache", help="Existing corpus cache directory to read from or append to")
    parser.add_argument("--no-cache", action="store_true", help="Disable corpus cache writes")
    parser.add_argument("--local-only", action="store_true", help="Read only local cache artifacts; make no network calls")
    parser.add_argument("--write-acquisition-queue", action="store_true", help="Write DOI/PMCID full-text candidates to reports/acquisition_queue.jsonl")
    parser.add_argument(
        "--include-cached-fulltext",
        action="store_true",
        help="When writing an acquisition queue, include documents whose PMC XML is already cached under raw/pmc/xml",
    )
    args = parser.parse_args()

    from_date = date.fromisoformat(args.from_date) if args.from_date else None
    asyncio.run(
        build_index(
            args.config,
            from_date=from_date,
            year=args.year,
            cache_path=args.cache,
            use_cache=not args.no_cache,
            local_only=args.local_only,
            write_queue=args.write_acquisition_queue,
            include_cached_fulltext=args.include_cached_fulltext,
        )
    )
