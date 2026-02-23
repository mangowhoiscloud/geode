"""Organization Memory — shared context across IPs (fixture-based).

Implements OrganizationMemoryPort using JSON fixtures loaded from disk.
Provides organization-wide rubrics, IP context, and analysis result storage.

Architecture-v6 §3 Layer 2: Organization Memory tier.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

# Default fixture directory
DEFAULT_FIXTURE_DIR = Path(__file__).parent.parent / "fixtures"


class MonoLakeOrganizationMemory:
    """Organization-level shared memory backed by JSON fixtures.

    Loads IP data from geode/fixtures/*.json and provides
    organization-wide rubric defaults and analysis result storage.

    Usage:
        org = MonoLakeOrganizationMemory()
        ctx = org.get_ip_context("Berserk")
        rubric = org.get_common_rubric()
    """

    def __init__(self, fixture_dir: Path | None = None) -> None:
        self._fixture_dir = fixture_dir or DEFAULT_FIXTURE_DIR
        self._cache: dict[str, dict[str, Any]] = {}
        self._analysis_results: dict[str, list[dict[str, Any]]] = {}
        self._load_fixtures()

    def _load_fixtures(self) -> None:
        """Load all JSON fixtures from the fixture directory."""
        if not self._fixture_dir.exists():
            log.warning("Fixture directory not found: %s", self._fixture_dir)
            return

        for json_file in sorted(self._fixture_dir.glob("*.json")):
            try:
                data = json.loads(json_file.read_text(encoding="utf-8"))
                # Use ip_name from data if available, else filename
                ip_name = data.get("ip_info", {}).get("ip_name", json_file.stem)
                self._cache[ip_name.lower()] = data
            except (json.JSONDecodeError, OSError) as e:
                log.warning("Failed to load fixture %s: %s", json_file.name, e)

    def get_ip_context(self, ip_name: str) -> dict[str, Any]:
        """Get all fixture data for an IP.

        Returns dict with ip_info, monolake, signals, psm_covariates, expected_results.
        Empty dict if IP not found.
        """
        return self._cache.get(ip_name.lower(), {})

    def get_common_rubric(self) -> dict[str, Any]:
        """Get organization-wide default rubric configuration."""
        return {
            "axes_count": 14,
            "scale": "1-5",
            "confidence_threshold": 0.7,
            "tier_mapping": {
                "S": {"min_score": 80},
                "A": {"min_score": 65},
                "B": {"min_score": 50},
                "C": {"min_score": 35},
                "D": {"min_score": 0},
            },
        }

    def save_analysis_result(self, ip_name: str, result: dict[str, Any]) -> bool:
        """Save an analysis result for an IP."""
        key = ip_name.lower()
        if key not in self._analysis_results:
            self._analysis_results[key] = []
        self._analysis_results[key].append(result)
        count = len(self._analysis_results[key])
        log.info("Saved analysis result for %s (total: %d)", ip_name, count)
        return True

    def get_analysis_results(self, ip_name: str) -> list[dict[str, Any]]:
        """Retrieve all saved analysis results for an IP."""
        return self._analysis_results.get(ip_name.lower(), [])

    def list_ips(self) -> list[str]:
        """List all known IP names from fixtures."""
        return [
            self._cache[k].get("ip_info", {}).get("ip_name", k)
            for k in sorted(self._cache.keys())
        ]
