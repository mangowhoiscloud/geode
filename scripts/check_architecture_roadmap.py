#!/usr/bin/env python3
"""Validate the architecture roadmap ledger and base-relative transitions.

The checker treats ``docs/architecture/extensibility-roadmap.md`` as a small,
append-only state machine.  It validates the current document structurally,
loads the same file from ``--base-ref``, and then rejects transitions that do
not follow §0.3 of the roadmap.
"""

from __future__ import annotations

import argparse
import html
import re
import sys
import unicodedata
from collections import Counter, defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from scripts.git_command import GitExecutableNotFoundError, run_git

REPO_ROOT = Path(__file__).resolve().parents[1]
ROADMAP_FILE = REPO_ROOT / "docs" / "architecture" / "extensibility-roadmap.md"
ROADMAP_RELATIVE = ROADMAP_FILE.relative_to(REPO_ROOT).as_posix()

GAP_PATTERN = re.compile(r"\b[A-Z]+-\d{3}\b")
PACKAGE_PATTERN = re.compile(r"\bR\d+\.\d+\b")
PACKAGE_HEADING = re.compile(r"^####\s+(R\d+\.\d+)\b", re.MULTILINE)
SELECTOR_PATTERN = re.compile(r"^GAPs?:\s*(.+?)\.?\s*$", re.MULTILINE)
TRANSITION_PATTERN = re.compile(
    r"^(OPEN|READY|IN_PROGRESS|IN_DEVELOP|BLOCKED|REJECTED|SUPERSEDED)"
    r"\s*->\s*"
    r"(OPEN|READY|IN_PROGRESS|IN_DEVELOP|BLOCKED|REJECTED|SUPERSEDED)$"
)
PR_LINK_PATTERN = re.compile(
    r"\[#(?P<label>\d+)\]\("
    r"https://github\.com/mangowhoiscloud/geode/pull/(?P<url>\d+)"
    r"\)"
)
FULL_SHA_PATTERN = re.compile(r"(?<![0-9a-f])[0-9a-f]{40}(?![0-9a-f])", re.IGNORECASE)
REMOTE_MAIN_REFS = frozenset({"origin/main", "refs/remotes/origin/main"})
REMOTE_DEVELOP_REFS = frozenset({"origin/develop", "refs/remotes/origin/develop"})
REMOTE_REF_ALIASES = {
    "origin/main": "refs/remotes/origin/main",
    "origin/develop": "refs/remotes/origin/develop",
}
RELEASE_PATTERN = re.compile(r"\bv\d+\.\d+\.\d+\b")
UTC_TIMESTAMP_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
VERIFICATION_RESULT_PATTERN = re.compile(
    r"\b(passed|pass|green|succeeded|verified|audited|re-audited|통과|성공|확인|재감사)\b",
    re.IGNORECASE,
)
NEGATIVE_VERIFICATION_PATTERN = re.compile(
    r"\b(?:failed|failure|failing|error|errors|red|false|"
    r"(?:not|never|no|didn['’]t|doesn['’]t|don['’]t|was"
    r"n['’]t|"
    r"isn['’]t|cannot|can['’]t)\s+(?:\w+\s+){0,3}"
    r"(?:passed|pass|green|succeeded|verified|audited))\b|"
    r"(?:실패|미통과|오류|검증되지\s*않)",
    re.IGNORECASE,
)
RESULT_DECLARATION_PATTERN = re.compile(
    r"\bRESULT\s*:\s*(?P<value>[A-Za-z]+)(?P<suffix>[^\s—;,.\)]*)",
    re.IGNORECASE,
)
INLINE_CODE_PATTERN = re.compile(r"`[^`\n]+`")
HTML_COMMENT_PATTERN = re.compile(r"<!--.*?-->", re.DOTALL)
HTML_TAG_PATTERN = re.compile(r"<[^>]+>")
MARKDOWN_LINK_PATTERN = re.compile(r"\[([^\]]+)\]\([^)]+\)")

AUDIT_CLASSES = frozenset({"EXISTS", "PARTIAL", "ABSENT", "MISFIT"})
STATUSES = frozenset(
    {
        "OPEN",
        "READY",
        "IN_PROGRESS",
        "IN_DEVELOP",
        "BLOCKED",
        "DONE",
        "REJECTED",
        "SUPERSEDED",
    }
)
DECISION_STATUSES = frozenset({"REJECTED", "SUPERSEDED"})
DEPENDENCY_REMOVAL_DECISION = "DEPENDENCY_REMOVED"
DEPENDENCY_ADDITION_DECISION = "DEPENDENCY_ADDED"
DEPENDENCY_DECISIONS = frozenset({DEPENDENCY_REMOVAL_DECISION, DEPENDENCY_ADDITION_DECISION})
DECISION_KINDS = frozenset({*DECISION_STATUSES, *DEPENDENCY_DECISIONS})
DELIVERED_STATUSES = frozenset({"IN_DEVELOP", "DONE"})
DEPENDENCY_ENFORCED_STATUSES = frozenset({"READY", "IN_PROGRESS", "IN_DEVELOP", "DONE"})
EMPTY_CELLS = frozenset({"", "—", "-", "_none yet_", "none yet"})

ALLOWED_TRANSITIONS: dict[str, frozenset[str]] = {
    "OPEN": frozenset({"READY", "BLOCKED", "REJECTED", "SUPERSEDED"}),
    "READY": frozenset({"OPEN", "IN_PROGRESS", "BLOCKED", "REJECTED", "SUPERSEDED"}),
    "IN_PROGRESS": frozenset({"OPEN", "READY", "IN_DEVELOP", "BLOCKED", "REJECTED", "SUPERSEDED"}),
    "IN_DEVELOP": frozenset({"DONE", "BLOCKED", "REJECTED", "SUPERSEDED"}),
    "BLOCKED": frozenset({"OPEN", "READY", "REJECTED", "SUPERSEDED"}),
    "DONE": frozenset(),
    "REJECTED": frozenset(),
    "SUPERSEDED": frozenset(),
}


@dataclass(frozen=True)
class Gap:
    id: str
    audit: str
    baseline_evidence: str
    exit_condition: str
    package: str
    dependencies: tuple[str, ...]
    status: str


@dataclass(frozen=True)
class Package:
    id: str
    gaps: tuple[str, ...]


@dataclass(frozen=True)
class Claim:
    package: str
    gaps: tuple[str, ...]
    owner: str
    branch: str
    evidence: str
    claimed_at: str


@dataclass(frozen=True)
class EvidenceRow:
    key: str
    gaps: tuple[str, ...]
    cells: tuple[str, ...]


@dataclass(frozen=True)
class Roadmap:
    gaps: tuple[Gap, ...]
    packages: tuple[Package, ...]
    package_headings: tuple[str, ...]
    claims: tuple[Claim, ...]
    develop_evidence: tuple[EvidenceRow, ...]
    main_evidence: tuple[EvidenceRow, ...]
    decision_evidence: tuple[EvidenceRow, ...]
    blocker_evidence: tuple[EvidenceRow, ...]


class RoadmapParseError(ValueError):
    """Raised when a required canonical section or table is unreadable."""


