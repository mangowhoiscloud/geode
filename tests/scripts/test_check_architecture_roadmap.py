"""Hostile fixtures for the architecture-roadmap state-machine checker."""

from __future__ import annotations

from pathlib import Path

import pytest
from scripts import check_architecture_roadmap as checker

ROADMAP = Path("docs/architecture/extensibility-roadmap.md").read_text(encoding="utf-8")
CI_WORKFLOW = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")


def _replace_ledger_cell(text: str, gap_id: str, column: int, value: str) -> str:
    prefix = f"| {gap_id} |"
    line = next(line for line in text.splitlines() if line.startswith(prefix))
    cells = line.strip().strip("|").split("|")
    cells[column] = f" {value} "
    replacement = "|" + "|".join(cells) + "|"
    return text.replace(line, replacement, 1)


def _add_evidence_row(text: str, heading: str, row: str) -> str:
    section_start = text.index(heading)
    section_end = text.find("\n### ", section_start + len(heading))
    section_end = len(text) if section_end < 0 else section_end
    section = text[section_start:section_end]
    lines = section.splitlines()
    placeholder = next(
        (index for index, line in enumerate(lines) if line.startswith("| _none yet_ |")),
        None,
    )
    if placeholder is not None:
        lines[placeholder] = row
    else:
        last_table_row = max(index for index, line in enumerate(lines) if line.startswith("|"))
        lines.insert(last_table_row + 1, row)
    return f"{text[:section_start]}{'\n'.join(lines)}{text[section_end:]}"


def _deliver_r02(text: str, verification: str) -> str:
    delivered = _replace_ledger_cell(text, "GOV-002", 6, "`IN_DEVELOP`")
    delivered = _replace_ledger_cell(delivered, "VER-003", 6, "`IN_DEVELOP`")
    claim_line = next(
        line for line in delivered.splitlines() if line.startswith("| R0.2 | GOV-002, VER-003 |")
    )
    delivered = delivered.replace(claim_line, "", 1)
    return _add_evidence_row(
        delivered,
        "### 10.1 Develop transition evidence",
        (
            "| R0.2 | GOV-002, VER-003 | "
            "[#9991](https://github.com/mangowhoiscloud/geode/pull/9991) | "
            f"`{'e' * 40}` | {verification} |"
        ),
    )


def test_current_roadmap_satisfies_every_structural_invariant() -> None:
    roadmap = checker.parse_roadmap(ROADMAP)

    assert checker.validate_structure(roadmap) == []
    assert checker.validate_transitions(roadmap, roadmap, base_ref="origin/develop") == []


def test_duplicate_gap_and_package_ids_fail() -> None:
    gap_line = next(line for line in ROADMAP.splitlines() if line.startswith("| GOV-002 |"))
    duplicate_gap = ROADMAP.replace(gap_line, f"{gap_line}\n{gap_line}", 1)
    package_heading = "#### R0.2 Generated architecture baseline"
    duplicate_package = ROADMAP.replace(
        package_heading,
        f"{package_heading}\n\n{package_heading}",
        1,
    )

    gap_errors = checker.validate_structure(checker.parse_roadmap(duplicate_gap))
    package_errors = checker.validate_structure(checker.parse_roadmap(duplicate_package))

    assert any("duplicate GAP IDs: GOV-002" in error for error in gap_errors)
    assert any("duplicate package IDs in §7: R0.2" in error for error in package_errors)


def test_malformed_gap_id_is_a_parse_error_not_a_skipped_row() -> None:
    malformed = ROADMAP.replace("| GOV-004 |", "| GOV-99 |", 1)

    with pytest.raises(checker.RoadmapParseError, match="invalid GAP ID 'GOV-99'"):
        checker.parse_roadmap(malformed)


