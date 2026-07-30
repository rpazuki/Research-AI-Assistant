"""Tests for the backend half of S3 and for the S4 spike report.

No network, no database: the ladder and the session are fakes so what is measured
is caching, status mapping and the shape of what the run records.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from types import SimpleNamespace

from app.datasheet import acquisition_service
from pipelines.acquisition import extraction_spike
from pipelines.acquisition.extract_text import ExtractedDocument, Section
from pipelines.acquisition.ladder import STATUS_ASSISTED, STATUS_FETCHED, AcquisitionTarget

JATS = b"""<?xml version="1.0"?>
<article>
  <front><article-meta><title-group><article-title>Po1g-&#916;ku70 engineering</article-title></title-group>
  <abstract><p>Titre 488.7 mg/L.</p></abstract></article-meta></front>
  <body>
    <sec><title>Methods</title><p>Grown at 28 &#176;C.</p></sec>
    <sec><title>Results</title><p>488.7 mg/L.</p></sec>
  </body>
</article>
"""


def candidate(**overrides):
    data = {
        "id": uuid.uuid4(),
        "doi": "10.1021/acsomega.6c03958",
        "pmid": "42428839",
        "pmc_id": "PMC13347637",
        "preprint_doi": None,
        "title": "A paper",
        "publisher": "ACS",
    }
    data.update(overrides)
    return SimpleNamespace(**data)


# ── Asset caching ─────────────────────────────────────────────────────────────


def test_a_doi_becomes_a_collision_free_filename(tmp_path: Path) -> None:
    """DOIs contain slashes; two that sanitise alike must not overwrite each other."""
    first, _ = acquisition_service.cache_paths(tmp_path, "10.1016/j.x.2020.01")
    second, _ = acquisition_service.cache_paths(tmp_path, "10.1016/j-x-2020-01")

    assert "/" not in first.name
    assert first != second


def test_a_stored_asset_is_found_again_and_never_re_requested(tmp_path: Path) -> None:
    """Fetch-once, across runs: the ladder short-circuits on this."""
    acquisition_service.store_asset(tmp_path, "10.1/x", JATS, "xml")

    found = acquisition_service.load_cached_asset(tmp_path, AcquisitionTarget(doi="10.1/x"))

    assert found is not None
    content, content_format, route = found
    assert content == JATS
    assert content_format == "xml"
    assert route == "cache"


def test_an_empty_cached_file_is_not_treated_as_an_asset(tmp_path: Path) -> None:
    """A truncated download must be re-fetched, not served as full text."""
    asset_base, _ = acquisition_service.cache_paths(tmp_path, "10.1/x")
    asset_base.parent.mkdir(parents=True, exist_ok=True)
    asset_base.with_suffix(".xml").write_bytes(b"")

    assert acquisition_service.load_cached_asset(tmp_path, AcquisitionTarget(doi="10.1/x")) is None


def test_a_candidate_with_no_identifier_has_no_cache_entry(tmp_path: Path) -> None:
    assert acquisition_service.load_cached_asset(tmp_path, AcquisitionTarget()) is None


def test_extracted_text_is_stored_with_its_section_labels(tmp_path: Path) -> None:
    """Round 2 restricts extraction to Methods and Results, so the labels must
    survive the round trip to disk."""
    document = ExtractedDocument(
        source_format="xml",
        title="A paper",
        sections=[Section("methods", "Methods", "Grown at 28 °C"), Section("results", "Results", "488.7 mg/L")],
    )

    path = acquisition_service.store_text(tmp_path, "10.1/x", document)
    payload = json.loads(path.read_text(encoding="utf-8"))

    assert [section["label"] for section in payload["sections"]] == ["methods", "results"]
    assert payload["sections"][0]["text"] == "Grown at 28 °C"


def test_the_greek_characters_survive_the_disk_round_trip(tmp_path: Path) -> None:
    document = ExtractedDocument(
        source_format="xml", sections=[Section("methods", "Methods", "Po1g-Δku70 at 28 °C, 5 μmol")]
    )

    path = acquisition_service.store_text(tmp_path, "10.1/x", document)

    assert "Po1g-Δku70" in path.read_text(encoding="utf-8")


# ── Ladder config from settings ───────────────────────────────────────────────


def test_the_ladder_falls_back_to_the_ncbi_contact_for_unpaywall(monkeypatch) -> None:
    """Unpaywall requires an email. Falling back to the address we already have
    means the route works before anyone configures a second one."""
    monkeypatch.setattr(acquisition_service.settings, "unpaywall_email", "", raising=False)
    monkeypatch.setattr(acquisition_service.settings, "ncbi_email", "lab@imperial.ac.uk", raising=False)

    config = acquisition_service.ladder_config_from({})

    assert config.unpaywall_email == "lab@imperial.ac.uk"


def test_a_run_can_narrow_the_ladder() -> None:
    config = acquisition_service.ladder_config_from({"acquisition": {"ladder": ["pmc_oa"]}})
    assert config.routes == ("pmc_oa",)


def test_the_resolver_template_is_optional() -> None:
    """Open item (a) is not a blocker: without it links fall back to doi.org."""
    config = acquisition_service.ladder_config_from({})
    assert config.resolver_url_template in (None, "")


# ── Per-candidate outcome mapping ─────────────────────────────────────────────


def test_a_fetched_paper_records_its_route_asset_and_sections(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        acquisition_service,
        "acquire",
        lambda *args, **kwargs: SimpleNamespace(
            status=STATUS_FETCHED, route="pmc_oa", content=JATS, content_format="xml",
            source_url="https://example/x", license="cc-by", resolver_url=None,
            detail=None, acquired=True,
        ),
    )

    record = acquisition_service._acquire_one(
        candidate(), cache_root=tmp_path, config=None, limiter=None, client=None
    )

    assert record["status"] == STATUS_FETCHED
    assert record["route"] == "pmc_oa"
    assert Path(record["asset_path"]).is_file()
    assert record["section_labels"] == ["abstract", "methods", "results"]
    assert record["fidelity"]["delta_count"] >= 1
    assert record["fidelity"]["looks_corrupted"] is False


def test_a_corrupted_extraction_is_flagged_but_still_kept(tmp_path: Path, monkeypatch) -> None:
    """A Δ that became a `D` renames a strain, so it must be visible — but the
    asset is real and the text is still usable, so it is not a failure."""
    corrupted = JATS.replace("Po1g-&#916;ku70".encode(), b"Po1g-Dku70")
    monkeypatch.setattr(
        acquisition_service,
        "acquire",
        lambda *args, **kwargs: SimpleNamespace(
            status=STATUS_FETCHED, route="unpaywall", content=corrupted, content_format="xml",
            source_url=None, license=None, resolver_url=None, detail=None, acquired=True,
        ),
    )

    record = acquisition_service._acquire_one(
        candidate(), cache_root=tmp_path, config=None, limiter=None, client=None
    )

    assert record["status"] == STATUS_FETCHED
    assert record["fidelity"]["looks_corrupted"] is True
    assert record["fidelity"]["suspicious_strain_names"] == ["Po1g-Dku70"]


def test_an_assisted_paper_carries_its_resolver_link(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        acquisition_service,
        "acquire",
        lambda *args, **kwargs: SimpleNamespace(
            status=STATUS_ASSISTED, route=None, content=None, content_format=None,
            source_url=None, license=None, resolver_url="https://doi.org/10.1/x",
            detail="no automated open-access route", acquired=False,
        ),
    )

    record = acquisition_service._acquire_one(
        candidate(), cache_root=tmp_path, config=None, limiter=None, client=None
    )

    assert record["status"] == STATUS_ASSISTED
    assert record["resolver_url"] == "https://doi.org/10.1/x"
    assert record["asset_path"] is None


# ── S4 spike report ───────────────────────────────────────────────────────────


def measurement(**overrides):
    data = {
        "identifier": "paper", "source_format": "xml", "bytes_on_disk": 1000,
        "total_chars": 40000, "selected_chars": 30000,
        "section_labels": ["abstract", "methods", "results"], "has_methods": True,
        "has_results": True, "tokens_total": 10000, "tokens_selected": 7500,
        "token_method": "provider", "delta_count": 4, "mu_count": 1,
        "critical_characters": 40, "replacement_characters": 0,
        "suspicious_strain_names": [], "looks_corrupted": False, "warnings": [],
    }
    data.update(overrides)
    return extraction_spike.DocumentMeasurement(**data)


def test_the_spike_measures_a_real_document(tmp_path: Path) -> None:
    path = tmp_path / "paper.xml"
    path.write_bytes(JATS)

    result = extraction_spike.measure_document(path)

    assert result.source_format == "xml"
    assert result.has_methods and result.has_results
    assert result.delta_count >= 1
    assert result.token_method == "estimated_from_chars"  # no provider counter passed


def test_the_spike_prefers_xml_when_pdf_loses_structure_or_characters() -> None:
    report = extraction_spike.build_report(
        [
            measurement(source_format="xml"),
            measurement(source_format="pdf", has_methods=False, has_results=False,
                        suspicious_strain_names=["Po1g-Dku70"], looks_corrupted=True),
        ]
    )

    assert report["route_preference"] == "prefer XML"
    assert report["by_format"]["pdf"]["documents_flagged_corrupted"] == 1
    assert report["by_format"]["pdf"]["suspicious_strain_names"] == ["Po1g-Dku70"]


def test_the_spike_reports_the_measurement_against_the_plans_estimate() -> None:
    """The point of the spike: replace §7.1's estimate with a number."""
    report = extraction_spike.build_report([measurement(tokens_selected=8000)])

    assert report["tokens_per_paper_selected_sections"]["median"] == 8000
    assert report["plan_estimate_tokens_per_paper"] == 24000
    assert report["measured_vs_estimate"] == 0.33


def test_a_single_format_sample_says_so_rather_than_claiming_a_comparison() -> None:
    report = extraction_spike.build_report([measurement(source_format="xml")])
    assert "only XML measured" in report["route_preference"]


def test_the_sample_interleaves_formats_so_a_comparison_is_possible(tmp_path: Path) -> None:
    """Alphabetical order would make a 20-document sample accidentally all XML."""
    assets = tmp_path / "assets"
    assets.mkdir()
    for index in range(6):
        (assets / f"a{index}.xml").write_bytes(JATS)
    for index in range(6):
        (assets / f"z{index}.pdf").write_bytes(b"%PDF-")

    picked = extraction_spike.collect_assets(tmp_path, limit=6)

    assert [path.suffix for path in picked].count(".pdf") == 3
    assert [path.suffix for path in picked].count(".xml") == 3


def test_an_empty_cache_is_reported_not_silently_measured(tmp_path: Path) -> None:
    (tmp_path / "assets").mkdir()
    assert extraction_spike.collect_assets(tmp_path, limit=20) == []