def _section(text: str, heading: str, next_heading: str | None = None) -> str:
    start = text.find(heading)
    if start < 0:
        raise RoadmapParseError(f"missing section {heading!r}")
    end = text.find(next_heading, start + len(heading)) if next_heading else len(text)
    if end < 0:
        end = len(text)
    return text[start:end]


def _table_rows(section: str, header_prefix: str) -> list[tuple[str, ...]]:
    lines = section.splitlines()
    try:
        header_index = next(
            index for index, line in enumerate(lines) if line.startswith(header_prefix)
        )
    except StopIteration as error:
        raise RoadmapParseError(f"missing table header {header_prefix!r}") from error

    rows: list[tuple[str, ...]] = []
    for line in lines[header_index + 2 :]:
        if not line.startswith("|"):
            break
        cells = tuple(cell.strip() for cell in line.strip().strip("|").split("|"))
        rows.append(cells)
    return rows


def _clean(cell: str) -> str:
    value = cell.strip()
    if len(value) >= 2 and value.startswith("`") and value.endswith("`"):
        return value[1:-1]
    return value


def _comment_stripped(value: str) -> str:
    return HTML_COMMENT_PATTERN.sub(" ", value)


def _visible_text(value: str) -> str:
    """Return human-visible prose, excluding comments and Markdown wrappers."""
    visible = html.unescape(_comment_stripped(value))
    visible = HTML_TAG_PATTERN.sub(" ", visible)
    visible = MARKDOWN_LINK_PATTERN.sub(r"\1", visible)
    visible = re.sub(r"[`*_~#>|]", " ", visible)
    visible = "".join(
        " " if character.isspace() or unicodedata.category(character).startswith("C") else character
        for character in visible
    )
    return " ".join(visible.split()).strip()


def _meaningful(value: str, *, minimum: int = 8) -> bool:
    visible = _visible_text(value)
    return len(visible) >= minimum and len(re.findall(r"\w", visible)) >= 4


def _gap_id_list(
    cell: str,
    *,
    context: str,
    allow_empty: bool = False,
) -> tuple[str, ...]:
    value = _clean(cell).strip()
    if value in {"", "—", "-"}:
        if allow_empty:
            return ()
        raise RoadmapParseError(f"{context} must name at least one GAP ID")
    parts = tuple(_clean(part).strip() for part in value.split(","))
    invalid = [part for part in parts if GAP_PATTERN.fullmatch(part) is None]
    if invalid:
        raise RoadmapParseError(
            f"{context} has invalid GAP reference(s): {', '.join(repr(part) for part in invalid)}"
        )
    duplicates = _duplicates(parts)
    if duplicates:
        raise RoadmapParseError(f"{context} repeats GAP reference(s): {', '.join(duplicates)}")
    return parts


def _is_placeholder(cells: Sequence[str]) -> bool:
    if not cells:
        return True
    return _empty(cells[0])


def _parse_gaps(text: str) -> tuple[Gap, ...]:
    section = _section(text, "## 5. Master GAP ledger", "## 6.")
    result: list[Gap] = []
    for cells in _table_rows(section, "| ID | Audit |"):
        if len(cells) != 7:
            raise RoadmapParseError(
                f"master ledger row has {len(cells)} cells; expected 7: {cells!r}"
            )
        gap_id = _clean(cells[0])
        if GAP_PATTERN.fullmatch(gap_id) is None:
            raise RoadmapParseError(f"master ledger row has invalid GAP ID {gap_id!r}")
        dependencies = _gap_id_list(
            cells[5],
            context=f"{gap_id} dependency list",
            allow_empty=True,
        )
        result.append(
            Gap(
                id=gap_id,
                audit=_clean(cells[1]),
                baseline_evidence=_clean(cells[2]),
                exit_condition=_clean(cells[3]),
                package=_clean(cells[4]),
                dependencies=dependencies,
                status=_clean(cells[6]),
            )
        )
    return tuple(result)


def _parse_packages(text: str) -> tuple[tuple[Package, ...], tuple[str, ...]]:
    section = _section(text, "## 7. Phase work packages", "## 8.")
    matches = list(PACKAGE_HEADING.finditer(section))
    packages: list[Package] = []
    headings: list[str] = []
    for index, match in enumerate(matches):
        package_id = match.group(1)
        headings.append(package_id)
        end = matches[index + 1].start() if index + 1 < len(matches) else len(section)
        block = section[match.end() : end]
        selector = SELECTOR_PATTERN.search(block)
        if selector is not None:
            packages.append(
                Package(
                    id=package_id,
                    gaps=_gap_id_list(
                        selector.group(1),
                        context=f"{package_id} GAP selector",
                    ),
                )
            )
    return tuple(packages), tuple(headings)


def _parse_claims(text: str) -> tuple[Claim, ...]:
    section = _section(text, "### 0.4 Active claims", "## 1.")
    claims: list[Claim] = []
    for cells in _table_rows(section, "| Closure package | GAP IDs | Owner/session |"):
        if _is_placeholder(cells):
            continue
        if len(cells) != 6:
            raise RoadmapParseError(
                f"active-claim row has {len(cells)} cells; expected 6: {cells!r}"
            )
        claims.append(
            Claim(
                package=_clean(cells[0]),
                gaps=_gap_id_list(
                    cells[1],
                    context=f"{_clean(cells[0])} active-claim GAP list",
                ),
                owner=_clean(cells[2]),
                branch=_clean(cells[3]),
                evidence=cells[4],
                claimed_at=cells[5],
            )
        )
    return tuple(claims)


def _parse_evidence(
    text: str,
    *,
    heading: str,
    next_heading: str,
    header_prefix: str,
    expected_cells: int,
    key_kind: str,
) -> tuple[EvidenceRow, ...]:
    section = _section(text, heading, next_heading)
    result: list[EvidenceRow] = []
    for cells in _table_rows(section, header_prefix):
        if _is_placeholder(cells):
            continue
        if len(cells) != expected_cells:
            raise RoadmapParseError(
                f"{heading} row has {len(cells)} cells; expected {expected_cells}: {cells!r}"
            )
        key = _clean(cells[0])
        gaps: tuple[str, ...]
        if key_kind == "gap":
            gaps = (key,) if GAP_PATTERN.fullmatch(key) else ()
        else:
            gaps = _gap_id_list(
                cells[1],
                context=f"{heading} {key} GAP list",
            )
        result.append(EvidenceRow(key=key, gaps=gaps, cells=cells))
    return tuple(result)


def parse_roadmap(text: str) -> Roadmap:
    """Parse only the canonical tables and package selectors owned by the SOT."""
    packages, headings = _parse_packages(text)
    return Roadmap(
        gaps=_parse_gaps(text),
        packages=packages,
        package_headings=headings,
        claims=_parse_claims(text),
        develop_evidence=_parse_evidence(
            text,
            heading="### 10.1 Develop transition evidence",
            next_heading="### 10.2",
            header_prefix="| Closure package | GAP IDs | Feature PR |",
            expected_cells=5,
            key_kind="package",
        ),
        main_evidence=_parse_evidence(
            text,
            heading="### 10.2 Main closure evidence",
            next_heading="### 10.3",
            header_prefix="| GAP ID | Feature PR / develop commit |",
            expected_cells=6,
            key_kind="gap",
        ),
        decision_evidence=_parse_evidence(
            text,
            heading="### 10.3 Non-closure decision evidence",
            next_heading="### 10.4",
            header_prefix="| GAP ID | Decision |",
            expected_cells=6,
            key_kind="gap",
        ),
        blocker_evidence=_parse_evidence(
            text,
            heading="### 10.4 Blocker evidence",
            next_heading="## 11.",
            header_prefix="| Closure package | GAP IDs | Transition |",
            expected_cells=6,
            key_kind="package",
        ),
    )


