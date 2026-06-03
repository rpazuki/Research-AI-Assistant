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
from pipelines.ingestion.lab_sources import (
    LocalTableCollectionIngester,
    LocalTextCollectionIngester,
)
from pipelines.corpus_cache import (
    CorpusCache,
    CorpusManifest,
    create_cache_from_config,
    load_toml,
    write_acquisition_queue,
)
from pipelines.processing.chunker import Chunker
from pipelines.processing.deduplicator import Deduplicator
from pipelines.processing.normalizer import NormalizedDocument

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

LOCAL_TEXT_SOURCES = {"lab_protocols"}
LOCAL_TABLE_SOURCES = {"eln_lims", "inventories", "omics_summaries"}
LOCAL_LAB_SOURCES = LOCAL_TEXT_SOURCES | LOCAL_TABLE_SOURCES

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
    """Upsert a document and return its database UUID."""
    d = doc.to_db_dict()
    row = await conn.fetchrow(
        """
        INSERT INTO documents
            (manifest_id, document_id, source, title, abstract, full_text, authors,
             journal, publication_date, year, doi, pmid, pmc_id, mesh_terms, keywords,
             url, license, ingested_at, metadata)
        VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,$18,$19)
        ON CONFLICT (document_id) DO UPDATE SET
            title = EXCLUDED.title,
            abstract = EXCLUDED.abstract,
            full_text = EXCLUDED.full_text,
            ingested_at = EXCLUDED.ingested_at
        RETURNING id
        """,
        manifest_id, d["document_id"], d["source"], d["title"], d["abstract"],
        d["full_text"], json.dumps(d["authors"]), d["journal"], d["publication_date"],
        d["year"], d["doi"], d["pmid"], d["pmc_id"], d["mesh_terms"],
        d["keywords"], d["url"], d["license"], d["ingested_at"], json.dumps(d["metadata"]),
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
                 token_count, embedding_model, embedding)
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8::vector)
            ON CONFLICT DO NOTHING
            """,
            doc_db_id, manifest_id, chunk.chunk_index, chunk.chunk_type,
            chunk.content, chunk.token_count, embedding_model_name, embedding_str,
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
    cfg = load_toml(config_path)
    root = Path(cache_path)
    manifest = CorpusManifest.from_config(cfg, run_id=root.name)
    cache = CorpusCache.open_or_create(root=root, manifest=manifest)
    cache.copy_config(config_path)
    return cache


def local_source_config(cfg: dict, source: str) -> dict:
    source_cfg = cfg.get(source, {})
    shared_cfg = cfg.get("local", {})
    return {**shared_cfg, **source_cfg}


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
    cfg = load_toml(config_path)
    await notify_progress(progress_callback, "Loaded ingestion config", {"config_path": config_path})

    corpus_cfg = cfg["corpus"]
    source = corpus_cfg["source"]
    embedding_model_name = corpus_cfg.get("embedding_model", "pubmedbert")
    cache = open_or_create_cache_from_path(config_path, cache_path) if cache_path else None
    if local_only and cache is None:
        raise ValueError("--local-only requires --cache so no new empty cache is created")
    if cache is None and use_cache:
        cache = create_cache_from_config(config_path)
    elif cache is not None:
        logger.info(f"Using corpus cache: {cache.root}")
    if cache is not None and not cache_path:
        logger.info(f"Created corpus cache: {cache.root}")
    await notify_progress(
        progress_callback,
        "Prepared corpus cache",
        {"cache_path": str(cache.root) if cache is not None else None, "source": source},
    )

    # Load environment
    import os
    from dotenv import load_dotenv
    load_dotenv()

    db_url = os.environ["DATABASE_URL"].replace("+asyncpg", "")  # asyncpg needs no driver prefix
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
        mode="abstract" if "abstract" in source else "fulltext",
    )
    embedding_batch_size = indexing_cfg.get(
        "embedding_batch_size",
        32 if source == "pubmed_abstract" else 2,
    )
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
                cache=cache,
            ).fetch()
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
    deduplicator = Deduplicator()

    if from_date is not None and source == "pubmed_abstract":
        deduplicator.load_existing_pmids(await load_existing_pubmed_pmids(conn))

    try:
        processed_docs: list[NormalizedDocument] = []
        for doc in documents:
            if deduplicator.is_duplicate(doc):
                continue

            # Upsert document
            doc_db_id = await upsert_document(conn, doc, manifest_id)
            deduplicator.register(doc)
            doc_count += 1
            if write_queue:
                processed_docs.append(doc)

            # Chunk
            chunks = cached_chunks.get(doc.document_id) or chunker.chunk_document(doc)
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

            if doc_count % 100 == 0:
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
            "  USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);"
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