def test_missing_and_cyclic_dependencies_fail() -> None:
    missing = _replace_ledger_cell(ROADMAP, "GOV-004", 5, "GOV-999")
    cyclic = _replace_ledger_cell(ROADMAP, "GOV-001", 5, "GOV-003")

    missing_errors = checker.validate_structure(checker.parse_roadmap(missing))
    cyclic_errors = checker.validate_structure(checker.parse_roadmap(cyclic))

    assert any("GOV-004: missing dependencies: GOV-999" in error for error in missing_errors)
    assert any("dependency cycle:" in error for error in cyclic_errors)


def test_gap_contract_columns_are_required_and_registered_values_are_immutable() -> None:
    missing_exit = _replace_ledger_cell(ROADMAP, "GOV-004", 3, "—")
    invalid_audit = _replace_ledger_cell(ROADMAP, "GOV-004", 1, "`UNKNOWN`")
    rewritten_baseline = _replace_ledger_cell(
        ROADMAP,
        "GOV-004",
        2,
        "prospectively rewritten evidence",
    )

    missing_errors = checker.validate_structure(checker.parse_roadmap(missing_exit))
    audit_errors = checker.validate_structure(checker.parse_roadmap(invalid_audit))
    transition_errors = checker.validate_transitions(
        checker.parse_roadmap(ROADMAP),
        checker.parse_roadmap(rewritten_baseline),
        base_ref="origin/develop",
    )

    assert "GOV-004: exit condition is empty or not meaningful" in missing_errors
    assert "GOV-004: unknown audit class 'UNKNOWN'" in audit_errors
    assert "GOV-004: registered baseline evidence is immutable" in transition_errors


def test_html_comments_do_not_satisfy_gap_contract_evidence() -> None:
    hidden_baseline = _replace_ledger_cell(
        ROADMAP,
        "GOV-004",
        2,
        "<!-- no evidence -->",
    )
    hidden_exit = _replace_ledger_cell(
        ROADMAP,
        "GOV-004",
        3,
        "<!-- no exit -->",
    )

    baseline_errors = checker.validate_structure(checker.parse_roadmap(hidden_baseline))
    exit_errors = checker.validate_structure(checker.parse_roadmap(hidden_exit))

    assert "GOV-004: baseline evidence is empty or not meaningful" in baseline_errors
    assert "GOV-004: exit condition is empty or not meaningful" in exit_errors


def test_html_entities_do_not_satisfy_gap_contract_evidence() -> None:
    entities = _replace_ledger_cell(ROADMAP, "GOV-004", 2, "&nbsp;&nbsp;")
    entities = _replace_ledger_cell(entities, "GOV-004", 3, "&#160;&#160;")

    errors = checker.validate_structure(checker.parse_roadmap(entities))

    assert "GOV-004: baseline evidence is empty or not meaningful" in errors
    assert "GOV-004: exit condition is empty or not meaningful" in errors


def test_dependency_lists_reject_duplicates_and_non_gap_tokens() -> None:
    duplicate = _replace_ledger_cell(
        ROADMAP,
        "GOV-004",
        5,
        "GOV-002, GOV-002",
    )
    garbage = _replace_ledger_cell(
        ROADMAP,
        "GOV-004",
        5,
        "GOV-002, BANANA",
    )

    with pytest.raises(checker.RoadmapParseError, match="repeats GAP reference"):
        checker.parse_roadmap(duplicate)
    with pytest.raises(checker.RoadmapParseError, match="invalid GAP reference"):
        checker.parse_roadmap(garbage)


def test_every_gap_must_be_selected_once_by_its_ledger_package() -> None:
    missing_selection = ROADMAP.replace(
        "GAPs: GOV-002, VER-003.",
        "GAP: GOV-002.",
        1,
    )
    wrong_package = _replace_ledger_cell(ROADMAP, "GOV-002", 4, "R0.3")

    selection_errors = checker.validate_structure(checker.parse_roadmap(missing_selection))
    mapping_errors = checker.validate_structure(checker.parse_roadmap(wrong_package))

    assert any("VER-003: selected by 0 §7 packages" in error for error in selection_errors)
    assert any(
        "GOV-002: ledger package R0.3 != §7 package R0.2" in error for error in mapping_errors
    )


