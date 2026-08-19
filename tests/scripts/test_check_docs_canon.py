from pathlib import Path

from scripts.check_docs_canon import scan_file


def test_retired_product_path_requires_explicit_waiver(tmp_path: Path) -> None:
    page = tmp_path / "page.tsx"
    page.write_text(
        "plugins/petri_audit/runner.py\nplugins/petri_audit is a legacy facade // canon-ok\n",
        encoding="utf-8",
    )

    assert [(line, label) for line, label, _text in scan_file(page, frozenset())] == [
        (1, "retired-product-path")
    ]