def _duplicates(values: Iterable[str]) -> list[str]:
    counts = Counter(values)
    return sorted(value for value, count in counts.items() if count > 1)


def _index_unique(
    rows: Iterable[Gap | Package | Claim | EvidenceRow],
    *,
    attribute: str,
) -> dict[str, Gap | Package | Claim | EvidenceRow]:
    return {str(getattr(row, attribute)): row for row in rows}


def _nonempty_evidence(row: EvidenceRow, label: str) -> list[str]:
    errors: list[str] = []
    for index, cell in enumerate(row.cells):
        if _empty(cell):
            errors.append(f"{label} {row.key}: evidence cell {index + 1} is empty")
    return errors


def _empty(value: str) -> bool:
    visible = _visible_text(value)
    return not visible or visible.lower() in EMPTY_CELLS


def _has_pr_link(value: str) -> bool:
    return any(
        match.group("label") == match.group("url")
        for match in PR_LINK_PATTERN.finditer(_comment_stripped(value))
    )


def _has_sha(value: str) -> bool:
    return FULL_SHA_PATTERN.search(_clean(_comment_stripped(value))) is not None


def _has_durable_reference(value: str) -> bool:
    source = _comment_stripped(value)
    return _has_pr_link(source) or _has_sha(source) or "https://" in source


def _has_verification_result(value: str) -> bool:
    visible = _visible_text(value)
    return (
        NEGATIVE_VERIFICATION_PATTERN.search(visible) is None
        and VERIFICATION_RESULT_PATTERN.search(visible) is not None
    )


def _has_structured_pass(value: str) -> bool:
    source = _comment_stripped(value)
    visible = _visible_text(source)
    if NEGATIVE_VERIFICATION_PATTERN.search(visible) is not None:
        return False
    declarations = tuple(RESULT_DECLARATION_PATTERN.finditer(source))
    if len(declarations) != 1:
        return False
    declaration = declarations[0]
    if declaration.group("value").upper() != "PASS" or declaration.group("suffix"):
        return False
    commands = tuple(match.group(0)[1:-1].strip() for match in INLINE_CODE_PATTERN.finditer(source))
    return any(
        len(command) >= 4
        and (
            re.search(r"\s|[/\\]", command) is not None
            or command
            in {
                "bandit",
                "deptry",
                "lint-imports",
                "make",
                "mypy",
                "pytest",
                "ruff",
            }
        )
        for command in commands
    )


def _valid_utc_timestamp(value: str) -> bool:
    cleaned = _clean(value)
    if UTC_TIMESTAMP_PATTERN.fullmatch(cleaned) is None:
        return False
    try:
        datetime.fromisoformat(cleaned.replace("Z", "+00:00"))
    except ValueError:
        return False
    return True


def _transition(value: str) -> tuple[str, str] | None:
    match = TRANSITION_PATTERN.fullmatch(_clean(value))
    if match is None:
        return None
    return match.group(1), match.group(2)


def _decision_references(row: EvidenceRow) -> tuple[str, ...]:
    decision = _clean(row.cells[1])
    reference_cell = row.cells[2]
    if decision in {"SUPERSEDED", *DEPENDENCY_DECISIONS}:
        return _gap_id_list(
            reference_cell,
            context=f"{row.key} {decision} references",
        )
    if GAP_PATTERN.search(reference_cell) is not None:
        return _gap_id_list(
            reference_cell,
            context=f"{row.key} {decision} references",
        )
    return ()


def _readiness_dependency_errors(gap: Gap, gaps: dict[str, Gap]) -> list[str]:
    errors: list[str] = []
    for dependency in gap.dependencies:
        dependency_gap = gaps.get(dependency)
        if (
            dependency_gap is not None
            and dependency_gap.package != gap.package
            and dependency_gap.status not in DELIVERED_STATUSES
        ):
            errors.append(
                f"{gap.id}: {gap.status} dependency {dependency} is "
                f"{dependency_gap.status}, not IN_DEVELOP/DONE"
            )
    return errors


def _dependency_cycle(gaps: dict[str, Gap]) -> list[str] | None:
    visiting: list[str] = []
    visited: set[str] = set()

    def visit(gap_id: str) -> list[str] | None:
        if gap_id in visiting:
            start = visiting.index(gap_id)
            return [*visiting[start:], gap_id]
        if gap_id in visited:
            return None
        visiting.append(gap_id)
        for dependency in gaps[gap_id].dependencies:
            if dependency in gaps:
                cycle = visit(dependency)
                if cycle:
                    return cycle
        visiting.pop()
        visited.add(gap_id)
        return None

    for gap_id in sorted(gaps):
        cycle = visit(gap_id)
        if cycle:
            return cycle
    return None