def test_package_status_and_active_claim_must_move_together() -> None:
    split_package = _replace_ledger_cell(ROADMAP, "VER-003", 6, "`READY`")
    missing_claim = ROADMAP.replace(
        next(
            line for line in ROADMAP.splitlines() if line.startswith("| R0.2 | GOV-002, VER-003 |")
        ),
        "",
        1,
    )

    split_errors = checker.validate_structure(checker.parse_roadmap(split_package))
    claim_errors = checker.validate_structure(checker.parse_roadmap(missing_claim))

    assert any("R0.2: non-atomic package statuses" in error for error in split_errors)
    assert any("R0.2: IN_PROGRESS package has no active claim" in error for error in claim_errors)


def test_claim_and_delivery_evidence_formats_fail_closed() -> None:
    bad_timestamp = ROADMAP.replace("2026-07-17T10:58:22Z", "2026-07-17 10:58:22", 1)
    bad_claim_link = ROADMAP
    for pr_number in ("2768", "2769"):
        bad_claim_link = bad_claim_link.replace(
            f"[#{pr_number}](https://github.com/mangowhoiscloud/geode/pull/{pr_number})",
            f"#{pr_number}",
            1,
        )
    bad_merge_sha = ROADMAP.replace(
        "`ab1a80e91f9947defc15fa97f5b4ce66126c0c13`",
        "`deadbeef`",
        1,
    )

    timestamp_errors = checker.validate_structure(checker.parse_roadmap(bad_timestamp))
    link_errors = checker.validate_structure(checker.parse_roadmap(bad_claim_link))
    sha_errors = checker.validate_structure(checker.parse_roadmap(bad_merge_sha))

    assert "R0.2: claimed-at timestamp must be ISO-8601 UTC" in timestamp_errors
    assert "R0.2: claim evidence must include a canonical PR link" in link_errors
    assert "R0.1: develop evidence requires a full 40-character merge SHA" in sha_errors


def test_delivered_package_requires_durable_develop_evidence() -> None:
    evidence_line = next(
        line for line in ROADMAP.splitlines() if line.startswith("| R0.1 | GOV-001, GOV-003 |")
    )
    without_evidence = ROADMAP.replace(evidence_line, "", 1)

    errors = checker.validate_structure(checker.parse_roadmap(without_evidence))

    assert "R0.1: delivered package lacks §10.1 evidence" in errors


def test_readiness_rejects_unsatisfied_external_dependency() -> None:
    promoted = _replace_ledger_cell(ROADMAP, "GOV-004", 6, "`READY`")
    current = checker.parse_roadmap(promoted)

    errors = checker.validate_structure(current)

    assert any("GOV-004: READY dependency GOV-002 is IN_PROGRESS" in error for error in errors)


def test_delivered_status_rejects_unsatisfied_external_dependency() -> None:
    delivered = _replace_ledger_cell(ROADMAP, "GOV-004", 6, "`IN_DEVELOP`")

    errors = checker.validate_structure(checker.parse_roadmap(delivered))

    assert any("GOV-004: IN_DEVELOP dependency GOV-002 is IN_PROGRESS" in error for error in errors)


def test_readiness_is_rechecked_when_status_does_not_change() -> None:
    ready = _replace_ledger_cell(ROADMAP, "GOV-004", 6, "`READY`")

    errors = checker.check(
        ready,
        ready,
        base_ref="origin/develop",
        target_branch="develop",
    )

    assert any("GOV-004: READY dependency GOV-002 is IN_PROGRESS" in error for error in errors)


def test_active_claim_cannot_be_stolen_without_release() -> None:
    changed = ROADMAP.replace(
        "`session=codex-2026-07-17 task=architecture-baseline`",
        "`session=someone-else task=architecture-baseline`",
        1,
    )

    errors = checker.validate_transitions(
        checker.parse_roadmap(ROADMAP),
        checker.parse_roadmap(changed),
        base_ref="origin/develop",
    )

    assert "R0.2: active claim changed without releasing the package" in errors


