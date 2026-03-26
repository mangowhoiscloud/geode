"""Vault — purpose-routed artifact storage under .geode/vault/.

Context Layer V0: "What have we produced?"

All agent-generated artifacts (reports, applications, research, profiles)
are stored here instead of /tmp/. Each artifact is auto-classified into
a purpose-based subdirectory.

Directories:
  .geode/vault/profile/          Career signals, resumes, portfolios
  .geode/vault/research/         Market research, company analysis, tech comparisons
  .geode/vault/applications/     Cover letters, tailored resumes per company
  .geode/vault/general/          Unclassified artifacts
"""

from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from core.utils.atomic_io import atomic_write_text

log = logging.getLogger(__name__)

DEFAULT_VAULT_DIR = Path(".geode") / "vault"

# Category routing keywords (lowercase matching)
_CATEGORY_KEYWORDS: dict[str, list[str]] = {
    "profile": [
        "profile",
        "signal",
        "resume",
        "cv",
        "이력서",
        "portfolio",
        "포트폴리오",
        "경력",
        "career",
        "시그널",
        "signal-report",
        "프로필",
    ],
    "research": [
        "research",
        "리서치",
        "조사",
        "market",
        "시장",
        "company",
        "회사",
        "industry",
        "기술",
        "비교",
        "compare",
    ],
    "applications": [
        "지원",
        "apply",
        "application",
        "cover-letter",
        "cover letter",
        "커버레터",
        "자소서",
        "자기소개서",
        "지원서",
    ],
}


def classify_artifact(
    filename: str,
    content: str = "",
    *,
    hint: str = "",
) -> str:
    """Classify an artifact into a vault category.

    Args:
        filename: The artifact filename.
        content: Optional content to scan for keywords.
        hint: Optional explicit category hint from the agent.

    Returns:
        Category string: "profile", "research", "applications", or "general".
    """
    # Explicit hint takes priority
    if hint:
        hint_lower = hint.lower()
        for category in ("profile", "research", "applications"):
            if category in hint_lower:
                return category
        # Check if hint matches any keywords
        for category, keywords in _CATEGORY_KEYWORDS.items():
            if any(kw in hint_lower for kw in keywords):
                return category

    # Scan filename + content
    text = f"{filename} {content[:500]}".lower()
    scores: dict[str, int] = {"profile": 0, "research": 0, "applications": 0}
    for category, keywords in _CATEGORY_KEYWORDS.items():
        for kw in keywords:
            if kw in text:
                scores[category] += 1

    best = max(scores, key=lambda k: scores[k])
    if scores[best] > 0:
        return best
    return "general"