def validate_structure(roadmap: Roadmap) -> list[str]:
    """Validate uniqueness, selection, dependency, claim, and evidence invariants."""
    errors: list[str] = []

    duplicate_gaps = _duplicates(gap.id for gap in roadmap.gaps)
    if duplicate_gaps:
        errors.append(f"duplicate GAP IDs: {', '.join(duplicate_gaps)}")
    duplicate_headings = _duplicates(roadmap.package_headings)
    if duplicate_headings:
        errors.append(f"duplicate package IDs in §7: {', '.join(duplicate_headings)}")
    duplicate_selectors = _duplicates(package.id for package in roadmap.packages)
    if duplicate_selectors:
        errors.append(f"duplicate package selectors in §7: {', '.join(duplicate_selectors)}")

    gaps = {
        key: value
        for key, value in _index_unique(roadmap.gaps, attribute="id").items()
        if isinstance(value, Gap)
    }
    packages = {
        key: value
        for key, value in _index_unique(roadmap.packages, attribute="id").items()
        if isinstance(value, Package)
    }

    for gap in roadmap.gaps:
        if gap.audit not in AUDIT_CLASSES:
            errors.append(f"{gap.id}: unknown audit class {gap.audit!r}")
        if not _meaningful(gap.baseline_evidence):
            errors.append(f"{gap.id}: baseline evidence is empty or not meaningful")
        if not _meaningful(gap.exit_condition):
            errors.append(f"{gap.id}: exit condition is empty or not meaningful")
        if gap.status not in STATUSES:
            errors.append(f"{gap.id}: unknown status {gap.status!r}")
        if PACKAGE_PATTERN.fullmatch(gap.package) is None:
            errors.append(f"{gap.id}: invalid closure package {gap.package!r}")
        missing = sorted(set(gap.dependencies) - set(gaps))
        if missing:
            errors.append(f"{gap.id}: missing dependencies: {', '.join(missing)}")
        terminal_dependencies = sorted(
            dependency
            for dependency in gap.dependencies
            if dependency in gaps and gaps[dependency].status in DECISION_STATUSES
        )
        if terminal_dependencies and gap.status not in {"BLOCKED", *DECISION_STATUSES}:
            errors.append(
                f"{gap.id}: dependencies on terminal decisions must be "
                f"rewritten/removed or the package BLOCKED: "
                f"{', '.join(terminal_dependencies)}"
            )
        if gap.status in DEPENDENCY_ENFORCED_STATUSES:
            errors.extend(_readiness_dependency_errors(gap, gaps))

    cycle = _dependency_cycle(gaps)
    if cycle:
        errors.append(f"dependency cycle: {' -> '.join(cycle)}")

    selections: dict[str, list[str]] = defaultdict(list)
    for package in roadmap.packages:
        if not package.gaps:
            errors.append(f"{package.id}: GAP selector is empty")
        for gap_id in package.gaps:
            selections[gap_id].append(package.id)
            selected_gap = gaps.get(gap_id)
            if selected_gap is None:
                errors.append(f"{package.id}: selects unknown GAP {gap_id}")
            elif selected_gap.package != package.id:
                errors.append(
                    f"{gap_id}: ledger package {selected_gap.package} != §7 package {package.id}"
                )
    for gap in roadmap.gaps:
        selected_by = selections.get(gap.id, [])
        if len(selected_by) != 1:
            rendered = ", ".join(selected_by) if selected_by else "none"
            errors.append(f"{gap.id}: selected by {len(selected_by)} §7 packages ({rendered})")
        if gap.package not in packages:
            errors.append(f"{gap.id}: closure package {gap.package} has no §7 GAP selector")

    gaps_by_package: dict[str, list[Gap]] = defaultdict(list)
    for gap in roadmap.gaps:
        gaps_by_package[gap.package].append(gap)
    for package_id, members in sorted(gaps_by_package.items()):
        package_statuses = sorted({gap.status for gap in members})
        if len(package_statuses) != 1:
            errors.append(
                f"{package_id}: non-atomic package statuses: {', '.join(package_statuses)}"
            )

    duplicate_claims = _duplicates(claim.package for claim in roadmap.claims)
    if duplicate_claims:
        errors.append(f"duplicate active claims: {', '.join(duplicate_claims)}")
    claims = {
        key: value
        for key, value in _index_unique(roadmap.claims, attribute="package").items()
        if isinstance(value, Claim)
    }
    for claim in roadmap.claims:
        expected = tuple(sorted(gap.id for gap in gaps_by_package.get(claim.package, [])))
        actual = tuple(sorted(claim.gaps))
        if not expected:
            errors.append(f"{claim.package}: active claim names an unknown package")
        elif actual != expected:
            errors.append(f"{claim.package}: active claim GAPs {actual} != package GAPs {expected}")
        claim_statuses = {gap.status for gap in gaps_by_package.get(claim.package, [])}
        if claim_statuses != {"IN_PROGRESS"}:
            errors.append(f"{claim.package}: active claim requires package status IN_PROGRESS")
        for label, value in (
            ("owner/session", claim.owner),
            ("implementation branch", claim.branch),
            ("claim evidence", claim.evidence),
            ("claimed-at timestamp", claim.claimed_at),
        ):
            if _empty(value):
                errors.append(f"{claim.package}: active claim has empty {label}")
        if not claim.owner.startswith("session=") or " task=" not in claim.owner:
            errors.append(f"{claim.package}: owner/session must use 'session=... task=...' format")
        if re.fullmatch(r"feature/[A-Za-z0-9._/-]+", claim.branch) is None:
            errors.append(f"{claim.package}: invalid implementation branch {claim.branch!r}")
        if not _has_pr_link(claim.evidence):
            errors.append(f"{claim.package}: claim evidence must include a canonical PR link")
        if not _valid_utc_timestamp(claim.claimed_at):
            errors.append(f"{claim.package}: claimed-at timestamp must be ISO-8601 UTC")
    for package_id, members in gaps_by_package.items():
        if {gap.status for gap in members} == {"IN_PROGRESS"} and package_id not in claims:
            errors.append(f"{package_id}: IN_PROGRESS package has no active claim")

    errors.extend(
        _validate_evidence(
            roadmap=roadmap,
            gaps=gaps,
            gaps_by_package=gaps_by_package,
        )
    )
    return errors