def test_illegal_jump_and_wrong_main_base_are_rejected() -> None:
    illegal_jump = _replace_ledger_cell(ROADMAP, "GOV-004", 6, "`IN_PROGRESS`")
    done = _replace_ledger_cell(ROADMAP, "GOV-001", 6, "`DONE`")
    done = _replace_ledger_cell(done, "GOV-003", 6, "`DONE`")
    base = checker.parse_roadmap(ROADMAP)

    jump_errors = checker.validate_transitions(
        base,
        checker.parse_roadmap(illegal_jump),
        base_ref="origin/develop",
    )
    done_errors = checker.validate_transitions(
        base,
        checker.parse_roadmap(done),
        base_ref="origin/develop",
    )

    assert any(
        "GOV-004: illegal status transition OPEN -> IN_PROGRESS" in error for error in jump_errors
    )
    assert any("DONE transition requires --base-ref origin/main" in error for error in done_errors)


def test_new_gap_cannot_reuse_an_existing_package_heading() -> None:
    ledger_anchor = next(line for line in ROADMAP.splitlines() if line.startswith("| VER-004 |"))
    new_row = "| GOV-999 | `ABSENT` | New evidence | New exit condition | R7.4 | — | `OPEN` |"
    current_text = ROADMAP.replace(ledger_anchor, f"{ledger_anchor}\n{new_row}", 1)
    release_heading = "#### R7.4 Documentation and release closure"
    current_text = current_text.replace(
        release_heading,
        f"{release_heading}\n\nGAP: GOV-999.",
        1,
    )

    errors = checker.validate_transitions(
        checker.parse_roadmap(ROADMAP),
        checker.parse_roadmap(current_text),
        base_ref="origin/develop",
    )

    assert "GOV-999: new GAP must use a new closure package, found R7.4" in errors


def test_evidence_rows_are_append_only() -> None:
    changed = ROADMAP.replace(
        "committed-diff re-review returned no findings",
        "rewritten evidence",
        1,
    )

    errors = checker.validate_transitions(
        checker.parse_roadmap(ROADMAP),
        checker.parse_roadmap(changed),
        base_ref="origin/develop",
    )

    assert any("evidence is append-only" in error for error in errors)


def test_prospective_delivery_evidence_is_rejected() -> None:
    sha = "a" * 40
    prospective_develop = _add_evidence_row(
        ROADMAP,
        "### 10.1 Develop transition evidence",
        (
            "| R0.3 | GOV-004 | "
            "[#9999](https://github.com/mangowhoiscloud/geode/pull/9999) | "
            f"`{sha}` | targeted tests passed |"
        ),
    )
    prospective_main = _add_evidence_row(
        ROADMAP,
        "### 10.2 Main closure evidence",
        (
            "| GOV-004 | "
            "[#9999](https://github.com/mangowhoiscloud/geode/pull/9999) | "
            f"`{sha}` | full gates passed | not applicable | docs synced |"
        ),
    )

    develop_errors = checker.validate_structure(checker.parse_roadmap(prospective_develop))
    main_errors = checker.validate_structure(checker.parse_roadmap(prospective_main))

    assert "R0.3: §10.1 evidence is prospective for package status OPEN" in develop_errors
    assert "GOV-004: §10.2 evidence is prospective for GAP status OPEN" in main_errors


def test_transition_requires_evidence_added_in_the_same_diff() -> None:
    sha = "b" * 40
    preseeded = _add_evidence_row(
        ROADMAP,
        "### 10.1 Develop transition evidence",
        (
            "| R0.2 | GOV-002, VER-003 | "
            "[#9998](https://github.com/mangowhoiscloud/geode/pull/9998) | "
            f"`{sha}` | targeted and full gates passed |"
        ),
    )
    delivered = _replace_ledger_cell(preseeded, "GOV-002", 6, "`IN_DEVELOP`")
    delivered = _replace_ledger_cell(delivered, "VER-003", 6, "`IN_DEVELOP`")
    claim_line = next(
        line for line in delivered.splitlines() if line.startswith("| R0.2 | GOV-002, VER-003 |")
    )
    delivered = delivered.replace(claim_line, "", 1)

    errors = checker.validate_transitions(
        checker.parse_roadmap(preseeded),
        checker.parse_roadmap(delivered),
        base_ref="origin/develop",
    )

    assert any("transition to IN_DEVELOP requires new §10.1 evidence" in error for error in errors)


