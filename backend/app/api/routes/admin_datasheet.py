"""Admin datasheet endpoints (round 1: template management)."""

import uuid

from fastapi import APIRouter, HTTPException, Query, Response, status

from app.api.deps import AdminUser, DBSession
from app.datasheet.admin_service import (
    DatasheetTemplateError,
    create_template,
    enabled_column_keys,
    extraction_schema_for_template,
    get_template,
    list_templates,
    seed_default_template,
    template_column_rows,
    update_template,
)
from app.datasheet.acquisition_service import assisted_links_csv
from app.datasheet.discovery_service import (
    DatasheetRunError,
    count_candidates,
    create_run,
    get_run,
    list_candidates,
    list_runs,
    manifest_csv_for_run,
    request_cancel,
)
from app.datasheet.lookup_service import (
    PRODUCT_CLASSES,
    resolve_organism_seed,
    resolve_product_seed,
    suggest_organisms,
    suggest_products,
)
from app.db.models import DatasheetCandidate, DatasheetRun, DatasheetTemplate
from app.schemas.datasheet import (
    DatasheetCandidateResponse,
    DatasheetExtractionSchemaResponse,
    DatasheetRunCreate,
    DatasheetRunDetail,
    DatasheetRunSummary,
    DatasheetTemplateCreate,
    DatasheetTemplateDetail,
    DatasheetTemplateSummary,
    DatasheetTemplateUpdate,
    OrganismLookupResponse,
    OrganismSeedResponse,
    OrganismSuggestionResponse,
    ProductLookupResponse,
    ProductSeedResponse,
    ProductSuggestionResponse,
)

router = APIRouter(prefix="/admin/datasheets", tags=["admin-datasheets"])


@router.get("/templates", response_model=list[DatasheetTemplateSummary])
async def list_datasheet_templates(
    _admin: AdminUser, db: DBSession
) -> list[DatasheetTemplateSummary]:
    """List templates. Seeds the default 17-column template on first call so a
    fresh database is usable without a separate provisioning step."""
    templates = await list_templates(db)
    if not templates:
        await seed_default_template(db)
        templates = await list_templates(db)
    return [_build_summary(template) for template in templates]


@router.post(
    "/templates",
    response_model=DatasheetTemplateDetail,
    status_code=status.HTTP_201_CREATED,
)
async def create_datasheet_template(
    body: DatasheetTemplateCreate, admin: AdminUser, db: DBSession
) -> DatasheetTemplateDetail:
    try:
        template = await create_template(
            db,
            name=body.name,
            description=body.description,
            is_default=body.is_default,
            columns=[column.model_dump() for column in body.columns],
            created_by_user_id=admin.id,
        )
    except DatasheetTemplateError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return _build_detail(template)


@router.post(
    "/templates/seed-default",
    response_model=DatasheetTemplateDetail,
)
async def seed_default_datasheet_template(
    _admin: AdminUser, db: DBSession
) -> DatasheetTemplateDetail:
    """Idempotently create the 17-column default template. An existing template is
    returned untouched so admin edits are never reset."""
    template, _created = await seed_default_template(db)
    return _build_detail(template)


@router.get("/templates/{template_name}", response_model=DatasheetTemplateDetail)
async def get_datasheet_template(
    template_name: str, _admin: AdminUser, db: DBSession
) -> DatasheetTemplateDetail:
    template = await _get_template_or_404(db, template_name)
    return _build_detail(template)


@router.put("/templates/{template_name}", response_model=DatasheetTemplateDetail)
async def update_datasheet_template(
    template_name: str,
    body: DatasheetTemplateUpdate,
    _admin: AdminUser,
    db: DBSession,
) -> DatasheetTemplateDetail:
    try:
        template = await update_template(
            db,
            name=template_name,
            description=body.description,
            is_default=body.is_default,
            columns=(
                [column.model_dump() for column in body.columns]
                if body.columns is not None
                else None
            ),
        )
    except DatasheetTemplateError as exc:
        message = str(exc)
        code = (
            status.HTTP_404_NOT_FOUND
            if "not found" in message.lower()
            else status.HTTP_400_BAD_REQUEST
        )
        raise HTTPException(status_code=code, detail=message) from exc
    return _build_detail(template)