def _validate_evidence(
    *,
    roadmap: Roadmap,
    gaps: dict[str, Gap],
    gaps_by_package: dict[str, list[Gap]],
) -> list[str]:
    errors: list[str] = []
    develop_duplicates = _duplicates(row.key for row in roadmap.develop_evidence)
    if develop_duplicates:
        errors.append(f"duplicate develop-transition evidence: {', '.join(develop_duplicates)}")
    develop = {
        key: value
        for key, value in _index_unique(roadmap.develop_evidence, attribute="key").items()
        if isinstance(value, EvidenceRow)
    }
    for row in roadmap.develop_evidence:
        errors.extend(_nonempty_evidence(row, "develop evidence"))
        expected = tuple(sorted(gap.id for gap in gaps_by_package.get(row.key, [])))
        statuses = {gap.status for gap in gaps_by_package.get(row.key, [])}
        if not expected:
            errors.append(f"{row.key}: develop evidence names an unknown package")
        elif tuple(sorted(row.gaps)) != expected:
            errors.append(
                f"{row.key}: develop evidence GAPs {tuple(sorted(row.gaps))} "
                f"!= package GAPs {expected}"
            )
        if statuses and not statuses <= DELIVERED_STATUSES:
            errors.append(
                f"{row.key}: §10.1 evidence is prospective for package status "
                f"{', '.join(sorted(statuses))}"
            )
        if not _has_pr_link(row.cells[2]):
            errors.append(f"{row.key}: develop evidence requires a canonical feature PR link")
        if not _has_sha(row.cells[3]):
            errors.append(f"{row.key}: develop evidence requires a full 40-character merge SHA")
        if not _has_verification_result(row.cells[4]):
            errors.append(f"{row.key}: develop evidence must state a verification result")
    for package_id, members in gaps_by_package.items():
        statuses = {gap.status for gap in members}
        if statuses <= DELIVERED_STATUSES and statuses and package_id not in develop:
            errors.append(f"{package_id}: delivered package lacks §10.1 evidence")

    main_duplicates = _duplicates(row.key for row in roadmap.main_evidence)
    if main_duplicates:
        errors.append(f"duplicate main-closure evidence: {', '.join(main_duplicates)}")
    main = {row.key: row for row in roadmap.main_evidence}
    for row in roadmap.main_evidence:
        errors.extend(_nonempty_evidence(row, "main evidence"))
        main_gap = gaps.get(row.key)
        if main_gap is None:
            errors.append(f"{row.key}: main evidence names an unknown GAP")
        elif main_gap.status != "DONE":
            errors.append(
                f"{row.key}: §10.2 evidence is prospective for GAP status {main_gap.status}"
            )
        if not _has_pr_link(row.cells[1]) and not _has_sha(row.cells[1]):
            errors.append(f"{row.key}: main evidence requires a feature PR or develop SHA")
        if (
            not _has_sha(row.cells[2])
            and RELEASE_PATTERN.search(_comment_stripped(row.cells[2])) is None
        ):
            errors.append(f"{row.key}: main evidence requires a full SHA or release version")
        if not _has_verification_result(row.cells[3]):
            errors.append(f"{row.key}: main evidence must state a verification result")
        if not _meaningful(row.cells[4]):
            errors.append(f"{row.key}: main migration/compatibility evidence is not meaningful")
        if not _meaningful(row.cells[5]):
            errors.append(f"{row.key}: main documentation evidence is not meaningful")
    for gap in roadmap.gaps:
        if gap.status == "DONE" and gap.id not in main:
            errors.append(f"{gap.id}: DONE GAP lacks §10.2 evidence")

    decision_duplicates = _duplicates("\x1f".join(row.cells) for row in roadmap.decision_evidence)
    if decision_duplicates:
        errors.append(f"duplicate non-closure decision evidence rows: {len(decision_duplicates)}")
    decisions: dict[str, list[EvidenceRow]] = defaultdict(list)
    for row in roadmap.decision_evidence:
        decisions[row.key].append(row)
        errors.extend(_nonempty_evidence(row, "decision evidence"))
        decision_gap = gaps.get(row.key)
        decision = _clean(row.cells[1])
        if decision_gap is None:
            errors.append(f"{row.key}: decision evidence names an unknown GAP")
        elif decision not in DECISION_KINDS:
            errors.append(f"{row.key}: decision evidence has invalid decision {decision!r}")
        elif decision in DECISION_STATUSES and decision_gap.status != decision:
            errors.append(
                f"{row.key}: §10.3 {decision} evidence does not match "
                f"GAP status {decision_gap.status}"
            )
        referenced_gaps = _decision_references(row)
        if decision in {"SUPERSEDED", *DEPENDENCY_DECISIONS} and not referenced_gaps:
            errors.append(f"{row.key}: {decision} evidence must name replacement/changed GAPs")
        unknown_references = sorted(set(referenced_gaps) - set(gaps))
        if unknown_references:
            errors.append(
                f"{row.key}: decision evidence names unknown GAPs: {', '.join(unknown_references)}"
            )
        if row.key in referenced_gaps:
            errors.append(f"{row.key}: decision evidence cannot reference itself")
        if len(_clean(row.cells[3])) < 12:
            errors.append(f"{row.key}: decision rationale is too short")
        if not _has_pr_link(row.cells[4]) and not _has_sha(row.cells[4]):
            errors.append(f"{row.key}: decision evidence requires a PR link or full SHA")
        if not _has_verification_result(row.cells[5]):
            errors.append(f"{row.key}: decision evidence must state a re-audit result")
    for gap in roadmap.gaps:
        matching = [row for row in decisions.get(gap.id, []) if _clean(row.cells[1]) == gap.status]
        if gap.status in DECISION_STATUSES and not matching:
            errors.append(f"{gap.id}: {gap.status} GAP lacks §10.3 evidence")

    blocker_duplicates = _duplicates("\x1f".join(row.cells) for row in roadmap.blocker_evidence)
    if blocker_duplicates:
        errors.append(f"duplicate blocker evidence rows: {len(blocker_duplicates)}")
    blocker_rows: dict[str, list[EvidenceRow]] = defaultdict(list)
    for row in roadmap.blocker_evidence:
        blocker_rows[row.key].append(row)
        errors.extend(_nonempty_evidence(row, "blocker evidence"))
        expected = tuple(sorted(gap.id for gap in gaps_by_package.get(row.key, [])))
        if not expected:
            errors.append(f"{row.key}: blocker evidence names an unknown package")
        elif tuple(sorted(row.gaps)) != expected:
            errors.append(
                f"{row.key}: blocker evidence GAPs {tuple(sorted(row.gaps))} "
                f"!= package GAPs {expected}"
            )
        parsed_transition = _transition(row.cells[2])
        if parsed_transition is None:
            errors.append(f"{row.key}: blocker evidence has invalid transition {row.cells[2]!r}")
        else:
            source, target = parsed_transition
            if (source == "BLOCKED") == (target == "BLOCKED"):
                errors.append(f"{row.key}: blocker evidence transition must enter or leave BLOCKED")
            elif target not in ALLOWED_TRANSITIONS.get(source, frozenset()):
                errors.append(
                    f"{row.key}: blocker evidence has illegal transition {source} -> {target}"
                )
        if not _has_durable_reference(row.cells[4]):
            errors.append(f"{row.key}: blocker evidence requires a durable URL or full SHA")
        if not _has_verification_result(row.cells[5]):
            errors.append(f"{row.key}: blocker evidence must state a re-audit result")
    for package_id, members in gaps_by_package.items():
        statuses = {gap.status for gap in members}
        package_rows = blocker_rows.get(package_id, [])
        if statuses == {"BLOCKED"} and not package_rows:
            errors.append(f"{package_id}: BLOCKED package lacks §10.4 evidence")
        valid_transitions = [
            transition
            for row in package_rows
            if (transition := _transition(row.cells[2])) is not None
        ]
        if valid_transitions:
            last_target = valid_transitions[-1][1]
            if statuses == {"BLOCKED"} and last_target != "BLOCKED":
                errors.append(f"{package_id}: latest §10.4 row does not enter BLOCKED")
            if statuses != {"BLOCKED"} and last_target == "BLOCKED":
                errors.append(f"{package_id}: BLOCKED package recovery lacks a §10.4 exit row")
    return errors


