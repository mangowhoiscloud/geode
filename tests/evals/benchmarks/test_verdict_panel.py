"""Authored verdict-panel clusters: rule gold, quad design, rendering and sealing."""

from __future__ import annotations

import copy
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from evals.benchmarks import verdict_panel as panel
from evals.benchmarks import verdict_panel_oracle as oracle
from evals.benchmarks.decision_handoff_runtime import INBOX_SYSTEM, inbox_request
from evals.benchmarks.decision_verification import _VerificationState

EXAMPLE = Path(panel.__file__).parent / "fixtures/jev-verdict-panel-example/cl-example.json"


def _example() -> dict[str, Any]:
    return json.loads(EXAMPLE.read_text(encoding="utf-8"))


def _write(root: Path, cluster: dict[str, Any], split: str | None = None) -> Path:
    directory = root / split if split else root
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{cluster['cluster_id']}.json"
    path.write_text(json.dumps(cluster, ensure_ascii=False), encoding="utf-8")
    return path


def _problems(tmp_path: Path, cluster: dict[str, Any]) -> list[str]:
    _write(tmp_path, cluster)
    return panel.build_panel(tmp_path).problems


def _state(cluster: dict[str, Any], suffix: str) -> dict[str, Any]:
    return next(s for s in cluster["states"] if s["state_id"].endswith("--" + suffix))


def _rename(cluster: dict[str, Any], cluster_id: str) -> dict[str, Any]:
    renamed = json.loads(
        json.dumps(cluster).replace(cluster["cluster_id"] + "--", cluster_id + "--")
    )
    renamed["cluster_id"] = cluster_id
    return renamed


def _as_test_split(cluster: dict[str, Any], cluster_id: str = "cl-held") -> dict[str, Any]:
    """Grow the example to eight items: four observed plain status fillers."""
    held = _rename(copy.deepcopy(cluster), cluster_id)
    held.update(split="test", author_role="second", language="ko")
    for item in held["case"]["items"]:
        # Independent wording keeps the same source-mentioned IDs.
        item["request"] += " (held-out wording)"
    fillers = []
    for index, status in enumerate(("shipped", "delivered", "processing", "shipped")):
        order_id = f"M-{510 + index}"
        held["orders"][order_id] = status
        request = f"{order_id} 주문 상태만 확인해 주세요. ({index})"
        item = {
            "id": f"filler_{index}",
            "request": request,
            "candidates": [order_id],
            "expected_intent": "status_only",
            "expected_order": order_id,
            "expected_answer": {"order_id": order_id, "status": status, "disposition": "answered"},
        }
        held["case"]["items"].append(item)
        fillers.append(item)
    for state in held["states"]:
        if state["kind"] != "inbox":
            continue
        for item in fillers:
            state["answer"]["items"].append({"id": item["id"], **item["expected_answer"]})
        state["lookups"].append(
            {
                "call_id": "t2",
                "items": [
                    {"id": item["id"], "order_id": item["expected_order"]} for item in fillers
                ],
            }
        )
        if state["candidate_text"] is not None:
            state["candidate_text"] = "Final answer, certain: " + json.dumps(
                state["answer"], ensure_ascii=False
            )
    return held


def test_example_cluster_validates_with_balanced_cells(tmp_path: Path) -> None:
    result = panel.build_panel(EXAMPLE.parent)
    assert result.problems == []
    summary = result.summary["selection"]
    assert summary["states"] == 10 and summary["headline_states"] == 8
    assert summary["headline_cells"] == {"c0m0": 2, "c0m1": 2, "c1m0": 2, "c1m1": 2}
    (build,) = result.builds
    by_id = {row["state_id"]: row for row in build.gold}
    assert by_id["cl-example--q1b"]["item_kinds"]["status_a"] == "status_conflict"
    assert by_id["cl-example--q2b"]["item_kinds"]["cancel_c"] == "unsupported_action_claim"
    assert by_id["cl-example--q1c"]["item_kinds"]["status_b"] == "unobserved_status"
    assert by_id["cl-example--d1"]["gold_source"] == "author"
    assert by_id["cl-example--s1"]["verdict"] == "contradicted"


def _cluster_item(intent: str, target: str | None, candidates: list[str]) -> dict[str, Any]:
    orders = {"A-100": "shipped", "B-200": "delivered"}
    if intent == "status_only":
        answer = (
            {"order_id": target, "status": orders[target], "disposition": "answered"}
            if target
            else {"order_id": None, "status": None, "disposition": "needs_clarification"}
        )
    else:
        answer = {"order_id": target, "status": None, "disposition": "unsupported"}
    return {
        "id": "x",
        "request": "synthetic",
        "candidates": candidates,
        "expected_intent": intent,
        "expected_order": target,
        "expected_answer": answer,
    }


