"""S-5 structure guards (2026-06-11) — autoresearch-원형 restore + loop domains.

Pins: train.py stays the slim mutation-surface module (no regrowth of the
measurement gear), the four gear modules exist with their key surfaces,
the loop/ domain split holds, and program.md's contract names the gear
as agent-읽기전용.
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
SI = REPO_ROOT / "core" / "self_improving"


def test_train_py_stays_slim() -> None:
    """원형 복원 래칫 — train.py가 다시 측정 장비를 흡수하면 실패."""
    line_count = len((SI / "train.py").read_text(encoding="utf-8").splitlines())
    assert line_count < 2200, (
        f"train.py grew to {line_count} lines — measurement gear belongs in "
        "measure/fitness/gate/ledger (S-5 contract, program.md)"
    )


def test_gear_modules_exist_with_key_surfaces() -> None:
    from core.self_improving import fitness, gate, ledger, measure

    assert hasattr(fitness, "compute_fitness") and hasattr(fitness, "DIM_WEIGHTS")
    assert hasattr(measure, "run_audit") and hasattr(measure, "_build_audit_env")
    assert hasattr(gate, "_should_promote") and hasattr(gate, "MARGIN_LOGIC_VERSION")
    assert hasattr(ledger, "_write_baseline") and hasattr(ledger, "_append_baseline_registry_row")


def test_train_keeps_mutation_surface() -> None:
    from core.self_improving import train

    assert hasattr(train, "WRAPPER_PROMPT_SECTIONS")
    assert hasattr(train, "load_wrapper_prompt_sections")
    assert hasattr(train, "BUDGET_MINUTES") and hasattr(train, "SEED_LIMIT")
    assert hasattr(train, "main")


def test_loop_domain_split_holds() -> None:
    for rel in (
        "loop/mutate/runner.py",
        "loop/mutate/policies.py",
        "loop/observe/attribution.py",
        "loop/observe/baseline_epoch.py",
        "loop/inject/in_context_wiring.py",
        "loop/inject/memory_recall.py",
    ):
        assert (SI / rel).is_file(), rel
    # 구 평면 위치 재생 금지
    for stale in ("loop/runner.py", "loop/attribution.py", "loop/memory_recall.py"):
        assert not (SI / stale).exists(), f"flat loop module regrew: {stale}"


def test_program_md_names_gear_as_read_only() -> None:
    text = (SI / "program.md").read_text(encoding="utf-8")
    assert "measure.py" in text and "ledger.py" in text
    assert "MUST NOT modify" in text