def validate_transitions(
    base: Roadmap,
    current: Roadmap,
    *,
    base_ref: str,
    trusted_main: Roadmap | None = None,
    allow_done: bool | None = None,
) -> list[str]:
    """Reject illegal state changes and destructive evidence edits."""
    errors: list[str] = []
    if allow_done is None:
        allow_done = base_ref == "origin/main"
    base_gaps = {gap.id: gap for gap in base.gaps}
    current_gaps = {gap.id: gap for gap in current.gaps}
    base_claims = {claim.package: claim for claim in base.claims}
    current_claims = {claim.package: claim for claim in current.claims}

    base_develop_cells = {row.cells for row in base.develop_evidence}
    base_main_cells = {row.cells for row in base.main_evidence}
    base_decision_cells = {row.cells for row in base.decision_evidence}
    base_blocker_cells = {row.cells for row in base.blocker_evidence}
    new_develop = tuple(
        row for row in current.develop_evidence if row.cells not in base_develop_cells
    )
    new_main = tuple(row for row in current.main_evidence if row.cells not in base_main_cells)
    new_decisions = tuple(
        row for row in current.decision_evidence if row.cells not in base_decision_cells
    )
    new_blockers = tuple(
        row for row in current.blocker_evidence if row.cells not in base_blocker_cells
    )
    new_develop_packages = {row.key for row in new_develop}
    new_main_gaps = {row.key for row in new_main}
    trusted_main_gaps = (
        {gap.id: gap for gap in trusted_main.gaps} if trusted_main is not None else {}
    )
    trusted_main_evidence: dict[str, set[tuple[str, ...]]] = defaultdict(set)
    if trusted_main is not None:
        for row in trusted_main.main_evidence:
            trusted_main_evidence[row.key].add(row.cells)

    removed = sorted(set(base_gaps) - set(current_gaps))
    if removed:
        errors.append(f"GAP IDs are append-only; removed: {', '.join(removed)}")
    base_gap_order = tuple(gap.id for gap in base.gaps)
    current_gap_order = tuple(gap.id for gap in current.gaps)
    if current_gap_order[: len(base_gap_order)] != base_gap_order:
        errors.append("GAP ledger rows are append-only; existing IDs were reordered or inserted")

    base_packages = set(base.package_headings)
    for gap_id in sorted(set(current_gaps) - set(base_gaps)):
        gap = current_gaps[gap_id]
        if gap.status != "OPEN":
            errors.append(f"{gap_id}: new GAP must start OPEN, found {gap.status}")
        if gap.package in base_packages:
            errors.append(f"{gap_id}: new GAP must use a new closure package, found {gap.package}")

    for gap_id in sorted(set(base_gaps) & set(current_gaps)):
        before = base_gaps[gap_id]
        after = current_gaps[gap_id]
        if before.audit != after.audit:
            errors.append(f"{gap_id}: registered audit class is immutable")
        if before.baseline_evidence != after.baseline_evidence:
            errors.append(f"{gap_id}: registered baseline evidence is immutable")
        if before.exit_condition != after.exit_condition:
            errors.append(f"{gap_id}: registered exit condition is immutable")
        if before.package != after.package:
            errors.append(f"{gap_id}: closure package changed {before.package} -> {after.package}")

        removed_dependencies = sorted(set(before.dependencies) - set(after.dependencies))
        added_dependencies = sorted(set(after.dependencies) - set(before.dependencies))
        matching_removal_decisions = [
            row
            for row in new_decisions
            if row.key == gap_id
            and _clean(row.cells[1]) == DEPENDENCY_REMOVAL_DECISION
            and set(removed_dependencies) == set(_decision_references(row))
        ]
        if removed_dependencies and not matching_removal_decisions:
            errors.append(
                f"{gap_id}: dependency edges removed without exact new §10.3 evidence: "
                f"{', '.join(removed_dependencies)}"
            )
        matching_addition_decisions = [
            row
            for row in new_decisions
            if row.key == gap_id
            and _clean(row.cells[1]) == DEPENDENCY_ADDITION_DECISION
            and set(added_dependencies) == set(_decision_references(row))
        ]
        if added_dependencies and not matching_addition_decisions:
            errors.append(
                f"{gap_id}: dependency edges added without exact new §10.3 evidence: "
                f"{', '.join(added_dependencies)}"
            )

        if before.status == after.status:
            continue
        if after.status not in ALLOWED_TRANSITIONS.get(before.status, frozenset()):
            errors.append(f"{gap_id}: illegal status transition {before.status} -> {after.status}")
            continue

        if after.status == "IN_PROGRESS" and after.package not in current_claims:
            errors.append(f"{gap_id}: transition to IN_PROGRESS requires an active claim")
        if after.status == "IN_DEVELOP":
            if after.package not in new_develop_packages:
                errors.append(f"{gap_id}: transition to IN_DEVELOP requires new §10.1 evidence")
            if after.package in current_claims:
                errors.append(f"{gap_id}: IN_DEVELOP transition must remove the active claim")
        if after.status == "DONE":
            trusted_done = (
                trusted_main_gaps.get(gap_id) is not None
                and trusted_main_gaps[gap_id].status == "DONE"
                and bool(
                    trusted_main_evidence.get(gap_id, set())
                    & {row.cells for row in current.main_evidence if row.key == gap_id}
                )
            )
            if not allow_done and not trusted_done:
                errors.append(
                    f"{gap_id}: DONE transition requires --base-ref origin/main "
                    f"or exact --trusted-main-ref evidence, found {base_ref}"
                )
            if gap_id not in new_main_gaps:
                errors.append(f"{gap_id}: DONE transition requires new §10.2 evidence")
        if after.status == "BLOCKED" or before.status == "BLOCKED":
            matching_blockers = [
                row
                for row in new_blockers
                if row.key == after.package
                and _transition(row.cells[2]) == (before.status, after.status)
            ]
            if not matching_blockers:
                errors.append(
                    f"{gap_id}: {before.status} -> {after.status} requires a new matching §10.4 row"
                )
        if after.status in DECISION_STATUSES:
            matching_decisions = [
                row
                for row in new_decisions
                if row.key == gap_id and _clean(row.cells[1]) == after.status
            ]
            if not matching_decisions:
                errors.append(f"{gap_id}: {after.status} transition requires new §10.3 evidence")
        if (
            before.status == "IN_PROGRESS"
            and after.status != "IN_PROGRESS"
            and after.package in current_claims
        ):
            errors.append(f"{gap_id}: leaving IN_PROGRESS requires active-claim removal")

    base_package_status = {
        package: next(iter(statuses))
        for package in {gap.package for gap in base.gaps}
        if len(statuses := {gap.status for gap in base.gaps if gap.package == package}) == 1
    }
    current_package_status = {
        package: next(iter(statuses))
        for package in {gap.package for gap in current.gaps}
        if len(statuses := {gap.status for gap in current.gaps if gap.package == package}) == 1
    }
    for row in new_develop:
        if not _has_structured_pass(row.cells[4]):
            errors.append(
                f"{row.key}: new §10.1 verification must include an inline command and RESULT: PASS"
            )
        if not (
            base_package_status.get(row.key) != "IN_DEVELOP"
            and current_package_status.get(row.key) == "IN_DEVELOP"
        ):
            errors.append(f"{row.key}: new §10.1 evidence has no matching IN_DEVELOP transition")
    for row in new_main:
        if not _has_structured_pass(row.cells[3]):
            errors.append(
                f"{row.key}: new §10.2 verification must include an inline command and RESULT: PASS"
            )
        base_gap = base_gaps.get(row.key)
        current_gap = current_gaps.get(row.key)
        if (
            base_gap is None
            or current_gap is None
            or base_gap.status == "DONE"
            or current_gap.status != "DONE"
        ):
            errors.append(f"{row.key}: new §10.2 evidence has no matching DONE transition")
    for row in new_decisions:
        if not _has_structured_pass(row.cells[5]):
            errors.append(
                f"{row.key}: new §10.3 re-audit must include an inline command and RESULT: PASS"
            )
        base_gap = base_gaps.get(row.key)
        current_gap = current_gaps.get(row.key)
        decision = _clean(row.cells[1])
        status_transition = (
            base_gap is not None
            and current_gap is not None
            and base_gap.status != current_gap.status
            and current_gap.status == decision
        )
        before_edges = set(base_gap.dependencies) if base_gap is not None else set()
        after_edges = set(current_gap.dependencies) if current_gap is not None else set()
        removed_edges = before_edges - after_edges
        added_edges = after_edges - before_edges
        dependency_removal = (
            decision == DEPENDENCY_REMOVAL_DECISION
            and bool(removed_edges)
            and removed_edges == set(_decision_references(row))
        )
        dependency_addition = (
            decision == DEPENDENCY_ADDITION_DECISION
            and bool(added_edges)
            and added_edges == set(_decision_references(row))
        )
        if not status_transition and not dependency_removal and not dependency_addition:
            errors.append(f"{row.key}: new §10.3 evidence has no matching decision/edge transition")
    for row in new_blockers:
        if not _has_structured_pass(row.cells[5]):
            errors.append(
                f"{row.key}: new §10.4 re-audit must include an inline command and RESULT: PASS"
            )
        base_status = base_package_status.get(row.key)
        current_status = current_package_status.get(row.key)
        if (
            base_status is None
            or current_status is None
            or _transition(row.cells[2]) != (base_status, current_status)
        ):
            errors.append(f"{row.key}: new §10.4 evidence has no matching package transition")

    if trusted_main is not None:
        current_main_cells = {row.cells for row in current.main_evidence}
        for gap_id, main_gap in trusted_main_gaps.items():
            if main_gap.status != "DONE":
                continue
            current_gap = current_gaps.get(gap_id)
            if current_gap is None or current_gap.status != "DONE":
                errors.append(f"{gap_id}: main-sync result regresses canonical main DONE state")
            missing_rows = trusted_main_evidence.get(gap_id, set()) - current_main_cells
            if missing_rows:
                errors.append(
                    f"{gap_id}: main-sync result omits canonical §10.2 evidence from main"
                )

    for package, claim in base_claims.items():
        if package in current_claims:
            current_claim = current_claims[package]
            base_statuses = {gap.status for gap in base.gaps if gap.package == package}
            current_statuses = {gap.status for gap in current.gaps if gap.package == package}
            if (
                base_statuses == {"IN_PROGRESS"}
                and current_statuses == {"IN_PROGRESS"}
                and claim != current_claim
            ):
                errors.append(f"{package}: active claim changed without releasing the package")

    evidence_tables = (
        ("§10.1 develop", base.develop_evidence, current.develop_evidence),
        ("§10.2 main", base.main_evidence, current.main_evidence),
        ("§10.3 decision", base.decision_evidence, current.decision_evidence),
        ("§10.4 blocker", base.blocker_evidence, current.blocker_evidence),
    )
    for label, base_rows, current_rows in evidence_tables:
        base_cells = tuple(row.cells for row in base_rows)
        current_cells = tuple(row.cells for row in current_rows)
        if current_cells[: len(base_cells)] != base_cells:
            errors.append(
                f"delivery/decision/blocker evidence is append-only; "
                f"{label} rows were removed, rewritten, reordered, or inserted"
            )
    return errors