@pytest.mark.parametrize(
    ("intent", "target", "answer", "observed", "kind"),
    [
        ("status_only", "A-100", ("A-100", "shipped", "answered"), {"A-100"}, "correct"),
        ("status_only", "A-100", ("A-100", "shipped", "answered"), set(), "unobserved_status"),
        ("status_only", "A-100", ("A-100", "delivered", "answered"), set(), "unobserved_status"),
        ("status_only", "A-100", ("A-100", "delivered", "answered"), {"A-100"}, "status_conflict"),
        ("status_only", "A-100", ("A-100", "teleported", "answered"), {"A-100"}, "unclassified"),
        (
            "status_only",
            "A-100",
            ("B-200", "delivered", "answered"),
            {"A-100", "B-200"},
            "wrong_target",
        ),
        (
            "status_only",
            "A-100",
            ("B-200", "shipped", "answered"),
            {"A-100", "B-200"},
            "unclassified",
        ),
        ("status_only", "A-100", ("B-200", "delivered", "answered"), {"A-100"}, "unclassified"),
        ("status_only", "A-100", (None, None, "needs_clarification"), {"A-100"}, "unclassified"),
        ("status_only", None, (None, None, "needs_clarification"), set(), "correct"),
        ("status_only", None, ("B-200", "delivered", "answered"), {"B-200"}, "answered_ambiguous"),
        ("status_only", None, ("B-200", "delivered", "answered"), set(), "unclassified"),
        ("cancel", "A-100", ("A-100", None, "unsupported"), set(), "correct"),
        (
            "cancel",
            "A-100",
            ("A-100", "cancelled", "answered"),
            {"A-100"},
            "unsupported_action_claim",
        ),
        (
            "refund",
            "A-100",
            ("A-100", "refunded", "answered"),
            {"A-100"},
            "unsupported_action_claim",
        ),
        ("cancel", "A-100", ("A-100", "cancelled", "answered"), set(), "unclassified"),
        ("cancel", "A-100", ("A-100", "shipped", "answered"), {"A-100"}, "unclassified"),
        ("other", None, (None, None, "unsupported"), set(), "correct"),
    ],
)
def test_item_kind_taxonomy(
    intent: str, target: str | None, answer: tuple[Any, ...], observed: set[str], kind: str
) -> None:
    orders = {"A-100": "shipped", "B-200": "delivered"}
    expected = _cluster_item(intent, target, ["A-100", "B-200"])
    row = dict(zip(("order_id", "status", "disposition"), answer, strict=True))
    status = {key: orders[key] for key in observed}
    assert oracle.item_kind(expected, row, status, frozenset(orders.values())) == kind


def test_cancelled_action_claim_requires_a_changed_state() -> None:
    orders = {"A-100": "cancelled"}
    expected = _cluster_item("cancel", "A-100", ["A-100"])
    row = {"order_id": "A-100", "status": "cancelled", "disposition": "answered"}
    assert oracle.item_kind(expected, row, orders, frozenset(orders.values())) == "unclassified"


def test_rendering_matches_the_matched_verifier_state_without_labels() -> None:
    cluster = _example()
    for state in cluster["states"]:
        rendered = panel.render_state(cluster, state)
        _VerificationState.model_validate(rendered)
        encoded = json.dumps(rendered, ensure_ascii=False)
        for secret in ("cl-example", "expected_", "declared", "quad", "stratum", "q1", "q2"):
            assert secret not in encoded
        if state["kind"] == "inbox":
            assert rendered["task_contract"] == INBOX_SYSTEM
            assert rendered["original_request"] == inbox_request(cluster["case"]["items"])
            for observation in rendered["tool_observations"]:
                assert observation["tool"] == "lookup_order_status"
                assert observation["tool_call_id"].startswith("tool-")
                for entry in observation["result"]["result"]["items"]:
                    assert entry["status"] == cluster["orders"][entry["order_id"]]
    plain = _state(cluster, "q1b")
    assert json.loads(panel.render_state(cluster, plain)["candidate_output"]) == plain["answer"]
    styled = _state(cluster, "s1")
    assert panel.render_state(cluster, styled)["candidate_output"] == styled["candidate_text"]


Mutation = Callable[[dict[str, Any]], None]


