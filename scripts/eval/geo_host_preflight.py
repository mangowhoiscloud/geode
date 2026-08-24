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
from typing import Any
from urllib.error import HTTPError
from urllib.parse import urljoin, urlsplit
from urllib.request import Request, urlopen
from urllib.robotparser import RobotFileParser

from scripts.eval.geo_visibility import _write_exclusive

_element_tree = import_module("defusedxml.ElementTree")
_MAX_RESPONSE_BYTES = 5 * 1024 * 1024


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
            "oai-searchbot",
        }:
            self.noindex = self.noindex or _has_noindex(fields.get("content", ""))


def _urls(xml: bytes) -> list[str]:
    root = _element_tree.fromstring(xml)
    return [str(node.text).strip() for node in root.findall("{*}url/{*}loc") if node.text]


def _digest(urls: list[str]) -> str:
    canonical = json.dumps(urls, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


def _get(url: str, timeout: float) -> tuple[int, str, str, str, bytes]:
    if urlsplit(url).scheme != "https":
        raise ValueError("GEO public-host requests require https")
    request = Request(  # noqa: S310 -- scheme is restricted above
        url, headers={"User-Agent": "GEODE-GEO-Preflight/1.0"}
    )
    try:
        with urlopen(request, timeout=timeout) as response:  # noqa: S310 -- frozen https origin
            body = response.read(_MAX_RESPONSE_BYTES + 1)
            if len(body) > _MAX_RESPONSE_BYTES:
                raise ValueError(f"GEO public-host response exceeds {_MAX_RESPONSE_BYTES} bytes")
            return (
                int(response.status),
                str(response.geturl()),
                str(response.headers.get_content_type()),
                ", ".join(response.headers.get_all("X-Robots-Tag", [])),
                body,
            )
    except HTTPError as exc:
        body = exc.read(_MAX_RESPONSE_BYTES + 1)
        if len(body) > _MAX_RESPONSE_BYTES:
            raise ValueError(
                f"GEO public-host response exceeds {_MAX_RESPONSE_BYTES} bytes"
            ) from exc
        return (
            int(exc.code),
            str(exc.geturl()),
            str(exc.headers.get_content_type()),
            ", ".join(exc.headers.get_all("X-Robots-Tag", [])),
            body,
        )


def _has_noindex(value: str) -> bool:
    return any(
        directive.strip() == "noindex"
        for field in value.casefold().split(",")
        for directive in field.rsplit(":", 1)[-1].split()
    )


def _local_page(root: Path, base_path: str, url: str) -> Path:
    relative = urlsplit(url).path.removeprefix(base_path).strip("/")
    resolved_root = root.resolve()
    page = (resolved_root / relative / "index.html").resolve()
    if not page.is_relative_to(resolved_root):
        raise ValueError("frozen sitemap page escapes the exported root")
    return page


def audit(
    *,
    base_url: str,
    expected_sitemap: Path,
    timeout: float,
    concurrency: int,
    expected_root: Path | None = None,
    crawler_user_agents: tuple[str, ...] = ("OAI-SearchBot",),
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
    if (
        not crawler_user_agents
        or len(crawler_user_agents) != len(set(crawler_user_agents))
        or any(not value.strip() or len(value) > 128 for value in crawler_user_agents)
    ):
        raise ValueError("GEO crawler user agents must be unique non-empty values")
    local_root = (expected_root or expected_sitemap.parent).resolve()
    sitemap_url = urljoin(base, "sitemap.xml")
    sitemap_status, _, _, _, sitemap_body = _get(sitemap_url, timeout)
    if sitemap_status != 200:
        raise ValueError(f"public sitemap returned HTTP {sitemap_status}")
    observed = _urls(sitemap_body)
    observed_set = set(observed)
    missing = [url for url in expected if url not in observed_set]
    unexpected = [url for url in observed if url not in set(expected)]
    duplicates = list(dict.fromkeys(url for url in observed if observed.count(url) > 1))

    robots_url = urljoin(base, "/robots.txt")
    robots_status, _, _, _, robots_body = _get(robots_url, timeout)
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

    def inspect(url: str) -> dict[str, Any]:
        status, final_url, content_type, x_robots_tag, body = _get(url, timeout)
        parser = _Metadata()
        if content_type == "text/html":
            parser.feed(body.decode("utf-8", errors="replace"))
        local_path = _local_page(local_root, base_parts.path, url)
        if not local_path.is_file():
            raise ValueError(f"frozen exported page is missing: {local_path}")
        local_sha256 = hashlib.sha256(local_path.read_bytes()).hexdigest()
        deployed_sha256 = hashlib.sha256(body).hexdigest()
        robots_allowed = {
            user_agent: robots.can_fetch(user_agent, url) for user_agent in crawler_user_agents
        }
        checks = {
            "sitemap_parity": url in observed_set,
            "http_2xx": 200 <= status < 300,
            "html": content_type == "text/html",
            "redirect_identity": final_url == url,
            "self_canonical": parser.canonicals == [url],
            "indexable": not parser.noindex and not _has_noindex(x_robots_tag),
            "robots_allowed": all(robots_allowed.values()),
            "content_parity": local_sha256 == deployed_sha256,
        }
        checks["eligible"] = all(checks.values())
        return {
            "url": url,
            "final_url": final_url,
            "status_code": status,
            "content_type": content_type,
            "x_robots_tag": x_robots_tag,
            "local_sha256": local_sha256,
            "deployed_sha256": deployed_sha256,
            "robots_allowed": robots_allowed,
            "checks": checks,
            "failures": [
                name for name, passed in checks.items() if name != "eligible" and not passed
            ],
        }

    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        pages = list(pool.map(inspect, expected))
    names = tuple(pages[0]["checks"])
    checks = {
        name: {
            "numerator": sum(int(row["checks"][name]) for row in pages),
            "denominator": len(expected),
        }
        for name in names
    }
    status = (
        "pass"
        if not missing
        and not unexpected
        and not duplicates
        and checks["eligible"]["numerator"] == checks["eligible"]["denominator"]
        else "fail"
    )
    return {
        "schema_id": "geode.geo-host-preflight@2",
        "schema_version": 2,
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
        "robots": {
            "url": robots_url,
            "status": robots_status,
            "policy": robots_policy,
            "user_agents": list(crawler_user_agents),
        },
        "checks": checks,
        "pages": pages,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--expected-sitemap", type=Path, required=True)
    parser.add_argument("--expected-root", type=Path)
    parser.add_argument("--crawler", action="append", dest="crawlers")
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
        expected_root=args.expected_root,
        crawler_user_agents=tuple(args.crawlers or ("OAI-SearchBot",)),
    )
    _write_exclusive(args.out, payload)
    print(args.out)
    return 0 if payload["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