@router.get(
    "/templates/{template_name}/extraction-schema",
    response_model=DatasheetExtractionSchemaResponse,
)
async def get_datasheet_extraction_schema(
    template_name: str, _admin: AdminUser, db: DBSession
) -> DatasheetExtractionSchemaResponse:
    """The JSON schema the extraction pass would send for this template — the
    feedback loop for an admin who has just added a column."""
    template = await _get_template_or_404(db, template_name)
    return DatasheetExtractionSchemaResponse(
        template_name=template.name,
        template_version=int(template.version or 1),
        enabled_columns=enabled_column_keys(template),
        json_schema=extraction_schema_for_template(template),
    )


# ── Seed lookup (S1) ──────────────────────────────────────────────────────────


@router.get("/lookup/organism", response_model=OrganismLookupResponse)
async def lookup_organism(
    _admin: AdminUser,
    q: str = Query(default="", max_length=200, description="Name, synonym or taxid"),
    taxid: int | None = Query(default=None, ge=1, description="Resolve a known taxid"),
    limit: int = Query(default=10, ge=1, le=25),
    resolve: bool = Query(
        default=False,
        description="Also resolve the best match to a full seed (one extra upstream call)",
    ),
) -> OrganismLookupResponse:
    """Organism typeahead and seed resolution.

    `q` alone lists suggestions — the cheap path the wizard calls per keystroke.
    `taxid`, or `q` with `resolve=true`, returns the full seed with the synonym
    set that discovery queries with.
    """
    if not q.strip() and taxid is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Provide q or taxid",
        )

    suggestions: list[OrganismSuggestionResponse] = []
    if taxid is None:
        suggestions = [
            OrganismSuggestionResponse(
                taxid=item.taxid,
                scientific_name=item.scientific_name,
                rank=item.rank,
                common_name=item.common_name,
            )
            for item in await suggest_organisms(q, limit=limit)
        ]

    seed = None
    if taxid is not None or resolve:
        resolved = await resolve_organism_seed(query=q or None, taxid=taxid)
        if resolved is not None:
            seed = OrganismSeedResponse(
                taxid=resolved.taxid,
                scientific_name=resolved.scientific_name,
                rank=resolved.rank,
                synonyms=list(resolved.synonyms),
                common_names=list(resolved.common_names),
                lineage=list(resolved.lineage),
                search_terms=list(resolved.search_terms),
            )

    return OrganismLookupResponse(query=q, suggestions=suggestions, seed=seed)


@router.get("/lookup/product", response_model=ProductLookupResponse)
async def lookup_product(
    _admin: AdminUser,
    q: str = Query(default="", max_length=200, description="Compound name, synonym or CID"),
    cid: int | None = Query(default=None, ge=1, description="Resolve a known PubChem CID"),
    limit: int = Query(default=10, ge=1, le=25),
    resolve: bool = Query(
        default=False,
        description="Also resolve the best match to a full seed (two extra upstream calls)",
    ),
) -> ProductLookupResponse:
    """Bioproduct typeahead and seed resolution.

    The response always carries the controlled `Standard Product Class` vocabulary
    so the wizard can offer it when no rule matched, without a second request.
    """
    if not q.strip() and cid is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Provide q or cid",
        )

    suggestions: list[ProductSuggestionResponse] = []
    if cid is None:
        suggestions = [
            ProductSuggestionResponse(name=item.name, cid=item.cid)
            for item in await suggest_products(q, limit=limit)
        ]

    seed = None
    if cid is not None or resolve:
        resolved = await resolve_product_seed(query=q or None, cid=cid)
        if resolved is not None:
            seed = ProductSeedResponse(
                cid=resolved.cid,
                preferred_name=resolved.preferred_name,
                synonyms=list(resolved.synonyms),
                chebi_id=resolved.chebi_id,
                inchikey=resolved.inchikey,
                molecular_formula=resolved.molecular_formula,
                molecular_weight=resolved.molecular_weight,
                iupac_name=resolved.iupac_name,
                chebi_label=resolved.chebi_label,
                chebi_definition=resolved.chebi_definition,
                product_class=resolved.product_class,
                product_class_evidence=resolved.product_class_evidence,
                search_terms=list(resolved.search_terms),
            )

    return ProductLookupResponse(
        query=q,
        suggestions=suggestions,
        seed=seed,
        product_classes=list(PRODUCT_CLASSES),
    )




# ── Runs (S2: discovery) ──────────────────────────────────────────────────────