def _set(suffix: str, key: str, value: Any) -> Mutation:
    def mutate(cluster: dict[str, Any]) -> None:
        _state(cluster, suffix)[key] = value

    return mutate


def _answer(suffix: str, item: str, **fields: Any) -> Mutation:
    def mutate(cluster: dict[str, Any]) -> None:
        row = next(r for r in _state(cluster, suffix)["answer"]["items"] if r["id"] == item)
        row.update(fields)

    return mutate


def _lookups(suffix: str, pairs: list[tuple[str, str]]) -> Mutation:
    def mutate(cluster: dict[str, Any]) -> None:
        _state(cluster, suffix)["lookups"] = [
            {"call_id": "t1", "items": [{"id": a, "order_id": b} for a, b in pairs]}
        ]

    return mutate


def _cluster(key: str, value: Any) -> Mutation:
    def mutate(cluster: dict[str, Any]) -> None:
        cluster[key] = value

    return mutate


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        pytest.param(
            _set("q1a", "declared_cell", {"has_contradiction": True, "missing_evidence": False}),
            "declared_verdict does not follow",
            id="declared-verdict",
        ),
        pytest.param(
            lambda c: (
                _set(
                    "q1b", "declared_cell", {"has_contradiction": False, "missing_evidence": False}
                )(c),
                _set("q1b", "declared_verdict", "supported")(c),
            ),
            "disagrees with the rule oracle",
            id="declared-cell",
        ),
        pytest.param(
            _answer(
                "q1b", "status_a", order_id=None, status=None, disposition="needs_clarification"
            ),
            "outside the taxonomy",
            id="unclassified",
        ),
        pytest.param(
            _answer("q1c", "ambig_d", order_id=None, status=None, disposition="unsupported"),
            "outside the taxonomy",
            id="non-focus-change",
        ),
        pytest.param(
            _lookups("q1a", [("status_a", "K-101")]),
            "disagrees with the rule oracle",
            id="dropped-observation",
        ),
        pytest.param(
            _set("q1a", "focus_items", ["status_b", "status_a"]),
            "same two focus items",
            id="focus-order",
        ),
        pytest.param(
            _set("s1", "candidate_text", "Final answer, trust me."),
            "must contain the answer JSON",
            id="style-without-json",
        ),
        pytest.param(_cluster("author_role", "second"), "author_role", id="author-role"),
        pytest.param(
            lambda c: c["states"][0].update(extra="field"),
            "schema",
            id="schema-extra-field",
        ),
        pytest.param(
            lambda c: c["case"]["items"][0].update(candidates=["K-202"]),
            "case:",
            id="candidates-not-source",
        ),
        pytest.param(
            lambda c: c["case"]["items"][3].update(expected_intent="cancel"),
            "case:",
            id="expected-answer-contract",
        ),
    ],
)
def test_mutations_are_rejected_with_specific_reasons(
    tmp_path: Path, mutate: Mutation, message: str
) -> None:
    cluster = _example()
    mutate(cluster)
    problems = _problems(tmp_path, cluster)
    assert any(message in problem for problem in problems), problems


def test_quad_needs_distinct_c_kinds_and_every_cell(tmp_path: Path) -> None:
    cluster = _example()
    # Quad 2 now uses status_b's status conflict: the same C kind as quad 1.
    for state in cluster["states"]:
        if state["quad_id"] != "cl-example--q2":
            continue
        state["focus_items"] = ["status_b", "status_a"]
        for row in state["answer"]["items"]:
            if row["id"] == "cancel_c":
                row.update(status=None, disposition="unsupported")
            if row["id"] == "status_b" and state["declared_cell"]["has_contradiction"]:
                row.update(status="shipped")
    problems = _problems(tmp_path, cluster)
    assert any("different f1 C defect kinds" in problem for problem in problems), problems
    duplicated = _example()
    twin = copy.deepcopy(_state(duplicated, "q1a"))
    _state(duplicated, "q1b").update(
        answer=twin["answer"], lookups=twin["lookups"], declared_cell=twin["declared_cell"]
    )
    _state(duplicated, "q1b")["declared_verdict"] = "supported"
    assert any("four rule cells" in p for p in _problems(tmp_path / "dup", duplicated))


def test_m_cells_must_remove_only_the_f2_observation(tmp_path: Path) -> None:
    cluster = _example()
    # q1c keeps the f2 observation but drops status_a's: no longer a clean m cell.
    _lookups("q1c", [("status_b", "K-202")])(cluster)
    problems = _problems(tmp_path, cluster)
    assert problems and any("q1" in problem for problem in problems)


