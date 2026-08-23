#!/usr/bin/env python3
"""Audit the deployed GEO target against the frozen exported sitemap."""

from __future__ import annotations

import argparse
import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from html.parser import HTMLParser
from importlib import import_module
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urljoin, urlsplit
from urllib.request import Request, urlopen
from urllib.robotparser import RobotFileParser

from scripts.eval.geo_visibility import _write_exclusive

_element_tree = import_module("defusedxml.ElementTree")


class _Metadata(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.canonicals: list[str] = []
        self.noindex = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        fields = {key.lower(): (value or "") for key, value in attrs}
        if tag.lower() == "link" and "canonical" in fields.get("rel", "").lower().split():
            self.canonicals.append(fields.get("href", ""))
        if tag.lower() == "meta" and fields.get("name", "").lower() in {
            "robots",
            "googlebot",
            "bingbot",
        }:
            directives = {value.strip() for value in fields.get("content", "").lower().split(",")}
            self.noindex = self.noindex or "noindex" in directives


def _urls(xml: bytes) -> list[str]:
    root = _element_tree.fromstring(xml)
    return [str(node.text).strip() for node in root.findall("{*}url/{*}loc") if node.text]


def _digest(urls: list[str]) -> str:
    canonical = json.dumps(urls, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


def _get(url: str, timeout: float) -> tuple[int, str, str, bytes]:
    if urlsplit(url).scheme != "https":
        raise ValueError("GEO public-host requests require https")
    request = Request(  # noqa: S310 -- scheme is restricted above
        url, headers={"User-Agent": "GEODE-GEO-Preflight/1.0"}
    )
    try:
        with urlopen(request, timeout=timeout) as response:  # noqa: S310 -- frozen https origin
            return (
                int(response.status),
                str(response.geturl()),
                str(response.headers.get_content_type()),
                response.read(),
            )
    except HTTPError as exc:
        return int(exc.code), str(exc.geturl()), str(exc.headers.get_content_type()), exc.read()


def audit(
    *, base_url: str, expected_sitemap: Path, timeout: float, concurrency: int
) -> dict[str, object]:
    base = base_url.rstrip("/") + "/"
    base_parts = urlsplit(base)
    if base_parts.scheme != "https" or not base_parts.netloc:
        raise ValueError("GEO public-host preflight requires https")
    expected = _urls(expected_sitemap.read_bytes())
    if not expected or any(
        urlsplit(url).scheme != "https"
        or urlsplit(url).netloc != base_parts.netloc
        or not urlsplit(url).path.startswith(base_parts.path)
        for url in expected
    ):
        raise ValueError("frozen sitemap URLs must stay under the https base URL")
    if len(expected) != len(set(expected)):
        raise ValueError("frozen sitemap URLs must be unique")
    sitemap_url = urljoin(base, "sitemap.xml")
    sitemap_status, _, _, sitemap_body = _get(sitemap_url, timeout)
    if sitemap_status != 200:
        raise ValueError(f"public sitemap returned HTTP {sitemap_status}")
    observed = _urls(sitemap_body)
    observed_set = set(observed)
    missing = [url for url in expected if url not in observed_set]
    unexpected = [url for url in observed if url not in set(expected)]
    duplicates = list(dict.fromkeys(url for url in observed if observed.count(url) > 1))

    robots_url = urljoin(base, "/robots.txt")
    robots_status, _, _, robots_body = _get(robots_url, timeout)
    if robots_status == 404:
        robots = RobotFileParser()
        robots.parse([])
        robots_policy = "allow-by-absence"
    elif robots_status == 200:
        robots = RobotFileParser()
        robots.set_url(robots_url)
        robots.parse(robots_body.decode("utf-8", errors="replace").splitlines())
        robots_policy = "parsed"
    else:
        raise ValueError(f"host-root robots.txt returned HTTP {robots_status}")

    def inspect(url: str) -> tuple[bool, bool, bool, bool, bool]:
        status, _, content_type, body = _get(url, timeout)
        parser = _Metadata()
        if content_type == "text/html":
            parser.feed(body.decode("utf-8", errors="replace"))
        return (
            200 <= status < 300,
            content_type == "text/html",
            parser.canonicals == [url],
            not parser.noindex,
            robots.can_fetch("GEODE-GEO-Preflight", url),
        )

    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        inspected = list(pool.map(inspect, expected))
    names = ("http_2xx", "html", "self_canonical", "indexable", "robots_allowed")
    checks = {
        name: {
            "numerator": sum(int(row[index]) for row in inspected),
            "denominator": len(expected),
        }
        for index, name in enumerate(names)
    }
    checks["sitemap_parity"] = {
        "numerator": len(expected) - len(missing),
        "denominator": len(expected),
    }
    status = (
        "pass"
        if not missing
        and not unexpected
        and not duplicates
        and all(row["numerator"] == row["denominator"] for row in checks.values())
        else "fail"
    )
    return {
        "schema_id": "geode.geo-host-preflight@1",
        "schema_version": 1,
        "status": status,
        "generated_at": datetime.now(UTC).isoformat(),
        "base_url": base,
        "sitemap_url": sitemap_url,
        "urlset_sha256": _digest(expected),
        "observed_urlset_sha256": _digest(observed),
        "sitemap_difference": {
            "missing": missing,
            "unexpected": unexpected,
            "duplicates": duplicates,
        },
        "robots": {"url": robots_url, "status": robots_status, "policy": robots_policy},
        "checks": checks,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--expected-sitemap", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--timeout", type=float, default=15.0)
    parser.add_argument("--concurrency", type=int, default=8)
    args = parser.parse_args(argv)
    if args.timeout <= 0 or args.concurrency <= 0:
        parser.error("timeout and concurrency must be positive")
    payload = audit(
        base_url=args.base_url,
        expected_sitemap=args.expected_sitemap,
        timeout=args.timeout,
        concurrency=args.concurrency,
    )
    _write_exclusive(args.out, payload)
    print(args.out)
    return 0 if payload["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