def test_new_transition_evidence_requires_command_and_explicit_pass_result() -> None:
    delivered = _replace_ledger_cell(ROADMAP, "GOV-002", 6, "`IN_DEVELOP`")
    delivered = _replace_ledger_cell(delivered, "VER-003", 6, "`IN_DEVELOP`")
    claim_line = next(
        line for line in delivered.splitlines() if line.startswith("| R0.2 | GOV-002, VER-003 |")
    )
    delivered = delivered.replace(claim_line, "", 1)
    delivered = _add_evidence_row(
        delivered,
        "### 10.1 Develop transition evidence",
        (
            "| R0.2 | GOV-002, VER-003 | "
            "[#9991](https://github.com/mangowhoiscloud/geode/pull/9991) | "
            f"`{'e' * 40}` | targeted tests passed |"
        ),
    )

    errors = checker.validate_transitions(
        checker.parse_roadmap(ROADMAP),
        checker.parse_roadmap(delivered),
        base_ref="origin/develop",
    )

    assert "R0.2: new §10.1 verification must include an inline command and RESULT: PASS" in errors


def test_hidden_comment_evidence_cannot_supply_pr_sha_command_or_result() -> None:
    hidden = _deliver_r02(
        ROADMAP,
        "tests passed <!-- `uv run pytest` RESULT: PASS -->",
    )
    hidden = hidden.replace(
        "[#9991](https://github.com/mangowhoiscloud/geode/pull/9991)",
        "pending <!-- [#9991](https://github.com/mangowhoiscloud/geode/pull/9991) -->",
        1,
    )
    hidden = hidden.replace(
        f"`{'e' * 40}`",
        f"pending <!-- `{'e' * 40}` -->",
        1,
    )

    errors = checker.check(
        hidden,
        ROADMAP,
        base_ref="origin/develop",
        target_branch="develop",
    )

    assert "R0.2: develop evidence requires a canonical feature PR link" in errors
    assert "R0.2: develop evidence requires a full 40-character merge SHA" in errors
    assert "R0.2: new §10.1 verification must include an inline command and RESULT: PASS" in errors


@pytest.mark.parametrize(
    "verification",
    (
        "`uv run pytest` — RESULT: PASS=false",
        "tests didn't pass; `uv run pytest` — RESULT: PASS",
        "`uv run pytest` — RESULT: PASS/FAIL",
    ),
)
def test_structured_pass_rejects_suffixes_and_negative_language(
    verification: str,
) -> None:
    delivered = _deliver_r02(ROADMAP, verification)

    errors = checker.validate_transitions(
        checker.parse_roadmap(ROADMAP),
        checker.parse_roadmap(delivered),
        base_ref="origin/develop",
    )

    assert "R0.2: new §10.1 verification must include an inline command and RESULT: PASS" in errors


def test_new_decision_and_blocker_evidence_cannot_be_preseeded() -> None:
    decision = _add_evidence_row(
        ROADMAP,
        "### 10.3 Non-closure decision evidence",
        (
            "| GOV-004 | DEPENDENCY_REMOVED | GOV-002 | "
            "prospective dependency removal rationale | "
            "[#9996](https://github.com/mangowhoiscloud/geode/pull/9996) | "
            "affected packages re-audited and passed |"
        ),
    )
    blocker = _add_evidence_row(
        ROADMAP,
        "### 10.4 Blocker evidence",
        (
            "| R0.3 | GOV-004 | BLOCKED -> OPEN | prospective recovery | "
            "[#9995](https://github.com/mangowhoiscloud/geode/pull/9995) | "
            "dependency and exit criteria re-audited and passed |"
        ),
    )

    decision_errors = checker.validate_transitions(
        checker.parse_roadmap(ROADMAP),
        checker.parse_roadmap(decision),
        base_ref="origin/develop",
    )
    blocker_errors = checker.validate_transitions(
        checker.parse_roadmap(ROADMAP),
        checker.parse_roadmap(blocker),
        base_ref="origin/develop",
    )

    assert "GOV-004: new §10.3 evidence has no matching decision/edge transition" in decision_errors
    assert "R0.3: new §10.4 evidence has no matching package transition" in blocker_errors