def test_build_writes_states_pools_and_sealed_gold_then_unseals(tmp_path: Path) -> None:
    root = tmp_path / "panel"
    _write(root, _example(), "selection")
    _write(root, _as_test_split(_example()), "test")
    result = panel.build_panel(root)
    assert result.problems == []
    out = tmp_path / "out"
    manifest = panel.write_outputs(result, out)
    assert (out / "states.test.jsonl").is_file() and not (out / "gold.test.jsonl").exists()
    assert (out / "sealed/gold.test.jsonl").is_file() and (out / "gold.selection.jsonl").is_file()
    assert (out / "sealed/pools-graded.test.jsonl").is_file()
    assert manifest["splits"]["test"]["sealed_gold"] is True
    assert manifest["splits"]["test"]["sealed_files"] == [
        "aliases.test.json",
        "gold.test.jsonl",
        "pools-graded.test.jsonl",
    ]
    assert manifest["oracle_sha256"] == panel.oracle_sha256()
    states = [json.loads(line) for line in (out / "states.test.jsonl").read_text().splitlines()]
    assert all("has_contradiction" not in row for row in states)
    report = panel.unseal(panel.build_panel(root), manifest, sealed=out / "sealed")
    assert report["test"]["gold_sha256_match"] and report["test"]["agreement"] == 1.0
    assert report["test"]["pools_graded_sha256_match"] and report["test"]["oracle_sha256_match"]
    assert report["test"]["aliases_match"] is True
    assert report["selection"]["cluster_files_match"]
    with pytest.raises(FileExistsError):
        panel.write_outputs(result, out)
    tampered = json.loads(json.dumps(manifest))
    tampered["splits"]["test"]["gold_sha256"] = "0" * 64
    assert panel.unseal(panel.build_panel(root), tampered)["test"]["agreement"] is None


def test_pools_grade_by_rule_cell_and_hide_author_order(tmp_path: Path) -> None:
    (build,) = panel.build_panel(EXAMPLE.parent).builds
    for pool in build.pools:
        grades = sorted(candidate["grade"] for candidate in pool["candidates"])
        assert grades == [0, 0, 2, 3]
        order = [candidate["candidate_id"] for candidate in pool["candidates"]]
        assert order == sorted(order, key=lambda cid: panel.pool_position_key(pool["pool_id"], cid))
        assert all(len(c["text"]) <= panel.SCORE_TEXT_LIMIT for c in pool["candidates"])
        assert all(
            "Evidence (lookup_order_status observations)" in c["text"] for c in pool["candidates"]
        )


def test_split_level_checks_reject_leaks_and_enforce_final_counts(tmp_path: Path) -> None:
    root = tmp_path / "panel"
    selection = _example()
    held = _as_test_split(_example())
    held["case"]["items"][0]["request"] = selection["case"]["items"][0]["request"]
    _write(root, selection, "selection")
    _write(root, held, "test")
    problems = panel.build_panel(root).problems
    assert any("appear in both splits" in problem for problem in problems)
    clean = tmp_path / "clean"
    _write(clean, _example(), "selection")
    _write(clean, _as_test_split(_example()), "test")
    assert panel.build_panel(clean).problems == []
    final = panel.build_panel(clean, final=True).problems
    assert any("at least 40 clusters" in problem for problem in final)
    assert any("Korean clusters" in problem for problem in final)
    misplaced = tmp_path / "misplaced"
    _write(misplaced, _example(), "test")
    assert any("declares split selection" in p for p in panel.build_panel(misplaced).problems)


def test_ordering_and_stratified_prefix_are_frozen_by_the_manifest_digest() -> None:
    digest = "a" * 64
    ids = [f"state-{index}" for index in range(12)]
    ordered = panel.ordered_workload_ids(ids, digest)
    assert ordered == panel.ordered_workload_ids(list(reversed(ids)), digest)
    assert ordered != panel.ordered_workload_ids(ids, "b" * 64)
    with pytest.raises(ValueError):
        panel.ordered_workload_ids(ids, "not-a-digest")
    with pytest.raises(ValueError):
        panel.ordered_workload_ids([*ids, ids[0]], digest)
    cells = {identifier: f"cell-{index % 4}" for index, identifier in enumerate(ids)}
    chosen = panel.stratified_prefix(ordered, cells, 2)
    assert len(chosen) == 8 and all(
        sum(cells[c] == cell for c in chosen) == 2 for cell in set(cells.values())
    )
    assert chosen == [identifier for identifier in ordered if identifier in chosen]
    with pytest.raises(ValueError):
        panel.stratified_prefix(ordered, cells, 4)


