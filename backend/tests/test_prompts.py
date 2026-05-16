"""Unit tests for app/rag/prompts.py."""

from __future__ import annotations

from app.rag.prompts import build_context_block, get_system_prompt


# ── get_system_prompt ─────────────────────────────────────────────────────────

def test_get_system_prompt_researcher_mode_contains_lab_name() -> None:
    prompt = get_system_prompt("researcher")
    assert "Rodrigo Ledesma-Amaro" in prompt
    assert "Yarrowia lipolytica" in prompt


def test_get_system_prompt_lab_manager_mode_differs_from_researcher() -> None:
    researcher = get_system_prompt("researcher")
    lab_manager = get_system_prompt("lab_manager")
    assert researcher != lab_manager


def test_get_system_prompt_unknown_mode_falls_back_to_researcher() -> None:
    fallback = get_system_prompt("nonexistent_mode")
    researcher = get_system_prompt("researcher")
    assert fallback == researcher


def test_get_system_prompt_researcher_forbids_fabrication() -> None:
    prompt = get_system_prompt("researcher")
    assert "Never fabricate" in prompt or "never fabricate" in prompt.lower()


# ── build_context_block ───────────────────────────────────────────────────────

def test_build_context_block_empty_returns_no_documents_message() -> None:
    result = build_context_block([])
    assert "No relevant documents" in result


def test_build_context_block_includes_pmid_in_output() -> None:
    chunk = {"pmid": "12345", "doi": None, "title": "Test paper", "journal": "Nature", "year": 2024, "content": "Some content."}
    result = build_context_block([chunk])
    assert "PMID: 12345" in result
    assert "Some content." in result


def test_build_context_block_includes_doi_when_no_pmid() -> None:
    chunk = {"pmid": None, "doi": "10.1/test", "title": "Paper", "journal": "Science", "year": 2023, "content": "Body."}
    result = build_context_block([chunk])
    assert "DOI: 10.1/test" in result


def test_build_context_block_numbers_documents_sequentially() -> None:
    chunks = [
        {"pmid": "1", "doi": None, "title": "A", "journal": "J", "year": 2020, "content": "c1"},
        {"pmid": "2", "doi": None, "title": "B", "journal": "J", "year": 2021, "content": "c2"},
    ]
    result = build_context_block(chunks)
    assert "[Document 1]" in result
    assert "[Document 2]" in result


def test_build_context_block_handles_missing_metadata_gracefully() -> None:
    chunk = {"pmid": None, "doi": None, "title": None, "journal": None, "year": None, "content": "content only"}
    result = build_context_block([chunk])
    assert "Source metadata unavailable" in result
    assert "content only" in result


def test_build_context_block_wraps_with_markers() -> None:
    result = build_context_block([{"pmid": "1", "doi": None, "title": "T", "journal": "J", "year": 2024, "content": "c"}])
    assert "--- RETRIEVED CONTEXT ---" in result
    assert "--- END OF CONTEXT ---" in result
