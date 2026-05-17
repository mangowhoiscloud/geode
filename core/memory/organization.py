"""Organization Memory — shared project/org context.

Implements OrganizationMemoryPort using optional JSON fixtures loaded from disk.
GEODE core no longer ships a built-in fixture set.

Architecture-v6 §3 Layer 2: Organization Memory tier.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

# GEODE.md lives at project root (Karpathy P7: program.md = agent identity)
DEFAULT_SOUL_PATH = Path(__file__).parent.parent.parent / "GEODE.md"


class MonoLakeOrganizationMemory:
    """Organization-level shared memory backed by optional JSON fixtures.

    External packages may pass their own fixture directory.

    Usage:
        org = MonoLakeOrganizationMemory()
        ctx = org.get_subject_context("example")
        rubric = org.get_common_rubric()
    """

    def __init__(
        self,
        fixture_dir: Path | None = None,
        soul_path: Path | None = None,
    ) -> None:
        self._fixture_dir = fixture_dir
        self._soul_path = soul_path or DEFAULT_SOUL_PATH
        self._cache: dict[str, dict[str, Any]] = {}
        self._analysis_results: dict[str, list[dict[str, Any]]] = {}
        self._soul_cache: str | None = None
        self._load_fixtures()

    def _load_fixtures(self) -> None:
        """Load all JSON fixtures from the fixture directory."""
        if self._fixture_dir is None:
            return
        if not self._fixture_dir.exists():
            log.warning("Fixture directory not found: %s", self._fixture_dir)
            return

        for json_file in sorted(self._fixture_dir.glob("*.json")):
            try:
                data = json.loads(json_file.read_text(encoding="utf-8"))
                subject = data.get("subject", {}).get("name") or json_file.stem
                self._cache[subject.lower()] = data
            except (json.JSONDecodeError, OSError) as e:
                log.warning("Failed to load fixture %s: %s", json_file.name, e)

    def get_subject_context(self, subject: str) -> dict[str, Any]:
        """Get all fixture data for a subject.

        Empty dict if the subject is not found.
        """
        return self._cache.get(subject.lower(), {})

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

    def get_soul(self) -> str:
        """Load GEODE.md — agent identity and mission statement.

        Returns empty string if GEODE.md not found (graceful degradation).
        Cached after first load.
        """
        if self._soul_cache is not None:
            return self._soul_cache

        if not self._soul_path.exists():
            log.info("GEODE.md not found at %s — using empty soul", self._soul_path)
            self._soul_cache = ""
            return ""

        try:
            self._soul_cache = self._soul_path.read_text(encoding="utf-8")
            log.info("Loaded GEODE.md (%d chars)", len(self._soul_cache))
        except OSError as e:
            log.warning("Failed to read GEODE.md: %s", e)
            self._soul_cache = ""
        return self._soul_cache

    def save_analysis_result(self, subject: str, result: dict[str, Any]) -> bool:
        """Save an analysis result for a subject."""
        key = subject.lower()
        if key not in self._analysis_results:
            self._analysis_results[key] = []
        self._analysis_results[key].append(result)
        count = len(self._analysis_results[key])
        log.info("Saved analysis result for %s (total: %d)", subject, count)
        return True

    def get_analysis_results(self, subject: str) -> list[dict[str, Any]]:
        """Retrieve all saved analysis results for a subject."""
        return self._analysis_results.get(subject.lower(), [])

    def list_subjects(self) -> list[str]:
        """List all known subject names from fixtures."""
        return [
            self._cache[k].get("subject", {}).get("name") or k for k in sorted(self._cache.keys())
        ]