def test_dependency_evidence_must_match_the_exact_known_edge_delta() -> None:
    removal = _replace_ledger_cell(ROADMAP, "GOV-004", 5, "—")
    removal = _add_evidence_row(
        removal,
        "### 10.3 Non-closure decision evidence",
        (
            "| GOV-004 | DEPENDENCY_REMOVED | GOV-002, GOV-001 | "
            "dependency contract was narrowed after provider re-audit | "
            "[#9994](https://github.com/mangowhoiscloud/geode/pull/9994) | "
            "`uv run pytest tests/scripts/test_check_architecture_roadmap.py` "
            "— RESULT: PASS |"
        ),
    )
    addition_without_evidence = _replace_ledger_cell(
        ROADMAP,
        "GOV-004",
        5,
        "GOV-002, GOV-001",
    )

    removal_errors = checker.validate_transitions(
        checker.parse_roadmap(ROADMAP),
        checker.parse_roadmap(removal),
        base_ref="origin/develop",
    )
    addition_errors = checker.validate_transitions(
        checker.parse_roadmap(ROADMAP),
        checker.parse_roadmap(addition_without_evidence),
        base_ref="origin/develop",
    )

    assert any("removed without exact new §10.3 evidence" in error for error in removal_errors)
    assert any(
        "new §10.3 evidence has no matching decision/edge transition" in error
        for error in removal_errors
    )
    assert any("added without exact new §10.3 evidence" in error for error in addition_errors)


def test_decision_evidence_rejects_unknown_and_self_references() -> None:
    decision = _add_evidence_row(
        ROADMAP,
        "### 10.3 Non-closure decision evidence",
        (
            "| GOV-004 | DEPENDENCY_ADDED | GOV-004, GOV-999 | "
            "dependency contract changed after an explicit re-audit | "
            "[#9993](https://github.com/mangowhoiscloud/geode/pull/9993) | "
            "affected packages re-audited and passed |"
        ),
    )

    errors = checker.validate_structure(checker.parse_roadmap(decision))

    assert "GOV-004: decision evidence names unknown GAPs: GOV-999" in errors
    assert "GOV-004: decision evidence cannot reference itself" in errors


def test_terminal_decision_requires_downstream_edge_reconciliation_or_block() -> None:
    superseded = _replace_ledger_cell(ROADMAP, "GOV-002", 6, "`SUPERSEDED`")
    superseded = _replace_ledger_cell(superseded, "VER-003", 6, "`SUPERSEDED`")
    claim_line = next(
        line for line in superseded.splitlines() if line.startswith("| R0.2 | GOV-002, VER-003 |")
    )
    superseded = superseded.replace(claim_line, "", 1)
    for gap_id in ("GOV-002", "VER-003"):
        superseded = _add_evidence_row(
            superseded,
            "### 10.3 Non-closure decision evidence",
            (
                f"| {gap_id} | SUPERSEDED | GOV-004 | "
                "replacement contract was selected after architecture re-audit | "
                "[#9990](https://github.com/mangowhoiscloud/geode/pull/9990) | "
                "`uv run pytest tests/scripts/test_check_architecture_roadmap.py` "
                "— RESULT: PASS |"
            ),
        )

    errors = checker.validate_structure(checker.parse_roadmap(superseded))

    assert any(
        "GOV-004: dependencies on terminal decisions must be "
        "rewritten/removed or the package BLOCKED: GOV-002" in error
        for error in errors
    )


