from __future__ import annotations

from pathlib import Path

import pytest
from scripts.eval import geo_host_preflight


def _sitemap(urls: list[str]) -> bytes:
    rows = "".join(f"<url><loc>{url}</loc></url>" for url in urls)
    return f'<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{rows}</urlset>'.encode()


def test_host_preflight_binds_public_fetch_to_frozen_sitemap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    urls = ["https://example.com/geode/", "https://example.com/geode/docs/"]
    expected = tmp_path / "sitemap.xml"
    expected.write_bytes(_sitemap(urls))

    def fake_get(url: str, _: float) -> tuple[int, str, str, bytes]:
        if url.endswith("sitemap.xml"):
            return 200, url, "application/xml", _sitemap(urls)
        if url.endswith("robots.txt"):
            return 404, url, "text/plain", b""
        body = f'<html><head><link rel="canonical" href="{url}"></head></html>'.encode()
        return 200, url, "text/html", body

    monkeypatch.setattr(geo_host_preflight, "_get", fake_get)
    receipt = geo_host_preflight.audit(
        base_url="https://example.com/geode/",
        expected_sitemap=expected,
        timeout=1,
        concurrency=2,
    )

    assert receipt["robots"] == {
        "url": "https://example.com/robots.txt",
        "status": 404,
        "policy": "allow-by-absence",
    }
    assert all(check["numerator"] == check["denominator"] for check in receipt["checks"].values())


def test_host_preflight_rejects_sitemap_drift(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    expected = tmp_path / "sitemap.xml"
    expected.write_bytes(_sitemap(["https://example.com/geode/"]))
    monkeypatch.setattr(
        geo_host_preflight,
        "_get",
        lambda url, timeout: (
            200,
            url,
            "application/xml",
            _sitemap(["https://example.com/geode/different/"]),
        ),
    )

    with pytest.raises(ValueError, match="does not match"):
        geo_host_preflight.audit(
            base_url="https://example.com/geode/",
            expected_sitemap=expected,
            timeout=1,
            concurrency=1,
        )
