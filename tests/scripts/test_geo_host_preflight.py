from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest
from scripts.eval import geo_host_preflight
from scripts.eval.geo_visibility import _validate_host_preflight


def _sitemap(urls: list[str]) -> bytes:
    rows = "".join(f"<url><loc>{url}</loc></url>" for url in urls)
    return f'<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{rows}</urlset>'.encode()


def _page(root: Path, relative: str, url: str) -> bytes:
    body = f'<html><head><link rel="canonical" href="{url}"></head></html>'.encode()
    path = root / relative / "index.html"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(body)
    return body


def test_host_preflight_binds_public_fetch_to_frozen_sitemap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    urls = ["https://example.com/geode/", "https://example.com/geode/docs/"]
    expected = tmp_path / "sitemap.xml"
    expected.write_bytes(_sitemap(urls))
    bodies = {
        urls[0]: _page(tmp_path, "", urls[0]),
        urls[1]: _page(tmp_path, "docs", urls[1]),
    }

    def fake_get(url: str, _: float) -> tuple[int, str, str, str, bytes]:
        if url.endswith("sitemap.xml"):
            return 200, url, "application/xml", "", _sitemap(urls)
        if url.endswith("robots.txt"):
            return 404, url, "text/plain", "", b""
        return 200, url, "text/html", "", bodies[url]

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
        "user_agents": ["OAI-SearchBot"],
    }
    assert receipt["schema_id"] == "geode.geo-host-preflight@2"
    assert _validate_host_preflight(receipt, label="test receipt") == 2
    assert receipt["status"] == "pass"
    assert receipt["sitemap_difference"] == {
        "missing": [],
        "unexpected": [],
        "duplicates": [],
    }
    assert all(check["numerator"] == check["denominator"] for check in receipt["checks"].values())
    assert receipt["checks"]["eligible"] == {"numerator": 2, "denominator": 2}


def test_host_preflight_preserves_sitemap_drift(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    expected = tmp_path / "sitemap.xml"
    expected.write_bytes(_sitemap(["https://example.com/geode/"]))
    _page(tmp_path, "", "https://example.com/geode/")
    monkeypatch.setattr(
        geo_host_preflight,
        "_get",
        lambda url, timeout: (
            200,
            url,
            "application/xml",
            "",
            _sitemap(["https://example.com/geode/different/"]),
        ),
    )

    receipt = geo_host_preflight.audit(
        base_url="https://example.com/geode/",
        expected_sitemap=expected,
        timeout=1,
        concurrency=1,
    )

    assert receipt["status"] == "fail"

    tampered = deepcopy(receipt)
    tampered["pages"][0]["checks"]["eligible"] = True
    with pytest.raises(ValueError, match="eligibility is not its check conjunction"):
        _validate_host_preflight(tampered, label="tampered receipt")
    assert receipt["checks"]["sitemap_parity"] == {"numerator": 0, "denominator": 1}
    assert receipt["sitemap_difference"] == {
        "missing": ["https://example.com/geode/"],
        "unexpected": ["https://example.com/geode/different/"],
        "duplicates": [],
    }

    output = tmp_path / "host-preflight.json"
    assert (
        geo_host_preflight.main(
            [
                "--base-url",
                "https://example.com/geode/",
                "--expected-sitemap",
                str(expected),
                "--out",
                str(output),
            ]
        )
        == 1
    )
    assert output.is_file()


def test_host_preflight_counts_only_per_url_conjunctions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    urls = ["https://example.com/geode/", "https://example.com/geode/docs/"]
    expected = tmp_path / "sitemap.xml"
    expected.write_bytes(_sitemap(urls))
    first = _page(tmp_path, "", urls[0])
    second = _page(tmp_path, "docs", urls[1])

    def fake_get(url: str, _: float) -> tuple[int, str, str, str, bytes]:
        if url.endswith("sitemap.xml"):
            return 200, url, "application/xml", "", _sitemap(urls)
        if url.endswith("robots.txt"):
            return 404, url, "text/plain", "", b""
        if url == urls[0]:
            return 200, url, "text/html", "", first + b"<!-- drift -->"
        return 200, url, "text/html", "noindex", second

    monkeypatch.setattr(geo_host_preflight, "_get", fake_get)
    receipt = geo_host_preflight.audit(
        base_url="https://example.com/geode/",
        expected_sitemap=expected,
        timeout=1,
        concurrency=2,
    )

    assert receipt["checks"]["content_parity"] == {"numerator": 1, "denominator": 2}
    assert receipt["checks"]["indexable"] == {"numerator": 1, "denominator": 2}
    assert receipt["checks"]["eligible"] == {"numerator": 0, "denominator": 2}
    assert receipt["status"] == "fail"
