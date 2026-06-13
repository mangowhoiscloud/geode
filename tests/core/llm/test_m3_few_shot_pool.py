"""ADR-012 M3 — Few-shot exemplar pool invariants.

Pins JSONL append-only schema + top-K rank + apply 가 messages 앞에
exemplar pair 삽입 + 3-layer BACKFILL-SOT chain.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from core.llm import few_shot_pool as fsp
from core.llm.few_shot_pool import (
    FewShotExemplar,
    _load_few_shot_pool_override,
    apply_few_shot_pool,
)


@pytest.fixture
def isolated_sot(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    sot = tmp_path / "few-shot-pool.jsonl"
    operator_local = tmp_path / "operator-local-few-shot-pool.jsonl"
    monkeypatch.setattr(fsp, "_FEW_SHOT_POOL_SOT_PATH", sot)
    monkeypatch.setattr(fsp, "_OPERATOR_LOCAL_FEW_SHOT_POOL_PATH", operator_local)
    monkeypatch.delenv("GEODE_FEW_SHOT_POOL_OVERRIDE", raising=False)
    monkeypatch.delenv("GEODE_FEW_SHOT_POOL_STRICT", raising=False)
    yield sot


def _write_jsonl(sot: Path, entries: list[dict[str, Any]]) -> None:
    sot.write_text("\n".join(json.dumps(e) for e in entries) + "\n", encoding="utf-8")


# Reader ----------------------------------------------------------------------


def test_load_returns_none_when_sot_missing(isolated_sot: Path) -> None:
    assert _load_few_shot_pool_override() is None


def test_load_empty_file_returns_empty_list(isolated_sot: Path) -> None:
    isolated_sot.write_text("", encoding="utf-8")
    result = _load_few_shot_pool_override()
    assert result == []


def test_load_skips_blank_lines(isolated_sot: Path) -> None:
    isolated_sot.write_text('\n\n{"user_msg": "q", "assistant_msg": "a"}\n\n', encoding="utf-8")
    result = _load_few_shot_pool_override()
    assert result is not None
    assert len(result) == 1


def test_load_valid_payload(isolated_sot: Path) -> None:
    _write_jsonl(
        isolated_sot,
        [
            {
                "user_msg": "user 1",
                "assistant_msg": "assist 1",
                "fitness_delta": 0.5,
                "source": "cycle-1",
            },
            {"user_msg": "user 2", "assistant_msg": "assist 2"},
        ],
    )
    result = _load_few_shot_pool_override()
    assert result is not None
    assert len(result) == 2
    assert result[0].user_msg == "user 1"
    assert result[0].fitness_delta == 0.5
    assert result[0].source == "cycle-1"
    assert result[1].fitness_delta == 0.0  # default
    assert result[1].source == ""


def test_load_per_line_graceful_one_bad_line_kept_rest(isolated_sot: Path) -> None:
    """JSONL per-line — broken line skipped, valid lines retained."""
    isolated_sot.write_text(
        "\n".join(
            [
                json.dumps({"user_msg": "ok1", "assistant_msg": "a1"}),
                "not valid json {",
                json.dumps({"user_msg": "ok2", "assistant_msg": "a2"}),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    result = _load_few_shot_pool_override()
    assert result is not None
    assert [e.user_msg for e in result] == ["ok1", "ok2"]


def test_load_skips_missing_user_msg(isolated_sot: Path) -> None:
    _write_jsonl(isolated_sot, [{"assistant_msg": "no user"}])
    result = _load_few_shot_pool_override()
    assert result == []


def test_load_skips_empty_assistant_msg(isolated_sot: Path) -> None:
    _write_jsonl(isolated_sot, [{"user_msg": "q", "assistant_msg": ""}])
    result = _load_few_shot_pool_override()
    assert result == []


def test_load_skips_non_dict_entry(isolated_sot: Path) -> None:
    """Top-level scalar / list in JSONL line → skipped."""
    isolated_sot.write_text(
        "\n".join(["42", '["a","b"]', json.dumps({"user_msg": "q", "assistant_msg": "a"})]) + "\n",
        encoding="utf-8",
    )
    result = _load_few_shot_pool_override()
    assert result is not None
    assert len(result) == 1


def test_load_coerces_non_numeric_fitness_delta_to_zero(isolated_sot: Path) -> None:
    _write_jsonl(
        isolated_sot,
        [
            {
                "user_msg": "q",
                "assistant_msg": "a",
                "fitness_delta": "not a number",
            }
        ],
    )
    result = _load_few_shot_pool_override()
    assert result is not None
    assert result[0].fitness_delta == 0.0


def test_load_rejects_bool_fitness_delta(isolated_sot: Path) -> None:
    """bool subclass int trap — should coerce to 0.0, not True/False."""
    _write_jsonl(
        isolated_sot,
        [
            {"user_msg": "q", "assistant_msg": "a", "fitness_delta": True},
        ],
    )
    result = _load_few_shot_pool_override()
    assert result is not None
    assert result[0].fitness_delta == 0.0


def test_strict_env_var_raises_on_bad_jsonl(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bad = tmp_path / "bad.jsonl"
    bad.write_text("garbage {{\n", encoding="utf-8")
    monkeypatch.setenv("GEODE_FEW_SHOT_POOL_OVERRIDE", str(bad))
    monkeypatch.setenv("GEODE_FEW_SHOT_POOL_STRICT", "1")
    with pytest.raises(RuntimeError, match="JSON decode failed"):
        _load_few_shot_pool_override()


def test_env_var_without_strict_is_graceful(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GEODE_FEW_SHOT_POOL_OVERRIDE", str(tmp_path / "nope.jsonl"))
    monkeypatch.delenv("GEODE_FEW_SHOT_POOL_STRICT", raising=False)
    assert _load_few_shot_pool_override() is None


def test_operator_local_layer_priority(isolated_sot: Path) -> None:
    operator_local = isolated_sot.parent / "operator-local-few-shot-pool.jsonl"
    operator_local.write_text(
        json.dumps({"user_msg": "from-ops", "assistant_msg": "a"}) + "\n",
        encoding="utf-8",
    )
    _write_jsonl(isolated_sot, [{"user_msg": "from-repo", "assistant_msg": "a"}])
    result = _load_few_shot_pool_override()
    assert result is not None
    assert result[0].user_msg == "from-ops"


# Apply -----------------------------------------------------------------------


def _msgs(*roles_and_contents: tuple[str, str]) -> list[dict[str, Any]]:
    return [{"role": r, "content": c} for r, c in roles_and_contents]


def test_apply_none_returns_original_unchanged() -> None:
    msgs = _msgs(("user", "hello"))
    assert apply_few_shot_pool(msgs, None) is msgs


def test_apply_empty_pool_returns_original() -> None:
    msgs = _msgs(("user", "hello"))
    assert apply_few_shot_pool(msgs, []) is msgs


def test_apply_zero_max_entries_returns_original() -> None:
    msgs = _msgs(("user", "hello"))
    pool = [FewShotExemplar(user_msg="q", assistant_msg="a")]
    assert apply_few_shot_pool(msgs, pool, max_entries=0) is msgs


def test_apply_inserts_exemplar_pair_at_head() -> None:
    msgs = _msgs(("user", "real question"))
    pool = [FewShotExemplar(user_msg="ex_q", assistant_msg="ex_a")]
    out = apply_few_shot_pool(msgs, pool, max_entries=1)
    assert out == [
        {"role": "user", "content": "ex_q"},
        {"role": "assistant", "content": "ex_a"},
        {"role": "user", "content": "real question"},
    ]


def test_apply_ranks_by_fitness_delta_desc() -> None:
    pool = [
        FewShotExemplar(user_msg="q_low", assistant_msg="a_low", fitness_delta=0.1),
        FewShotExemplar(user_msg="q_high", assistant_msg="a_high", fitness_delta=0.9),
        FewShotExemplar(user_msg="q_mid", assistant_msg="a_mid", fitness_delta=0.5),
    ]
    out = apply_few_shot_pool([], pool, max_entries=2)
    # top-2 by fitness_delta desc: q_high, q_mid
    user_contents = [m["content"] for m in out if m["role"] == "user"]
    assert user_contents == ["q_high", "q_mid"]


def test_apply_does_not_mutate_input_lists() -> None:
    msgs = _msgs(("user", "original"))
    pool = [FewShotExemplar(user_msg="ex_q", assistant_msg="ex_a")]
    original_len = len(msgs)
    apply_few_shot_pool(msgs, pool)
    assert len(msgs) == original_len  # input list intact


def test_apply_respects_max_entries_cap() -> None:
    pool = [
        FewShotExemplar(user_msg=f"q{i}", assistant_msg=f"a{i}", fitness_delta=float(i))
        for i in range(10)
    ]
    out = apply_few_shot_pool([], pool, max_entries=3)
    # 3 pairs = 6 messages
    assert len(out) == 6


# Wiring + path constants ----------------------------------------------------


def test_path_constants_present() -> None:
    from core.paths import (
        AUTORESEARCH_FEW_SHOT_POOL_PATH,
        OPERATOR_LOCAL_FEW_SHOT_POOL_PATH,
    )

    assert AUTORESEARCH_FEW_SHOT_POOL_PATH.name == "few-shot-pool.jsonl"
    assert OPERATOR_LOCAL_FEW_SHOT_POOL_PATH.name == "few-shot-pool.jsonl"
    assert "policies" in str(AUTORESEARCH_FEW_SHOT_POOL_PATH)
    assert "autoresearch/handoff" in str(OPERATOR_LOCAL_FEW_SHOT_POOL_PATH)


def test_train_py_sets_few_shot_pool_env_pair() -> None:
    repo_root = Path(__file__).resolve().parents[3]
    src = (repo_root / "core/self_improving/measure.py").read_text(encoding="utf-8")
    assert "GEODE_FEW_SHOT_POOL_OVERRIDE" in src
    assert "GEODE_FEW_SHOT_POOL_STRICT" in src
    assert "AUTORESEARCH_FEW_SHOT_POOL_PATH" in src


def test_few_shot_pool_jsonl_referenced_in_inference_path() -> None:
    repo_root = Path(__file__).resolve().parents[3]
    hits: list[str] = []
    for path in (repo_root / "core").rglob("*.py"):
        if "test_" in path.name:
            continue
        try:
            content = path.read_text(encoding="utf-8")
        except OSError:
            continue
        if "few-shot-pool.jsonl" in content:
            hits.append(str(path.relative_to(repo_root)))
    assert any("few_shot_pool.py" in h for h in hits)