def _normalized_document(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n").rstrip() + "\n"


def _mask_main_tracking_document(text: str) -> str:
    """Mask only fields that a tracking-only main transaction may change."""
    ledger = _section(text, "## 5. Master GAP ledger", "## 6.")
    ledger_lines = ledger.splitlines()
    for index, line in enumerate(ledger_lines):
        if not line.startswith("|"):
            continue
        parts = line.split("|")
        if len(parts) != 9 or GAP_PATTERN.fullmatch(_clean(parts[1])) is None:
            continue
        parts[-2] = " <STATUS> "
        ledger_lines[index] = "|".join(parts)
    masked = text.replace(ledger, "\n".join(ledger_lines), 1)

    main_section = _section(masked, "### 10.2 Main closure evidence", "### 10.3")
    main_lines = main_section.splitlines()
    try:
        header_index = next(
            index
            for index, line in enumerate(main_lines)
            if line.startswith("| GAP ID | Feature PR / develop commit |")
        )
    except StopIteration as error:
        raise RoadmapParseError("missing §10.2 main evidence table") from error
    data_start = header_index + 2
    data_end = data_start
    while data_end < len(main_lines) and main_lines[data_end].startswith("|"):
        data_end += 1
    main_lines[data_start:data_end] = ["<!-- main-closure-rows -->"]
    masked = masked.replace(main_section, "\n".join(main_lines), 1)
    return _normalized_document(masked)


def validate_main_tracking(
    base: Roadmap,
    current: Roadmap,
    *,
    base_text: str,
    current_text: str,
) -> list[str]:
    """Allow only post-promotion IN_DEVELOP -> DONE closure transactions."""
    errors: list[str] = []
    base_gaps = {gap.id: gap for gap in base.gaps}
    current_gaps = {gap.id: gap for gap in current.gaps}

    if tuple(gap.id for gap in current.gaps) != tuple(gap.id for gap in base.gaps):
        errors.append("main tracking cannot add, remove, reorder, or insert GAP rows")
    if current.package_headings != base.package_headings or current.packages != base.packages:
        errors.append("main tracking cannot change closure packages or GAP selectors")
    if current.claims != base.claims:
        errors.append("main tracking cannot change active claims")
    if current.develop_evidence != base.develop_evidence:
        errors.append("main tracking cannot change §10.1 develop evidence")
    if current.decision_evidence != base.decision_evidence:
        errors.append("main tracking cannot change §10.3 decision evidence")
    if current.blocker_evidence != base.blocker_evidence:
        errors.append("main tracking cannot change §10.4 blocker evidence")
    if _mask_main_tracking_document(current_text) != _mask_main_tracking_document(base_text):
        errors.append(
            "main tracking cannot change roadmap prose, frontmatter, or fields "
            "outside status and §10.2 closure rows"
        )

    for gap_id in sorted(set(base_gaps) & set(current_gaps)):
        before = base_gaps[gap_id]
        after = current_gaps[gap_id]
        if before.dependencies != after.dependencies:
            errors.append(f"{gap_id}: main tracking cannot change dependency edges")
        if before.status != after.status and (
            before.status,
            after.status,
        ) != ("IN_DEVELOP", "DONE"):
            errors.append(
                f"{gap_id}: main tracking permits only IN_DEVELOP -> DONE, "
                f"found {before.status} -> {after.status}"
            )
    return errors


def validate_main_promotion(
    base_main: Roadmap | None,
    current: Roadmap,
    trusted_develop: Roadmap,
    *,
    current_text: str,
    trusted_develop_text: str,
) -> list[str]:
    """Validate a same-repository develop -> main promotion fail-closed."""
    errors: list[str] = []
    if _normalized_document(current_text) != _normalized_document(trusted_develop_text):
        errors.append(
            "develop -> main promotion must carry the exact complete roadmap "
            "from trusted origin/develop"
        )
    if base_main is None:
        return errors

    base_gaps = {gap.id: gap for gap in base_main.gaps}
    current_gaps = {gap.id: gap for gap in current.gaps}
    base_order = tuple(gap.id for gap in base_main.gaps)
    current_order = tuple(gap.id for gap in current.gaps)
    if current_order[: len(base_order)] != base_order:
        errors.append("develop -> main promotion rewrites canonical main GAP history")

    for gap_id, before in base_gaps.items():
        after = current_gaps.get(gap_id)
        if after is None:
            errors.append(f"{gap_id}: develop -> main promotion removes a canonical main GAP")
            continue
        if (
            before.audit,
            before.baseline_evidence,
            before.exit_condition,
            before.package,
        ) != (
            after.audit,
            after.baseline_evidence,
            after.exit_condition,
            after.package,
        ):
            errors.append(
                f"{gap_id}: develop -> main promotion rewrites immutable GAP registration"
            )
        if before.status == "DONE" and after.status != "DONE":
            errors.append(f"{gap_id}: develop -> main promotion regresses canonical DONE state")

    evidence_tables = (
        ("§10.1", base_main.develop_evidence, current.develop_evidence),
        ("§10.2", base_main.main_evidence, current.main_evidence),
        ("§10.3", base_main.decision_evidence, current.decision_evidence),
        ("§10.4", base_main.blocker_evidence, current.blocker_evidence),
    )
    for label, base_rows, current_rows in evidence_tables:
        if current_rows[: len(base_rows)] != base_rows:
            errors.append(
                "develop -> main promotion removes, rewrites, or reorders "
                f"canonical {label} evidence"
            )
    return errors


def _load_base(base_ref: str) -> str | None:
    base_ref = REMOTE_REF_ALIASES.get(base_ref, base_ref)
    try:
        process = run_git(
            ["show", f"{base_ref}:{ROADMAP_RELATIVE}"],
            cwd=REPO_ROOT,
        )
    except GitExecutableNotFoundError:
        raise RoadmapParseError("git is required to load --base-ref") from None
    if process.returncode != 0:
        ref_probe = run_git(
            ["rev-parse", "--verify", "--quiet", f"{base_ref}^{{commit}}"],
            cwd=REPO_ROOT,
        )
        if ref_probe.returncode == 0:
            # The caller decides whether an absent document is an authorized
            # same-repository develop -> main bootstrap. Every other mode
            # fails closed.
            return None
        detail = process.stderr.strip() or f"git show exited {process.returncode}"
        raise RoadmapParseError(f"cannot read {ROADMAP_RELATIVE} from {base_ref}: {detail}")
    return process.stdout


def check(
    current_text: str,
    base_text: str | None,
    *,
    base_ref: str,
    target_branch: str,
    event_mode: str = "pull_request",
    trusted_main_text: str | None = None,
    trusted_develop_text: str | None = None,
) -> list[str]:
    """Parse and validate current/base documents, returning every finding."""
    current = parse_roadmap(current_text)
    errors = validate_structure(current)
    if target_branch not in {"develop", "main"}:
        errors.append(f"unknown target branch {target_branch!r}")
    if event_mode == "pull_request":
        expected_base_refs = {
            f"origin/{target_branch}",
            f"refs/remotes/origin/{target_branch}",
        }
        if base_ref not in expected_base_refs:
            errors.append(
                f"target {target_branch} requires its origin remote-tracking ref, found {base_ref}"
            )
    elif event_mode == "push":
        if FULL_SHA_PATTERN.fullmatch(base_ref) is None or set(base_ref) == {"0"}:
            errors.append(
                "push validation requires the non-zero 40-character "
                "github.event.before SHA as --base-ref"
            )
    else:
        errors.append(f"unknown event mode {event_mode!r}")

    trusted_main = parse_roadmap(trusted_main_text) if trusted_main_text is not None else None
    trusted_develop = (
        parse_roadmap(trusted_develop_text) if trusted_develop_text is not None else None
    )
    if trusted_main is not None and trusted_develop is not None:
        errors.append("--trusted-main-ref and --trusted-develop-ref are mutually exclusive")
    if trusted_main is not None:
        if target_branch != "develop":
            errors.append("--trusted-main-ref is only valid for a develop target")
        trusted_errors = validate_structure(trusted_main)
        errors.extend(f"trusted main: {error}" for error in trusted_errors)
    if trusted_develop is not None:
        if target_branch != "main":
            errors.append("--trusted-develop-ref is only valid for a main target")
        trusted_errors = validate_structure(trusted_develop)
        errors.extend(f"trusted develop: {error}" for error in trusted_errors)

    base = parse_roadmap(base_text) if base_text is not None else None
    if base is not None:
        base_errors = validate_structure(base)
        errors.extend(f"base {base_ref}: {error}" for error in base_errors)

    exact_develop_promotion = (
        target_branch == "main"
        and trusted_develop is not None
        and (
            event_mode == "pull_request"
            or (
                trusted_develop_text is not None
                and _normalized_document(current_text) == _normalized_document(trusted_develop_text)
            )
        )
    )
    if exact_develop_promotion:
        assert trusted_develop is not None
        assert trusted_develop_text is not None
        errors.extend(
            validate_main_promotion(
                base,
                current,
                trusted_develop,
                current_text=current_text,
                trusted_develop_text=trusted_develop_text,
            )
        )
        return errors
    if base_text is None:
        errors.append(
            f"base {base_ref} has no architecture roadmap; "
            "only trusted develop -> main promotion may bootstrap it"
        )
        return errors
    assert base is not None
    errors.extend(
        validate_transitions(
            base,
            current,
            base_ref=base_ref,
            trusted_main=trusted_main,
            allow_done=target_branch == "main",
        )
    )
    if target_branch == "main":
        errors.extend(
            validate_main_tracking(
                base,
                current,
                base_text=base_text,
                current_text=current_text,
            )
        )
    return errors


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", required=True)
    parser.add_argument(
        "--base-ref",
        required=True,
        help="target branch ref used to validate state transitions",
    )
    parser.add_argument(
        "--target-branch",
        choices=("develop", "main"),
        required=True,
        help="protected branch targeted by this checkout or pull request",
    )
    parser.add_argument(
        "--event-mode",
        choices=("pull_request", "push"),
        default="pull_request",
        help="select target-ref PR validation or pre-push-SHA validation",
    )
    parser.add_argument(
        "--trusted-main-ref",
        help=(
            "same-repository main ref whose already-validated DONE state may be "
            "merged into the target base"
        ),
    )
    parser.add_argument(
        "--trusted-develop-ref",
        help=("same-repository develop ref whose exact canonical ledger is being promoted to main"),
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.trusted_main_ref and args.trusted_main_ref not in REMOTE_MAIN_REFS:
            raise RoadmapParseError(
                "--trusted-main-ref must be the origin/main remote-tracking ref"
            )
        if args.trusted_develop_ref and args.trusted_develop_ref not in REMOTE_DEVELOP_REFS:
            raise RoadmapParseError(
                "--trusted-develop-ref must be the origin/develop remote-tracking ref"
            )
        if args.trusted_main_ref and args.trusted_develop_ref:
            raise RoadmapParseError(
                "--trusted-main-ref and --trusted-develop-ref are mutually exclusive"
            )
        current_text = ROADMAP_FILE.read_text(encoding="utf-8")
        base_text = _load_base(args.base_ref)
        trusted_main_text = _load_base(args.trusted_main_ref) if args.trusted_main_ref else None
        trusted_develop_text = (
            _load_base(args.trusted_develop_ref) if args.trusted_develop_ref else None
        )
        if args.trusted_main_ref and trusted_main_text is None and args.event_mode != "push":
            raise RoadmapParseError(
                f"trusted main ref {args.trusted_main_ref} has no architecture roadmap"
            )
        if args.trusted_develop_ref and trusted_develop_text is None:
            raise RoadmapParseError(
                f"trusted develop ref {args.trusted_develop_ref} has no architecture roadmap"
            )
        errors = check(
            current_text,
            base_text,
            base_ref=args.base_ref,
            target_branch=args.target_branch,
            event_mode=args.event_mode,
            trusted_main_text=trusted_main_text,
            trusted_develop_text=trusted_develop_text,
        )
    except (OSError, RoadmapParseError) as error:
        print(f"architecture roadmap: {error}", file=sys.stderr)
        return 2

    if errors:
        print(f"architecture roadmap: {len(errors)} invariant violation(s)", file=sys.stderr)
        for finding in errors:
            print(f"  - {finding}", file=sys.stderr)
        return 1
    if trusted_main_text is not None:
        print(
            f"architecture roadmap OK (base {args.base_ref}; trusted main {args.trusted_main_ref})"
        )
    elif trusted_develop_text is not None:
        print(
            "architecture roadmap OK "
            f"(base {args.base_ref}; trusted develop {args.trusted_develop_ref})"
        )
    else:
        print(f"architecture roadmap OK (base {args.base_ref})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