def test_blocked_recovery_requires_a_new_matching_event_row() -> None:
    blocked = _replace_ledger_cell(ROADMAP, "GOV-004", 6, "`BLOCKED`")
    blocked = _add_evidence_row(
        blocked,
        "### 10.4 Blocker evidence",
        (
            "| R0.3 | GOV-004 | OPEN -> BLOCKED | upstream contract unavailable | "
            "[#9997](https://github.com/mangowhoiscloud/geode/pull/9997) | "
            "dependency and exit criteria audited; BLOCKED confirmed |"
        ),
    )
    recovered_without_event = _replace_ledger_cell(blocked, "GOV-004", 6, "`OPEN`")

    errors = checker.validate_transitions(
        checker.parse_roadmap(blocked),
        checker.parse_roadmap(recovered_without_event),
        base_ref="origin/develop",
    )

    assert any("BLOCKED -> OPEN requires a new matching §10.4 row" in error for error in errors)


def test_missing_base_document_fails_closed_except_exact_develop_promotion() -> None:
    rewritten = _replace_ledger_cell(
        ROADMAP,
        "GOV-004",
        2,
        "attacker-controlled replacement",
    )

    untrusted_errors = checker.check(
        rewritten,
        None,
        base_ref="origin/main",
        target_branch="main",
    )
    exact_promotion_errors = checker.check(
        ROADMAP,
        None,
        base_ref="origin/main",
        target_branch="main",
        trusted_develop_text=ROADMAP,
    )
    push_promotion_errors = checker.check(
        ROADMAP,
        None,
        base_ref="a" * 40,
        target_branch="main",
        event_mode="push",
        trusted_develop_text=ROADMAP,
    )
    mismatched_promotion_errors = checker.check(
        rewritten,
        None,
        base_ref="origin/main",
        target_branch="main",
        trusted_develop_text=ROADMAP,
    )

    assert any(
        "only trusted develop -> main promotion may bootstrap" in error
        for error in untrusted_errors
    )
    assert exact_promotion_errors == []
    assert push_promotion_errors == []
    assert any(
        "must carry the exact complete roadmap" in error for error in mismatched_promotion_errors
    )


def test_main_to_develop_sync_uses_main_as_the_canonical_ledger() -> None:
    done = _replace_ledger_cell(ROADMAP, "GOV-001", 6, "`DONE`")
    done = _replace_ledger_cell(done, "GOV-003", 6, "`DONE`")
    main_sha = "c" * 40
    for gap_id in ("GOV-001", "GOV-003"):
        done = _add_evidence_row(
            done,
            "### 10.2 Main closure evidence",
            (
                f"| {gap_id} | "
                "[#2767](https://github.com/mangowhoiscloud/geode/pull/2767) | "
                f'`{main_sha}` | `uv run pytest tests/ -m "not live"` — RESULT: PASS | '
                "compatibility verified | "
                "public docs synced |"
            ),
        )

    assert (
        checker.check(
            done,
            done,
            base_ref="origin/main",
            target_branch="main",
        )
        == []
    )
    trusted_main = _replace_ledger_cell(done, "GOV-002", 6, "`READY`")
    trusted_main = _replace_ledger_cell(trusted_main, "VER-003", 6, "`READY`")
    trusted_claim = next(
        line for line in trusted_main.splitlines() if line.startswith("| R0.2 | GOV-002, VER-003 |")
    )
    trusted_main = trusted_main.replace(trusted_claim, "", 1)
    assert (
        checker.check(
            done,
            ROADMAP,
            base_ref="origin/develop",
            target_branch="develop",
            trusted_main_text=trusted_main,
        )
        == []
    )
    wrong_base_errors = checker.check(
        done,
        ROADMAP,
        base_ref="origin/develop",
        target_branch="develop",
    )
    assert any(
        "DONE transition requires --base-ref origin/main" in error for error in wrong_base_errors
    )