class Vault:
    """Purpose-routed artifact storage.

    Usage::

        vault = Vault()
        path = vault.save(
            "signal-report.md",
            content="# Signal Report ...",
            category="profile",
        )
        # → .geode/vault/profile/signal-report-2026-03-18.md

        artifacts = vault.list_artifacts("profile")
        content = vault.load("profile/signal-report-2026-03-18.md")
    """

    CATEGORIES = ("profile", "research", "applications", "general")

    def __init__(self, vault_dir: Path | str | None = None) -> None:
        self._dir = Path(vault_dir) if vault_dir else DEFAULT_VAULT_DIR

    @property
    def vault_dir(self) -> Path:
        return self._dir

    def ensure_structure(self) -> None:
        """Create vault directory structure."""
        for cat in self.CATEGORIES:
            (self._dir / cat).mkdir(parents=True, exist_ok=True)

    def save(
        self,
        filename: str,
        content: str,
        *,
        category: str | None = None,
        company: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Path:
        """Save an artifact to the vault.

        Args:
            filename: Base filename (e.g., "signal-report.md").
            content: File content.
            category: Explicit category. Auto-classified if None.
            company: For applications, the company slug.
            metadata: Optional metadata (written to meta.json for applications).

        Returns:
            Absolute path where the file was saved.
        """
        if category is None:
            category = classify_artifact(filename, content)

        # Ensure category is valid
        if category not in self.CATEGORIES:
            category = "general"

        # Build target directory
        if category == "applications" and company:
            slug = _slugify(company)
            target_dir = self._dir / category / slug
        else:
            target_dir = self._dir / category

        target_dir.mkdir(parents=True, exist_ok=True)

        # Add date suffix for uniqueness (avoid overwrite)
        stem, ext = _split_ext(filename)
        today = date.today().isoformat()
        target_file = target_dir / f"{stem}-{today}{ext}"

        # Handle version collision
        if target_file.exists():
            target_file = _next_version(target_file)

        atomic_write_text(target_file, content)
        log.info("Vault: saved %s → %s", filename, target_file)

        # Write meta.json for applications
        if metadata and category == "applications":
            meta_path = target_dir / "meta.json"
            existing: dict[str, Any] = {}
            if meta_path.exists():
                import contextlib

                with contextlib.suppress(json.JSONDecodeError, OSError):
                    existing = json.loads(meta_path.read_text(encoding="utf-8"))
            existing.update(metadata)
            existing["updated_at"] = time.time()
            if "files" not in existing:
                existing["files"] = []
            if target_file.name not in existing["files"]:
                existing["files"].append(target_file.name)
            atomic_write_text(
                meta_path,
                json.dumps(existing, ensure_ascii=False, indent=2),
            )

        return target_file

    def load(self, relative_path: str) -> str | None:
        """Load an artifact by relative path within the vault."""
        fpath = self._dir / relative_path
        if not fpath.exists():
            return None
        try:
            return fpath.read_text(encoding="utf-8")
        except OSError:
            return None

    def list_artifacts(
        self,
        category: str | None = None,
        *,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """List artifacts in the vault.

        Returns list of dicts with 'path', 'name', 'category', 'size', 'modified'.
        """
        results: list[dict[str, Any]] = []

        categories = [category] if category else list(self.CATEGORIES)

        for cat in categories:
            cat_dir = self._dir / cat
            if not cat_dir.exists():
                continue
            for fpath in cat_dir.rglob("*"):
                if not fpath.is_file():
                    continue
                if fpath.name == "meta.json":
                    continue
                try:
                    results.append(
                        {
                            "path": str(fpath.relative_to(self._dir)),
                            "name": fpath.name,
                            "category": cat,
                            "size": fpath.stat().st_size,
                            "modified": fpath.stat().st_mtime,
                        }
                    )
                except OSError:
                    continue

        # Sort by modified descending (newest first)
        results.sort(key=lambda x: x["modified"], reverse=True)
        return results[:limit]

    def get_context_summary(self, max_items: int = 5) -> str:
        """Build a summary of vault contents for system prompt injection.

        Format: "Vault: 3 profile docs, 2 research, 1 application (Anthropic)"
        """
        counts: dict[str, int] = {}
        app_companies: list[str] = []

        for cat in self.CATEGORIES:
            cat_dir = self._dir / cat
            if not cat_dir.exists():
                continue
            files = [f for f in cat_dir.rglob("*") if f.is_file() and f.name != "meta.json"]
            if files:
                counts[cat] = len(files)
            # Track application companies
            if cat == "applications":
                for d in cat_dir.iterdir():
                    if d.is_dir():
                        app_companies.append(d.name)

        if not counts:
            return ""

        parts = []
        for cat, count in counts.items():
            if cat == "applications" and app_companies:
                companies = ", ".join(app_companies[:3])
                parts.append(f"{count} {cat} ({companies})")
            else:
                parts.append(f"{count} {cat}")
        return "Vault: " + ", ".join(parts)


@dataclass
class ApplicationEntry:
    """A job application entry."""

    company: str
    position: str
    status: str = "draft"  # draft -> applied -> interview -> offer -> rejected
    applied_at: str = ""
    url: str = ""
    notes: str = ""


class ApplicationTracker:
    """CRUD for .geode/vault/applications/tracker.json."""

    VALID_STATUSES = ("draft", "applied", "interview", "offer", "rejected")

    def __init__(self, vault_dir: Path | None = None) -> None:
        self._path = (vault_dir or DEFAULT_VAULT_DIR) / "applications" / "tracker.json"

    def _load(self) -> list[dict[str, Any]]:
        if not self._path.exists():
            return []
        try:
            return json.loads(self._path.read_text(encoding="utf-8"))  # type: ignore[no-any-return]
        except (json.JSONDecodeError, OSError):
            return []

    def _save(self, entries: list[dict[str, Any]]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(
            json.dumps(entries, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    def list(self) -> list[ApplicationEntry]:
        """List all application entries."""
        raw = self._load()
        return [ApplicationEntry(**e) for e in raw]

    def add(self, entry: ApplicationEntry) -> None:
        """Add a new application entry."""
        raw = self._load()
        raw.append(
            {
                "company": entry.company,
                "position": entry.position,
                "status": entry.status,
                "applied_at": entry.applied_at,
                "url": entry.url,
                "notes": entry.notes,
            }
        )
        self._save(raw)

    def update_status(self, company: str, status: str) -> bool:
        """Update the status of an application by company name. Returns True on success."""
        raw = self._load()
        company_lower = company.lower()
        for entry in raw:
            if entry["company"].lower() == company_lower:
                entry["status"] = status
                self._save(raw)
                return True
        return False

    def remove(self, company: str) -> bool:
        """Remove an application by company name. Returns True on success."""
        raw = self._load()
        company_lower = company.lower()
        new = [e for e in raw if e["company"].lower() != company_lower]
        if len(new) == len(raw):
            return False
        self._save(new)
        return True


def _slugify(text: str) -> str:
    """Convert text to URL-safe slug."""
    slug = text.lower().strip()
    slug = re.sub(r"[^\w\s-]", "", slug)
    slug = re.sub(r"[\s]+", "-", slug)
    return slug or "unknown"


def _split_ext(filename: str) -> tuple[str, str]:
    """Split filename into stem and extension."""
    p = Path(filename)
    return p.stem, p.suffix or ".md"


def _next_version(path: Path) -> Path:
    """Find next available version: file.md → file-v2.md → file-v3.md."""
    stem = path.stem
    ext = path.suffix
    parent = path.parent
    for v in range(2, 100):
        candidate = parent / f"{stem}-v{v}{ext}"
        if not candidate.exists():
            return candidate
    # Fallback: use timestamp
    ts = int(time.time())
    return parent / f"{stem}-{ts}{ext}"
