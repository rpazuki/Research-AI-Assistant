from __future__ import annotations

from types import SimpleNamespace

from pipelines.processing.deduplicator import Deduplicator


def test_deduplicator_can_disable_title_matching() -> None:
    deduplicator = Deduplicator(match_on_title=False)
    first = SimpleNamespace(document_id="a", pmid=None, title="Yarrowia lipid production")
    second = SimpleNamespace(document_id="b", pmid=None, title="Yarrowia lipid production")

    deduplicator.register(first)

    assert deduplicator.is_duplicate(second) is False


def test_deduplicator_uses_configurable_fuzzy_title_threshold() -> None:
    deduplicator = Deduplicator(title_threshold=0.8)
    first = SimpleNamespace(document_id="a", pmid=None, title="Yarrowia lipolytica lipid production")
    second = SimpleNamespace(document_id="b", pmid=None, title="Yarrowia lipolytica lipids production")

    deduplicator.register(first)

    assert deduplicator.is_duplicate(second) is True