def test_main_tracking_rejects_develop_only_claim_transitions() -> None:
    ready_base = _replace_ledger_cell(ROADMAP, "GOV-002", 6, "`READY`")
    ready_base = _replace_ledger_cell(ready_base, "VER-003", 6, "`READY`")
    claim_line = next(
        line for line in ready_base.splitlines() if line.startswith("| R0.2 | GOV-002, VER-003 |")
    )
    ready_base = ready_base.replace(claim_line, "", 1)

    errors = checker.check(
        ROADMAP,
        ready_base,
        base_ref="origin/main",
        target_branch="main",
    )

    assert any(
        "main tracking permits only IN_DEVELOP -> DONE, found READY -> IN_PROGRESS" in error
        for error in errors
    )
    assert "main tracking cannot change active claims" in errors


def test_main_modes_reject_protocol_or_frontmatter_rewrites() -> None:
    rewritten = ROADMAP.replace(
        "This roadmap is an execution ledger, not a proposal archive.",
        "This roadmap is optional prose, not an execution ledger.",
        1,
    )

    tracking_errors = checker.check(
        rewritten,
        ROADMAP,
        base_ref="origin/main",
        target_branch="main",
    )
    promotion_errors = checker.check(
        rewritten,
        None,
        base_ref="origin/main",
        target_branch="main",
        trusted_develop_text=ROADMAP,
    )

    assert any("cannot change roadmap prose, frontmatter" in error for error in tracking_errors)
    assert any("must carry the exact complete roadmap" in error for error in promotion_errors)


def test_push_mode_uses_the_pre_push_sha_not_the_updated_remote_ref() -> None:
    rewritten = _replace_ledger_cell(
        ROADMAP,
        "GOV-004",
        2,
        "rewritten directly on the protected branch",
    )

    errors = checker.check(
        rewritten,
        ROADMAP,
        base_ref="a" * 40,
        target_branch="develop",
        event_mode="push",
        trusted_main_text=ROADMAP,
    )
    zero_sha_errors = checker.check(
        ROADMAP,
        ROADMAP,
        base_ref="0" * 40,
        target_branch="develop",
        event_mode="push",
        trusted_main_text=ROADMAP,
    )

    assert "GOV-004: registered baseline evidence is immutable" in errors
    assert any(
        "non-zero 40-character github.event.before SHA" in error for error in zero_sha_errors
    )


def test_failed_language_and_one_character_main_evidence_fail_closed() -> None:
    done = _replace_ledger_cell(ROADMAP, "GOV-001", 6, "`DONE`")
    done = _replace_ledger_cell(done, "GOV-003", 6, "`DONE`")
    main_sha = "d" * 40
    for gap_id in ("GOV-001", "GOV-003"):
        done = _add_evidence_row(
            done,
            "### 10.2 Main closure evidence",
            (
                f"| {gap_id} | "
                "[#9992](https://github.com/mangowhoiscloud/geode/pull/9992) | "
                f"`{main_sha}` | tests failed; not passed | x | x |"
            ),
        )

    errors = checker.validate_structure(checker.parse_roadmap(done))

    assert "GOV-001: main evidence must state a verification result" in errors
    assert "GOV-001: main migration/compatibility evidence is not meaningful" in errors
    assert "GOV-001: main documentation evidence is not meaningful" in errors


def test_ci_covers_managed_outputs_and_main_to_develop_sync() -> None:
    assert "- 'AGENTS.md'" in CI_WORKFLOW
    assert "- 'site/src/data/geode/architecture-baseline.json'" in CI_WORKFLOW
    assert "github.event.pull_request.head.repo.full_name == github.repository" in CI_WORKFLOW
    assert "github.base_ref == 'develop' && github.head_ref == 'main'" in CI_WORKFLOW
    assert "--trusted-main-ref" in CI_WORKFLOW
    assert "github.base_ref == 'main' && github.head_ref == 'develop'" in CI_WORKFLOW
    assert "--trusted-develop-ref" in CI_WORKFLOW
    assert "--target-branch" in CI_WORKFLOW
    assert "--event-mode" in CI_WORKFLOW
    assert "github.event.before" in CI_WORKFLOW
    assert "ROADMAP_PUSH_BASE_REF" in CI_WORKFLOW
    assert "0000000000000000000000000000000000000000" in CI_WORKFLOW
    assert "- 'CHANGELOG.md'" in CI_WORKFLOW