@router.post("/runs", response_model=DatasheetRunDetail, status_code=status.HTTP_201_CREATED)
async def create_datasheet_run(
    body: DatasheetRunCreate, admin: AdminUser, db: DBSession
) -> DatasheetRunDetail:
    """Queue a run. The worker picks it up and drives discovery.

    Nothing is searched inline: a full discovery pass is thousands of upstream
    records over several minutes, which is not a request.
    """
    try:
        run = await create_run(
            db,
            name=body.name,
            seed_kind=body.seed_kind,
            organism_name=body.organism_name,
            organism_taxid=body.organism_taxid,
            organism_synonyms=body.organism_synonyms,
            product_term=body.product_term,
            product_ids=body.product_ids,
            product_synonyms=body.product_synonyms,
            product_classes=body.product_classes,
            year_from=body.year_from,
            year_to=body.year_to,
            template_name=body.template_name,
            config={
                "discovery": {
                    "sources": body.sources or None,
                    "max_records_per_source": body.max_records_per_source,
                    "include_mentions": body.include_mentions,
                    "include_reviews": body.include_reviews,
                    "check_retraction_notices": body.check_retraction_notices,
                }
            },
            requested_by_user_id=admin.id,
        )
    except DatasheetRunError as exc:
        message = str(exc)
        code = (
            status.HTTP_404_NOT_FOUND if "not found" in message.lower() else status.HTTP_400_BAD_REQUEST
        )
        raise HTTPException(status_code=code, detail=message) from exc

    return await _build_run_detail(db, run)


@router.get("/runs", response_model=list[DatasheetRunSummary])
async def list_datasheet_runs(
    _admin: AdminUser, db: DBSession, limit: int = Query(default=50, ge=1, le=200)
) -> list[DatasheetRunSummary]:
    return [_build_run_summary(run) for run in await list_runs(db, limit=limit)]


@router.get("/runs/{run_id}", response_model=DatasheetRunDetail)
async def get_datasheet_run(run_id: uuid.UUID, _admin: AdminUser, db: DBSession) -> DatasheetRunDetail:
    run = await _get_run_or_404(db, run_id)
    return await _build_run_detail(db, run)


@router.post("/runs/{run_id}/cancel", response_model=DatasheetRunDetail)
async def cancel_datasheet_run(
    run_id: uuid.UUID, _admin: AdminUser, db: DBSession
) -> DatasheetRunDetail:
    run = await request_cancel(db, run_id)
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found")
    return await _build_run_detail(db, run)