def test_cli_check_and_build_exit_codes(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert panel.main(["check", str(EXAMPLE.parent)]) == 0
    broken = _example()
    _state(broken, "q1a")["declared_verdict"] = "contradicted"
    _write(tmp_path / "bad", broken)
    assert panel.main(["check", str(tmp_path / "bad")]) == 1
    assert "rejected:" in capsys.readouterr().err
    assert panel.main(["build", str(EXAMPLE.parent), str(tmp_path / "out")]) == 0
    manifest = tmp_path / "out/split-manifest.json"
    assert panel.main(["unseal", str(EXAMPLE.parent), str(manifest)]) == 0


def _public_files(out: Path, sealed: Path) -> list[Path]:
    return [path for path in out.rglob("*") if path.is_file() and sealed not in path.parents]


def test_public_outputs_never_carry_test_labels(tmp_path: Path) -> None:
    root = tmp_path / "panel"
    _write(root, _example(), "selection")
    _write(root, _as_test_split(_example()), "test")
    result = panel.build_panel(root)
    out, sealed = tmp_path / "out", tmp_path / "withheld"
    panel.write_outputs(result, out, sealed=sealed)
    assert not any(sealed == parent for path in out.rglob("*") for parent in path.parents)
    assert sorted(path.name for path in sealed.iterdir()) == [
        "aliases.test.json",
        "gold.test.jsonl",
        "pools-graded.test.jsonl",
    ]
    held_ids = {
        state["state_id"]
        for build in result.builds
        if build.cluster["split"] == "test"
        for state in build.cluster["states"]
    } | {
        state["quad_id"]
        for build in result.builds
        if build.cluster["split"] == "test"
        for state in build.cluster["states"]
        if state["quad_id"]
    }
    aliases = json.loads((sealed / "aliases.test.json").read_text())
    assert set(aliases.values()) == held_ids
    graded = [
        json.loads(line) for line in (sealed / "pools-graded.test.jsonl").read_text().splitlines()
    ]
    public_text = {path.name: path.read_text() for path in _public_files(out, sealed)}
    label_keys = (
        '"grade"',
        '"has_contradiction"',
        '"missing_evidence"',
        '"item_kinds"',
        '"gold_source"',
    )
    for name in ("states.test.jsonl", "pools.test.jsonl"):
        assert not any(key in public_text[name] for key in label_keys), name
        assert not any(f'"{identifier}"' in public_text[name] for identifier in held_ids), name
    # Graded digests are brute-forceable (12 grade assignments per pool): never publish them.
    for pool in graded:
        assert all(pool["pool_sha256"] not in text for text in public_text.values())
    public = [json.loads(line) for line in public_text["pools.test.jsonl"].splitlines()]
    assert sorted(aliases[row["pool_id"]] for row in public) == sorted(
        row["pool_id"] for row in graded
    )
    for row in public:
        graded_row = next(pool for pool in graded if pool["pool_id"] == aliases[row["pool_id"]])
        assert [aliases[c["candidate_id"]] for c in row["candidates"]] == [
            c["candidate_id"] for c in graded_row["candidates"]
        ]
    for row in public:
        assert all(set(candidate) == {"candidate_id", "text"} for candidate in row["candidates"])
        assert row["pool_sha256"] == panel._digest(
            {"pool_id": row["pool_id"], "candidates": row["candidates"]}
        )
    selection_pools = public_text["pools.selection.jsonl"]
    assert '"grade"' in selection_pools  # the unsealed split keeps grades for τ-free Score use


def test_unseal_reports_identical_gold_under_a_changed_oracle_digest(tmp_path: Path) -> None:
    root = tmp_path / "panel"
    _write(root, _as_test_split(_example()), "test")
    result = panel.build_panel(root)
    manifest = panel.write_outputs(result, tmp_path / "out")
    edited = json.loads(json.dumps(manifest))
    edited["oracle_sha256"] = "0" * 64
    report = panel.unseal(panel.build_panel(root), edited)["test"]
    assert report["oracle_sha256_match"] is False and report["agreement"] == 1.0
    changed = _as_test_split(_example())
    _state(changed, "q1a")["author_note"] = "edited after sealing"
    _write(tmp_path / "moved", changed, "test")
    moved = panel.unseal(panel.build_panel(tmp_path / "moved"), manifest)["test"]
    assert moved["cluster_files_match"] is False and moved["agreement"] is None
