"""Authored verdict-panel clusters: schema checks, rule oracle, rendering and split manifest.

A cluster is one synthetic read-only order inbox plus at most ten verification
states. Gold for inbox states is recomputed from the structured answer and the
observed lookups; authors' declared cells are only cross-checks. Rendering reuses
the runtime inbox contract and request builder, so panel inputs match the matched
verifier's E2E state shape. Nothing here dispatches a model call.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import re
import secrets
import sys
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from evals.benchmarks.verdict_panel_oracle import (
    C_KINDS,
    ITEM_KINDS,
    POOL_GRADES,
    RuleGold,
    observed_statuses,
    rule_gold,
    verdict_for,
)

SCHEMA_ID = "geode.jev-verdict-panel-cluster@1"
MANIFEST_SCHEMA_ID = "geode.jev-verdict-panel-manifest@1"
BUILDER_VERSION = "jev-verdict-panel-builder@1"
REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = REPO_ROOT / "docs/eval/schemas/jev-verdict-panel-cluster.schema.json"
LOOKUP_TOOL = "lookup_order_status"
HEADLINE_STRATA = frozenset({"envelope"})
SPLIT_ROLES = {"selection": "primary", "test": "second"}
SPLIT_ITEM_RANGES = {"selection": (4, 12), "test": (8, 12)}
SCORE_TEXT_LIMIT = 2000
MAX_STATES_PER_CLUSTER = 10
QUADS_PER_CLUSTER = 2
MIN_KOREAN_SHARE = 0.3
SELECTION_CLUSTER_SHARE = (0.35, 0.45)
MIN_CLUSTERS = 40


def _canonical(value: Any) -> str:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    )


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _digest(value: Any) -> str:
    return _sha256_text(_canonical(value))


def _jsonl(rows: Iterable[Mapping[str, Any]]) -> str:
    return "".join(_canonical(row) + "\n" for row in rows)


def _tool_call_id(state_id: str, call_id: str) -> str:
    # Opaque: the judge never sees state, quad or cell identifiers.
    return "tool-" + _sha256_text(state_id + "␟" + call_id)[:12]


def render_state(cluster: Mapping[str, Any], state: Mapping[str, Any]) -> dict[str, Any]:
    """Return the exact ``_VerificationState`` the matched verifier receives."""
    from evals.benchmarks.decision_handoff_runtime import INBOX_SYSTEM, inbox_request

    if state["kind"] == "text":
        text = state["text_state"]
        return {
            "task_contract": text["task_contract"],
            "original_request": text["original_request"],
            "candidate_output": text["candidate_output"],
            "tool_observations": [
                {
                    "tool_call_id": _tool_call_id(state["state_id"], f"t{index + 1}"),
                    "tool": row["tool"],
                    "input": row["input"],
                    "result": row["result"],
                }
                for index, row in enumerate(text["tool_observations"])
            ],
        }
    orders = cluster["orders"]
    answer_text = json.dumps(state["answer"], ensure_ascii=False)
    return {
        "task_contract": INBOX_SYSTEM,
        "original_request": inbox_request(cluster["case"]["items"]),
        "candidate_output": state["candidate_text"] or answer_text,
        "tool_observations": [
            {
                "tool_call_id": _tool_call_id(state["state_id"], call["call_id"]),
                "tool": LOOKUP_TOOL,
                "input": {"items": [dict(entry) for entry in call["items"]]},
                "result": {
                    "result": {
                        "items": [
                            {**entry, "status": orders[entry["order_id"]]}
                            for entry in call["items"]
                        ]
                    }
                },
            }
            for call in state["lookups"]
        ],
    }


def pool_position_key(pool_id: str, candidate_id: str) -> str:
    """Forward candidate order: salted hash, independent of names and the tie rule."""
    return _sha256_text(pool_id + "\u241fposition\u241f" + candidate_id)


def score_candidate_text(cluster: Mapping[str, Any], state: Mapping[str, Any]) -> str:
    """Candidate body for a controlled Score pool: answer plus its cited evidence."""
    orders = cluster["orders"]
    evidence = [
        {**entry, "status": orders[entry["order_id"]]}
        for call in state["lookups"]
        for entry in call["items"]
    ]
    return (
        "Answer: "
        + json.dumps(state["answer"], ensure_ascii=False, separators=(",", ":"))
        + "\nEvidence (lookup_order_status observations): "
        + json.dumps(evidence, ensure_ascii=False, separators=(",", ":"))
    )


@dataclass
class ClusterBuild:
    path: Path
    cluster: dict[str, Any]
    sha256: str
    problems: list[str] = field(default_factory=list)
    states: list[dict[str, Any]] = field(default_factory=list)
    gold: list[dict[str, Any]] = field(default_factory=list)
    pools: list[dict[str, Any]] = field(default_factory=list)


def _schema_problems(cluster: Any, schema: Mapping[str, Any]) -> list[str]:
    from jsonschema import Draft202012Validator

    validator = Draft202012Validator(schema)
    return [
        "schema " + "/".join(str(part) for part in error.absolute_path) + ": " + error.message
        for error in sorted(validator.iter_errors(cluster), key=lambda item: list(item.path))
    ]


def _case_problems(cluster: Mapping[str, Any]) -> list[str]:
    from evals.benchmarks.decision_handoff_runtime import inbox_request, validate_inbox_case

    problems: list[str] = []
    items = cluster["case"]["items"]
    case = {
        "id": cluster["case"]["id"],
        "profile": "inbox",
        "items": items,
        "request": inbox_request(items),
    }
    try:
        validate_inbox_case(case, cluster["orders"])
    except ValueError as exc:
        problems.append(f"case: {exc}")
    split = cluster["split"]
    low, high = SPLIT_ITEM_RANGES[split]
    if not low <= len(items) <= high:
        problems.append(f"case: {split} clusters need {low}-{high} items, found {len(items)}")
    if cluster["author_role"] != SPLIT_ROLES[split]:
        problems.append(f"author_role must be {SPLIT_ROLES[split]!r} for the {split} split")
    if not any(
        item["expected_order"] is None or item["expected_intent"] != "status_only" for item in items
    ):
        problems.append("case: each cluster needs at least one no-match or unsupported item")
    return problems


def _state_problems(
    cluster: Mapping[str, Any], state: Mapping[str, Any]
) -> tuple[list[str], RuleGold | None]:
    problems: list[str] = []
    prefix = cluster["cluster_id"] + "--"
    label = state["state_id"]
    if not label.startswith(prefix):
        problems.append(f"{label}: state_id must start with {prefix!r}")
    quad = state["quad_id"]
    if quad is not None and not quad.startswith(prefix):
        problems.append(f"{label}: quad_id must start with {prefix!r}")
    declared = state["declared_cell"]
    declared_pair = (declared["has_contradiction"], declared["missing_evidence"])
    if state["declared_verdict"] != verdict_for(*declared_pair):
        problems.append(f"{label}: declared_verdict does not follow the declared cell")
    if state["kind"] == "text":
        return problems, None
    item_ids = {item["id"] for item in cluster["case"]["items"]}
    unknown_focus = set(state["focus_items"]) - item_ids
    if unknown_focus:
        problems.append(f"{label}: unknown focus items {sorted(unknown_focus)}")
    for call in state["lookups"]:
        entries = call["items"]
        if len({entry["id"] for entry in entries}) != len(entries):
            problems.append(f"{label}: lookup {call['call_id']} repeats an item id")
        for entry in entries:
            if entry["id"] not in item_ids or entry["order_id"] not in cluster["orders"]:
                problems.append(f"{label}: lookup {call['call_id']} references unknown ids")
    if len({call["call_id"] for call in state["lookups"]}) != len(state["lookups"]):
        problems.append(f"{label}: lookup call ids repeat")
    if problems:
        return problems, None
    try:
        gold = rule_gold(cluster, state)
    except ValueError as exc:
        return [*problems, f"{label}: {exc}"], None
    unclassified = sorted(key for key, kind in gold.item_kinds.items() if kind not in ITEM_KINDS)
    if unclassified:
        problems.append(f"{label}: answer shape outside the taxonomy for {unclassified}")
    elif (gold.has_contradiction, gold.missing_evidence) != declared_pair:
        problems.append(
            f"{label}: declared cell {declared_pair} disagrees with the rule oracle "
            f"({gold.has_contradiction}, {gold.missing_evidence}) {gold.item_kinds}"
        )
    if state["stratum"] == "style_adversarial":
        text = state["candidate_text"]
        if json.dumps(state["answer"], ensure_ascii=False) not in text:
            problems.append(f"{label}: candidate_text must contain the answer JSON verbatim")
    return problems, gold


def _quad_problems(cluster: Mapping[str, Any], golds: Mapping[str, RuleGold]) -> list[str]:
    problems: list[str] = []
    quads: dict[str, list[dict[str, Any]]] = {}
    for state in cluster["states"]:
        if state["stratum"] == "envelope":
            quads.setdefault(state["quad_id"], []).append(state)
    if len(quads) != QUADS_PER_CLUSTER:
        problems.append(f"cluster needs {QUADS_PER_CLUSTER} envelope quads, found {len(quads)}")
    f1_kinds: list[str] = []
    orders = cluster["orders"]
    targets = {item["id"]: item["expected_order"] for item in cluster["case"]["items"]}
    intents = {item["id"]: item["expected_intent"] for item in cluster["case"]["items"]}
    for quad_id, members in sorted(quads.items()):
        if len(members) != 4 or any(state["state_id"] not in golds for state in members):
            problems.append(f"{quad_id}: a quad needs four valid inbox states")
            continue
        cells = {
            (golds[s["state_id"]].has_contradiction, golds[s["state_id"]].missing_evidence): s
            for s in members
        }
        if set(cells) != set(POOL_GRADES):
            problems.append(f"{quad_id}: the four rule cells must each occur once")
            continue
        focus = [list(state["focus_items"]) for state in members]
        if any(value != focus[0] for value in focus) or len(focus[0]) != 2:
            problems.append(f"{quad_id}: members need the same two focus items [f1, f2]")
            continue
        f1, f2 = focus[0]
        if intents[f2] != "status_only" or targets[f2] is None:
            problems.append(f"{quad_id}: f2 must be a targeted status-only item")
            continue
        kinds = {cell: golds[state["state_id"]].item_kinds for cell, state in cells.items()}
        expected_f2 = {
            (False, False): "correct",
            (True, False): "correct",
            (False, True): "unobserved_status",
            (True, True): "unobserved_status",
        }
        if any(kinds[cell][f2] != expected_f2[cell] for cell in cells):
            problems.append(f"{quad_id}: f2 must be correct, then unobserved in the m cells")
        c_kind = kinds[(True, False)][f1]
        if (
            c_kind not in C_KINDS
            or kinds[(True, True)][f1] != c_kind
            or kinds[(False, False)][f1] != "correct"
            or kinds[(False, True)][f1] != "correct"
        ):
            problems.append(f"{quad_id}: f1 must carry one C defect in exactly the c cells")
        f1_kinds.append(c_kind)
        answers = {cell: state["answer"]["items"] for cell, state in cells.items()}
        order = [item["id"] for item in cluster["case"]["items"]]
        for index, item_id in enumerate(order):
            variants = {_canonical(answers[cell][index]) for cell in answers}
            if item_id not in (f1, f2) and len(variants) > 1:
                problems.append(f"{quad_id}: non-focus item {item_id} differs across the quad")
        first, second = order.index(f1), order.index(f2)
        if (
            answers[(True, False)][first] != answers[(True, True)][first]
            or answers[(False, False)][first] != answers[(False, True)][first]
        ):
            problems.append(f"{quad_id}: the c cells must share one f1 answer and so must the rest")
        if len({_canonical(answers[cell][second]) for cell in answers}) > 1:
            problems.append(f"{quad_id}: the f2 answer must stay identical across the quad")
        observed = {
            cell: set(observed_statuses(orders, state["lookups"])) for cell, state in cells.items()
        }
        target = targets[f2]
        if any((target in observed[cell]) == cell[1] for cell in cells):
            problems.append(f"{quad_id}: only the m cells may omit the f2 target observation")
        stripped = {frozenset(values - {target}) for values in observed.values()}
        if len(stripped) != 1:
            problems.append(f"{quad_id}: observations may differ only by the f2 target")
    if len(f1_kinds) == QUADS_PER_CLUSTER and len(set(f1_kinds)) != QUADS_PER_CLUSTER:
        problems.append("the two quads must use different f1 C defect kinds")
    return problems


def _leak_problems(
    cluster: Mapping[str, Any], state: Mapping[str, Any], rendered: str
) -> list[str]:
    problems = []
    for key in ("state_id", "quad_id"):
        value = state.get(key)
        if isinstance(value, str) and value in rendered:
            problems.append(f"{state['state_id']}: rendered input leaks {key}")
    if cluster["cluster_id"] in rendered:
        problems.append(f"{state['state_id']}: rendered input leaks cluster_id")
    for marker in ("expected_intent", "expected_order", "expected_answer", "declared_cell"):
        if marker in rendered:
            problems.append(f"{state['state_id']}: rendered input leaks {marker}")
    return problems


def build_cluster(path: Path, schema: Mapping[str, Any]) -> ClusterBuild:
    """Validate one cluster file and derive its states, gold and Score pools."""
    from evals.benchmarks.decision_verification import _VerificationState

    raw = path.read_bytes()
    try:
        cluster = json.loads(raw)
    except ValueError as exc:
        return ClusterBuild(path, {}, hashlib.sha256(raw).hexdigest(), [f"invalid JSON: {exc}"])
    build = ClusterBuild(path, cluster, hashlib.sha256(raw).hexdigest())
    build.problems.extend(_schema_problems(cluster, schema))
    if build.problems:
        return build
    build.problems.extend(_case_problems(cluster))
    golds: dict[str, RuleGold] = {}
    identifiers = [state["state_id"] for state in cluster["states"]]
    if len(set(identifiers)) != len(identifiers):
        build.problems.append("state_id values repeat inside the cluster")
    for state in cluster["states"]:
        problems, gold = _state_problems(cluster, state)
        build.problems.extend(problems)
        if gold is not None and not problems:
            golds[state["state_id"]] = gold
    build.problems.extend(_quad_problems(cluster, golds))
    if build.problems:
        return build
    for state in cluster["states"]:
        rendered = render_state(cluster, state)
        _VerificationState.model_validate(rendered)
        encoded = _canonical(rendered)
        build.problems.extend(_leak_problems(cluster, state, encoded))
        declared = state["declared_cell"]
        gold = golds.get(state["state_id"])
        contradiction = gold.has_contradiction if gold else declared["has_contradiction"]
        missing = gold.missing_evidence if gold else declared["missing_evidence"]
        build.states.append(
            {
                "state_id": state["state_id"],
                "cluster_id": cluster["cluster_id"],
                "split": cluster["split"],
                "stratum": state["stratum"],
                "quad_id": state["quad_id"],
                "headline": state["stratum"] in HEADLINE_STRATA,
                "language": cluster["language"],
                "state": rendered,
                "state_sha256": _digest(rendered),
            }
        )
        build.gold.append(
            {
                "state_id": state["state_id"],
                "gold_source": "rule" if gold else "author",
                "has_contradiction": contradiction,
                "missing_evidence": missing,
                "verdict": verdict_for(contradiction, missing),
                "item_kinds": gold.item_kinds if gold else None,
            }
        )
    by_quad: dict[str, list[dict[str, Any]]] = {}
    for state in cluster["states"]:
        if state["stratum"] == "envelope":
            by_quad.setdefault(state["quad_id"], []).append(state)
    for quad_id, members in sorted(by_quad.items()):
        candidates = []
        for state in sorted(members, key=lambda item: pool_position_key(quad_id, item["state_id"])):
            gold = golds[state["state_id"]]
            text = score_candidate_text(cluster, state)
            if len(text) > SCORE_TEXT_LIMIT:
                build.problems.append(f"{state['state_id']}: Score candidate text exceeds limit")
            candidates.append(
                {
                    "candidate_id": state["state_id"],
                    "text": text,
                    "grade": POOL_GRADES[(gold.has_contradiction, gold.missing_evidence)],
                }
            )
        pool = {
            "pool_id": quad_id,
            "cluster_id": cluster["cluster_id"],
            "split": cluster["split"],
            "candidates": candidates,
        }
        pool["pool_sha256"] = _digest({"pool_id": quad_id, "candidates": candidates})
        build.pools.append(pool)
    return build


def cluster_paths(root: Path) -> list[tuple[str | None, Path]]:
    """Discover cluster files under ``<root>/<split>/`` or directly under ``root``."""
    found: list[tuple[str | None, Path]] = []
    for split in ("selection", "test"):
        found.extend((split, path) for path in sorted((root / split).glob("*.json")))
    if not found:
        found.extend((None, path) for path in sorted(root.glob("*.json")))
    return found


def _normalized_requests(cluster: Mapping[str, Any]) -> set[str]:
    return {
        re.sub(r"\s+", " ", item["request"]).strip().lower() for item in cluster["case"]["items"]
    }


def _split_problems(
    builds: Sequence[ClusterBuild], directories: Sequence[str | None], *, final: bool
) -> tuple[list[str], dict[str, Any]]:
    problems: list[str] = []
    by_split: dict[str, list[ClusterBuild]] = {}
    for build, directory in zip(builds, directories, strict=True):
        split = build.cluster.get("split")
        if directory is not None and split != directory:
            problems.append(f"{build.path.name}: file under {directory}/ declares split {split}")
        if isinstance(split, str):
            by_split.setdefault(split, []).append(build)
    clusters = [str(build.cluster.get("cluster_id")) for build in builds]
    repeated = sorted(key for key, count in Counter(clusters).items() if count > 1)
    if repeated:
        problems.append(f"cluster_id values repeat: {repeated}")
    states = [state["state_id"] for build in builds for state in build.states]
    if len(set(states)) != len(states):
        problems.append("state_id values repeat across clusters")
    summary: dict[str, Any] = {}
    for split, members in sorted(by_split.items()):
        korean = sum(build.cluster.get("language") in {"ko", "mixed"} for build in members)
        if final and members and korean / len(members) < MIN_KOREAN_SHARE:
            problems.append(f"{split}: fewer than 30% Korean clusters ({korean}/{len(members)})")
        rows = [state for build in members for state in build.states]
        gold = [row for build in members for row in build.gold]
        cells = Counter(
            (row["has_contradiction"], row["missing_evidence"])
            for row, state in zip(gold, rows, strict=True)
            if state["headline"]
        )
        summary[split] = {
            "clusters": len(members),
            "states": len(rows),
            "headline_states": sum(state["headline"] for state in rows),
            "out_of_envelope_states": sum(not state["headline"] for state in rows),
            "korean_clusters": korean,
            "headline_cells": {
                f"c{int(cell[0])}m{int(cell[1])}": count for cell, count in sorted(cells.items())
            },
        }
    if {"selection", "test"} <= by_split.keys():
        overlap = set().union(
            *(_normalized_requests(build.cluster) for build in by_split["selection"])
        ) & set().union(*(_normalized_requests(build.cluster) for build in by_split["test"]))
        if overlap:
            problems.append(f"{len(overlap)} normalized requests appear in both splits")
        total = len(by_split["selection"]) + len(by_split["test"])
        share = len(by_split["selection"]) / total
        low, high = SELECTION_CLUSTER_SHARE
        if final and not low <= share <= high:
            problems.append(f"selection holds {share:.0%} of clusters; expected 35-45%")
        if final and total < MIN_CLUSTERS:
            problems.append(f"final panel needs at least {MIN_CLUSTERS} clusters, found {total}")
    elif final:
        problems.append("final checks need both selection/ and test/ directories")
    return problems, summary


@dataclass
class PanelBuild:
    builds: list[ClusterBuild]
    problems: list[str]
    summary: dict[str, Any]


def build_panel(root: Path, *, final: bool = False) -> PanelBuild:
    """Validate every cluster under ``root`` and gather split-level checks."""
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    located = cluster_paths(root)
    if not located:
        return PanelBuild([], [f"{root}: no cluster JSON files"], {})
    builds = [build_cluster(path, schema) for _, path in located]
    problems = [
        f"{build.cluster.get('cluster_id') or build.path.name}: {problem}"
        for build in builds
        for problem in build.problems
    ]
    split_problems, summary = _split_problems(
        builds, [directory for directory, _ in located], final=final
    )
    return PanelBuild(builds, problems + split_problems, summary)


ORACLE_PATH = Path(__file__).with_name("verdict_panel_oracle.py")


def oracle_sha256() -> str:
    """Digest of the frozen rule-oracle module, recorded in every panel manifest."""
    return hashlib.sha256(ORACLE_PATH.read_bytes()).hexdigest()


SEALED_SPLITS = frozenset({"test"})


def public_pools(
    pools: Iterable[Mapping[str, Any]], aliases: Mapping[str, str]
) -> list[dict[str, Any]]:
    """Drop grades from Score pools and alias their IDs; the digest covers public fields.

    A graded digest beside public texts would leak grades: four candidates have only
    twelve grade assignments, so the graded hash is brute-forceable.
    """
    public = []
    for pool in pools:
        pool_id = aliases[pool["pool_id"]]
        candidates = [
            {"candidate_id": aliases[row["candidate_id"]], "text": row["text"]}
            for row in pool["candidates"]
        ]
        public.append(
            {
                "pool_id": pool_id,
                "cluster_id": pool["cluster_id"],
                "split": pool["split"],
                "candidates": candidates,
                "pool_sha256": _digest({"pool_id": pool_id, "candidates": candidates}),
            }
        )
    return public


def sealed_aliases(
    states: Iterable[Mapping[str, Any]], rng: random.Random | None = None
) -> dict[str, str]:
    """Map every state and quad ID to a random opaque alias kept only in the sealed map.

    Author-chosen IDs may describe a cell; public files for a sealed split carry
    aliases instead, and the sealed map restores the IDs at unseal.
    """
    source = rng if rng is not None else secrets.SystemRandom()
    aliases: dict[str, str] = {}
    used: set[str] = set()
    for row in states:
        for key, prefix in (("state_id", "s-"), ("quad_id", "q-")):
            original = row[key]
            if original is None or original in aliases:
                continue
            alias = prefix + f"{source.getrandbits(64):016x}"
            while alias in used:
                alias = prefix + f"{source.getrandbits(64):016x}"
            used.add(alias)
            aliases[original] = alias
    return aliases


def _write_text(path: Path, text: str) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as handle:
        handle.write(text)
    return _sha256_text(text)


def write_outputs(
    panel: PanelBuild,
    output: Path,
    *,
    sealed: Path | None = None,
    alias_rng: random.Random | None = None,
) -> dict[str, Any]:
    """Write per-split derived files and the split manifest (never overwrite).

    For a sealed split, gold, graded Score pools and the alias map go only to
    ``sealed``; the public output keeps judge inputs and ungraded pools under opaque
    aliases, so no file handed to the run owner determines or names a test label.
    """
    output.mkdir(parents=True, exist_ok=False)
    sealed = sealed if sealed is not None else output / "sealed"
    manifest: dict[str, Any] = {
        "schema_id": MANIFEST_SCHEMA_ID,
        "schema_version": 1,
        "builder_version": BUILDER_VERSION,
        "oracle_sha256": oracle_sha256(),
        "cluster_schema_sha256": hashlib.sha256(SCHEMA_PATH.read_bytes()).hexdigest(),
        "splits": {},
    }
    for split in sorted({build.cluster["split"] for build in panel.builds}):
        members = sorted(
            (build for build in panel.builds if build.cluster["split"] == split),
            key=lambda item: item.cluster["cluster_id"],
        )
        states = sorted((row for b in members for row in b.states), key=lambda r: r["state_id"])
        gold = sorted((row for b in members for row in b.gold), key=lambda r: r["state_id"])
        pools = sorted((row for b in members for row in b.pools), key=lambda r: r["pool_id"])
        withheld = split in SEALED_SPLITS
        entry: dict[str, Any] = {
            "sealed_gold": withheld,
            "id_scheme": "sealed-alias" if withheld else "author",
            "cluster_files": [
                {
                    "cluster_id": build.cluster["cluster_id"],
                    "file": build.path.name,
                    "sha256": build.sha256,
                    "states": len(build.states),
                }
                for build in members
            ],
        }
        if withheld:
            aliases = sealed_aliases(states, alias_rng)
            public_states = sorted(
                (
                    {
                        **row,
                        "state_id": aliases[row["state_id"]],
                        "quad_id": aliases.get(row["quad_id"]) if row["quad_id"] else None,
                    }
                    for row in states
                ),
                key=lambda r: r["state_id"],
            )
            entry["states_sha256"] = _write_text(
                output / f"states.{split}.jsonl", _jsonl(public_states)
            )
            entry["gold_sha256"] = _write_text(sealed / f"gold.{split}.jsonl", _jsonl(gold))
            entry["pools_graded_sha256"] = _write_text(
                sealed / f"pools-graded.{split}.jsonl", _jsonl(pools)
            )
            entry["aliases_sha256"] = _write_text(
                sealed / f"aliases.{split}.json",
                json.dumps(
                    {alias: original for original, alias in sorted(aliases.items())},
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                )
                + "\n",
            )
            entry["pools_sha256"] = _write_text(
                output / f"pools.{split}.jsonl",
                _jsonl(sorted(public_pools(pools, aliases), key=lambda r: r["pool_id"])),
            )
            entry["sealed_files"] = [
                f"aliases.{split}.json",
                f"gold.{split}.jsonl",
                f"pools-graded.{split}.jsonl",
            ]
        else:
            entry["states_sha256"] = _write_text(output / f"states.{split}.jsonl", _jsonl(states))
            entry["gold_sha256"] = _write_text(output / f"gold.{split}.jsonl", _jsonl(gold))
            entry["pools_sha256"] = _write_text(output / f"pools.{split}.jsonl", _jsonl(pools))
        entry.update(panel.summary.get(split, {}))
        manifest["splits"][split] = entry
    _write_text(
        output / "split-manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2) + "\n"
    )
    return manifest


def manifest_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def ordered_workload_ids(workload_ids: Iterable[str], split_manifest_sha256: str) -> list[str]:
    """Freeze dispatch order as ascending ``sha256(id ∥ manifest sha256)`` (05 §8.1)."""
    if not re.fullmatch(r"[0-9a-f]{64}", split_manifest_sha256):
        raise ValueError("split manifest digest must be a SHA-256 hex string")
    ids = list(workload_ids)
    if len(set(ids)) != len(ids):
        raise ValueError("workload IDs must be unique")
    return sorted(ids, key=lambda value: _sha256_text(value + split_manifest_sha256))


def stratified_prefix(
    ordered_ids: Sequence[str], cell_of: Mapping[str, str], per_cell: int
) -> list[str]:
    """Take the earliest ``per_cell`` IDs of every cell from a frozen order."""
    taken: Counter[str] = Counter()
    selected = []
    cells = set(cell_of.values())
    for identifier in ordered_ids:
        cell = cell_of.get(identifier)
        if cell is not None and taken[cell] < per_cell:
            taken[cell] += 1
            selected.append(identifier)
    if any(taken[cell] < per_cell for cell in cells):
        raise ValueError("not enough states to fill every cell")
    return selected


def unseal(
    panel: PanelBuild, manifest: Mapping[str, Any], *, sealed: Path | None = None
) -> dict[str, Any]:
    """Recompute gold (and graded pools) from cluster files; compare with the manifest.

    Agreement requires the same cluster files and an identical gold digest. The
    oracle digest is reported separately: identical gold under an edited oracle is
    shown, not hidden.
    """
    report: dict[str, Any] = {}
    oracle_match = manifest.get("oracle_sha256") == oracle_sha256()
    for split, entry in manifest["splits"].items():
        members = sorted(
            (build for build in panel.builds if build.cluster.get("split") == split),
            key=lambda item: item.cluster["cluster_id"],
        )
        files = {build.path.name: build.sha256 for build in members}
        expected_files = {row["file"]: row["sha256"] for row in entry["cluster_files"]}
        gold = sorted((row for b in members for row in b.gold), key=lambda r: r["state_id"])
        pools = sorted((row for b in members for row in b.pools), key=lambda r: r["pool_id"])
        gold_match = _sha256_text(_jsonl(gold)) == entry["gold_sha256"]
        row: dict[str, Any] = {
            "cluster_files_match": files == expected_files,
            "states": len(gold),
            "gold_sha256_match": gold_match,
            "oracle_sha256_match": oracle_match,
            "agreement": 1.0 if gold_match and files == expected_files else None,
        }
        if "pools_graded_sha256" in entry:
            row["pools_graded_sha256_match"] = (
                _sha256_text(_jsonl(pools)) == entry["pools_graded_sha256"]
            )
        if "aliases_sha256" in entry and sealed is not None:
            path = sealed / f"aliases.{split}.json"
            mapping = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
            known = {state["state_id"] for state in gold} | {
                state["quad_id"] for b in members for state in b.states if state["quad_id"]
            }
            row["aliases_match"] = (
                path.is_file()
                and hashlib.sha256(path.read_bytes()).hexdigest() == entry["aliases_sha256"]
                and set(mapping.values()) == known
            )
        report[split] = row
    return report


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    check = commands.add_parser("check", help="validate clusters; exit 1 on any problem")
    check.add_argument("root", type=Path)
    check.add_argument("--final", action="store_true", help="also enforce full-panel counts")
    build = commands.add_parser("build", help="validate, then write derived panel files")
    build.add_argument("root", type=Path)
    build.add_argument("output", type=Path)
    build.add_argument("--sealed-dir", type=Path)
    build.add_argument("--final", action="store_true")
    opened = commands.add_parser("unseal", help="recompute gold against a split manifest")
    opened.add_argument("root", type=Path)
    opened.add_argument("manifest", type=Path)
    opened.add_argument("--sealed-dir", type=Path)
    args = parser.parse_args(argv)
    panel = build_panel(args.root, final=getattr(args, "final", False))
    if panel.problems:
        for problem in panel.problems:
            print(problem, file=sys.stderr)
        print(f"rejected: {len(panel.problems)} problem(s)", file=sys.stderr)
        return 1
    if args.command == "check":
        print(json.dumps(panel.summary, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    if args.command == "build":
        manifest = write_outputs(panel, args.output, sealed=args.sealed_dir)
        digest = manifest_sha256(args.output / "split-manifest.json")
        print(json.dumps({"split_manifest_sha256": digest, **manifest["splits"]}, indent=2))
        return 0
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    report = unseal(panel, manifest, sealed=args.sealed_dir)
    print(json.dumps(report, indent=2, sort_keys=True))
    return (
        0
        if all(
            row["agreement"] == 1.0
            and row.get("pools_graded_sha256_match", True)
            and row.get("aliases_match", True)
            for row in report.values()
        )
        else 1
    )


if __name__ == "__main__":
    raise SystemExit(main())
