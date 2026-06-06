from __future__ import annotations

from pipelines.ingestion.lab_sources import LocalTableCollectionIngester, LocalTextCollectionIngester


def test_local_text_suffixes_are_configurable(tmp_path) -> None:
    source_dir = tmp_path / "protocols"
    source_dir.mkdir()
    (source_dir / "included.rst").write_text("content", encoding="utf-8")
    (source_dir / "ignored.md").write_text("content", encoding="utf-8")

    ingester = LocalTextCollectionIngester(
        directory=str(source_dir),
        source_name="lab_protocols",
        text_suffixes=[".rst"],
    )

    docs = list(ingester.fetch())

    assert [doc.title for doc in docs] == ["included"]


def test_local_table_suffixes_are_configurable(tmp_path) -> None:
    source_dir = tmp_path / "tables"
    source_dir.mkdir()
    (source_dir / "included.psv").write_text("a|b\n1|2\n", encoding="utf-8")
    (source_dir / "ignored.csv").write_text("a,b\n1,2\n", encoding="utf-8")

    ingester = LocalTableCollectionIngester(
        directory=str(source_dir),
        source_name="inventories",
        table_suffixes=[".psv"],
        max_rows=1,
    )

    docs = list(ingester.fetch())

    assert [doc.title for doc in docs] == ["included"]