@router.get("/runs/{run_id}/candidates", response_model=list[DatasheetCandidateResponse])
async def list_datasheet_run_candidates(
    run_id: uuid.UUID,
    _admin: AdminUser,
    db: DBSession,
    relevance: str | None = Query(default=None, max_length=20),
    acquisition_status: str | None = Query(default=None, max_length=30),
    limit: int = Query(default=200, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
) -> list[DatasheetCandidateResponse]:
    await _get_run_or_404(db, run_id)
    rows = await list_candidates(
        db,
        run_id,
        relevance=relevance,
        acquisition_status=acquisition_status,
        limit=limit,
        offset=offset,
    )
    return [_build_candidate(row) for row in rows]


@router.get("/runs/{run_id}/manifest.csv")
async def download_datasheet_run_manifest(
    run_id: uuid.UUID, _admin: AdminUser, db: DBSession
) -> Response:
    """Every candidate with the decision made about it and the reason for it."""
    run = await _get_run_or_404(db, run_id)
    csv_text = await manifest_csv_for_run(db, run_id)
    filename = f"discovery-manifest-{run.name}-{run_id}.csv".replace(" ", "_")
    return Response(
        content=csv_text,
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )



@router.get("/runs/{run_id}/acquisition-links.csv")
async def download_datasheet_assisted_links(
    run_id: uuid.UUID, _admin: AdminUser, db: DBSession
) -> Response:
    """The work list for assisted acquisition: one row per paper to fetch by hand.

    Papers reach this list because every automated route was exhausted — usually a
    paywall, sometimes publisher bot protection. Downloading them is a human task
    by design: a scripted SSO login is what gets an institution's IP range blocked.
    """
    run = await _get_run_or_404(db, run_id)
    csv_text = await assisted_links_csv(db, run_id)
    filename = f"assisted-acquisition-{run.name}-{run_id}.csv".replace(" ", "_")
    return Response(
        content=csv_text,
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ── Helpers ───────────────────────────────────────────────────────────────────

async def _get_template_or_404(db: DBSession, template_name: str) -> DatasheetTemplate:
    template = await get_template(db, template_name)
    if template is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Template '{template_name}' not found",
        )
    return template


def _build_summary(template: DatasheetTemplate) -> DatasheetTemplateSummary:
    columns = template_column_rows(template)
    return DatasheetTemplateSummary(
        id=template.id,
        name=template.name,
        version=int(template.version or 1),
        description=template.description,
        is_default=bool(template.is_default),
        column_count=len(columns),
        enabled_column_count=sum(1 for column in columns if column["enabled"]),
        created_at=template.created_at,
        updated_at=template.updated_at,
    )


def _build_detail(template: DatasheetTemplate) -> DatasheetTemplateDetail:
    """Built explicitly rather than via model_validate: the ORM relationship may be
    unloaded and lazy-loading inside Pydantic validation raises in async contexts
    (see mistakes.md)."""
    summary = _build_summary(template)
    columns = sorted(template.columns, key=lambda c: c.order_index)
    return DatasheetTemplateDetail(
        **summary.model_dump(),
        columns=[
            {
                "id": column.id,
                "key": column.key,
                "label": column.label,
                "kind": column.kind,
                "order_index": column.order_index,
                "vocabulary": list(column.vocabulary or []),
                "extraction_hint": column.extraction_hint,
                "source_hint": column.source_hint,
                "required": bool(column.required),
                "enabled": bool(column.enabled),
            }
            for column in columns
        ],
    )


async def _get_run_or_404(db: DBSession, run_id: uuid.UUID) -> DatasheetRun:
    run = await get_run(db, run_id)
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Run not found")
    return run


def _build_run_summary(run: DatasheetRun) -> DatasheetRunSummary:
    return DatasheetRunSummary(
        id=run.id,
        name=run.name,
        status=run.status,
        phase=run.phase,
        seed_kind=run.seed_kind,
        organism_name=run.organism_name,
        organism_taxid=run.organism_taxid,
        product_term=run.product_term,
        year_from=run.year_from,
        year_to=run.year_to,
        candidate_count=run.candidate_count,
        progress_message=run.progress_message,
        error=run.error,
        created_at=run.created_at,
        started_at=run.started_at,
        finished_at=run.finished_at,
    )


async def _build_run_detail(db: DBSession, run: DatasheetRun) -> DatasheetRunDetail:
    """Built explicitly, never via model_validate on the ORM object: the candidate
    relationship may be unloaded and lazy-loading inside Pydantic validation raises
    in async contexts (see mistakes.md)."""
    snapshot = run.template_snapshot or {}
    config = run.config_snapshot or {}
    return DatasheetRunDetail(
        **_build_run_summary(run).model_dump(),
        organism_synonyms=list(run.organism_synonyms or []),
        product_synonyms=list(run.product_synonyms or []),
        product_classes=list(run.product_classes or []),
        template_name=snapshot.get("name"),
        template_version=snapshot.get("version"),
        log_tail=run.log_tail,
        candidate_counts=await count_candidates(db, run.id),
        discovery_summary=config.get("discovery_result"),
        acquisition_summary=config.get("acquisition_result"),
        acquired_count=run.acquired_count,
    )


def _build_candidate(row: DatasheetCandidate) -> DatasheetCandidateResponse:
    return DatasheetCandidateResponse(
        id=row.id,
        doi=row.doi,
        pmid=row.pmid,
        pmc_id=row.pmc_id,
        title=row.title,
        journal=row.journal,
        publisher=row.publisher,
        year=row.year,
        found_in=list(row.found_in or []),
        oa_status=row.oa_status,
        license=row.license,
        is_preprint=bool(row.is_preprint),
        preprint_doi=row.preprint_doi,
        version_of_record_doi=row.version_of_record_doi,
        doc_type=row.doc_type,
        is_review=bool(row.is_review),
        is_retracted=bool(row.is_retracted),
        relevance=row.relevance,
        relevance_reason=row.relevance_reason,
        acquisition_status=row.acquisition_status,
        acquisition_route=row.acquisition_route,
        dedupe_group=row.dedupe_group,
        possible_duplicate_of=list(row.possible_duplicate_of or []),
        duplicate_evidence=row.duplicate_evidence,
        notes=row.notes,
    )
