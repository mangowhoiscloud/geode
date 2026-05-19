"""
One-time sanity check for autoresearch — GEODE self-improving loop pre-flight.

``train.py`` 가 자동 엔지니어링 루프를 돌리기 전에 ``prepare.py`` 가 한 번
실행되어 **fixed audit harness** 의 무결성을 검증한다 — Petri seed pool 의
file count / format, AlphaEval rubric 의 dim count, audit CLI 의 dry-run
reachability. 측정 대상 (rubric · seed pool · subprocess 진입점) 은 모두
petri 가 소유하는 자산이며, ``prepare.py`` 는 그 자산이 자동 엔지니어링
루프에 사용 가능한 상태인지를 확인할 뿐 직접 수정하지 않는다.

Usage:
    uv run python autoresearch/prepare.py             # full check
    uv run python autoresearch/prepare.py --skip-cli  # rubric/seed only

Artefact 위치 — sanity report 만 ``~/.cache/autoresearch-petri/`` 에
저장한다 (3-file pattern 의 그릇은 Karpathy autoresearch 에서 차용했지만
저장 위치는 GEODE 의 ``~/.cache/`` 관행을 따른다):

    ~/.cache/autoresearch-petri/prepare-report.txt
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

import yaml

# ---------------------------------------------------------------------------
# Constants (fixed, do not modify — agent 가 수정 X)
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parent.parent
SEED_POOL_DIR = REPO_ROOT / "plugins" / "petri_audit" / "seeds"
RUBRIC_FILE = REPO_ROOT / "plugins" / "petri_audit" / "judge_dims" / "geode_5axes.yaml"
MIN_SEED_COUNT = 18  # post-PR-0 minimum (18 migrated + 4 new dim bases)
EXPECTED_DIM_COUNT = (
    22  # PR 0: 19 (base + AlphaEval) + 3 new context-management JudgeDimension entries
)

CACHE_DIR = Path.home() / ".cache" / "autoresearch-petri"
REPORT_FILE = CACHE_DIR / "prepare-report.txt"
FALLBACK_REPORT_FILE = REPO_ROOT / "autoresearch" / "state" / "prepare-report.txt"


# ---------------------------------------------------------------------------
# Checks
# ---------------------------------------------------------------------------


def check_seed_pool() -> tuple[bool, str]:
    """Verify the hierarchical seed pool exists with the expected layout.

    Post-PR-0 the seed pool is a tree:
    ``seeds/<tier>/<dim>/<NN>_<variant>.md``. We walk recursively and
    enforce a minimum count rather than an exact one — gen1+ runs may
    grow the pool.
    """
    if not SEED_POOL_DIR.is_dir():
        return False, f"missing seed pool dir: {SEED_POOL_DIR}"
    # PR 0: hierarchical tree — verify the 3 tier dirs exist
    for tier in ("critical", "auxiliary", "info"):
        if not (SEED_POOL_DIR / tier).is_dir():
            return False, f"hierarchical tier missing: {SEED_POOL_DIR / tier}"
    seeds = sorted(SEED_POOL_DIR.rglob("*.md"))
    if len(seeds) < MIN_SEED_COUNT:
        return (
            False,
            f"expected at least {MIN_SEED_COUNT} seeds under {SEED_POOL_DIR}, found {len(seeds)}",
        )
    return True, f"seed pool OK — {len(seeds)} files under {SEED_POOL_DIR}"


def check_rubric() -> tuple[bool, str]:
    """Verify the AlphaEval rubric file has the expected dim count.

    Post-PR-0 the YAML is mixed: 19 string entries (default-36 subset)
    + 3 full ``JudgeDimension`` dict entries (new context-management
    dims). inspect-petri's ``judge_dimensions()`` accepts
    ``Sequence[str | JudgeDimension]``.
    """
    if not RUBRIC_FILE.is_file():
        return False, f"missing rubric file: {RUBRIC_FILE}"
    with RUBRIC_FILE.open(encoding="utf-8") as f:
        dims = yaml.safe_load(f)
    if not isinstance(dims, list):
        return False, f"rubric must be a YAML list: {RUBRIC_FILE}"
    valid = all(isinstance(d, str) or (isinstance(d, dict) and "name" in d) for d in dims)
    if not valid:
        return False, (
            f"rubric entries must be strings or dicts with a 'name' field: {RUBRIC_FILE}"
        )
    if len(dims) != EXPECTED_DIM_COUNT:
        return (
            False,
            f"expected {EXPECTED_DIM_COUNT} dims in {RUBRIC_FILE.name}, found {len(dims)}",
        )
    return True, f"rubric OK — {len(dims)} dims in {RUBRIC_FILE.name}"


def check_audit_cli(skip_cli: bool) -> tuple[bool, str]:
    """Verify the ``geode audit`` CLI is reachable (dry-run --help only)."""
    if skip_cli:
        return True, "audit CLI check skipped (--skip-cli)"
    geode_bin = shutil.which("geode") or shutil.which("uv")
    if geode_bin is None:
        return False, "neither `geode` nor `uv` on PATH"
    cmd = (
        [geode_bin, "audit", "--help"]
        if geode_bin.endswith("/geode")
        else [geode_bin, "run", "geode", "audit", "--help"]
    )
    try:
        result = subprocess.run(  # noqa: S603  # nosec B603 — argv from shutil.which + module constants
            cmd, capture_output=True, timeout=30, check=False
        )
    except subprocess.TimeoutExpired:
        return False, f"audit CLI --help timed out: {' '.join(cmd)}"
    if result.returncode != 0:
        return (
            False,
            f"audit CLI --help exit={result.returncode}: {result.stderr.decode()[:200]}",
        )
    return True, "audit CLI reachable (--help OK)"


def write_report(text: str) -> Path:
    """Write the prepare report, falling back inside the worktree if needed."""
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        REPORT_FILE.write_text(text, encoding="utf-8")
        return REPORT_FILE
    except PermissionError:
        FALLBACK_REPORT_FILE.parent.mkdir(parents=True, exist_ok=True)
        FALLBACK_REPORT_FILE.write_text(text, encoding="utf-8")
        return FALLBACK_REPORT_FILE


# ---------------------------------------------------------------------------
# Entry
# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--skip-cli",
        action="store_true",
        help="skip the `geode audit --help` reachability check",
    )
    args = parser.parse_args()

    print("autoresearch — prepare.py sanity check")
    print(f"  repo: {REPO_ROOT}")
    print()

    started = time.time()
    checks = [
        ("seed pool", check_seed_pool()),
        ("rubric", check_rubric()),
        ("audit CLI", check_audit_cli(args.skip_cli)),
    ]
    elapsed = time.time() - started

    all_ok = True
    lines: list[str] = []
    for label, (ok, msg) in checks:
        marker = "OK " if ok else "FAIL"
        line = f"  [{marker}] {label}: {msg}"
        print(line)
        lines.append(line)
        all_ok = all_ok and ok

    report_path = write_report(
        "\n".join(
            [
                f"autoresearch-petri prepare report — {time.strftime('%Y-%m-%d %H:%M:%S')}",
                f"elapsed_seconds: {elapsed:.2f}",
                f"all_ok: {all_ok}",
                "",
                *lines,
            ]
        )
        + "\n"
    )
    print()
    print(f"report → {report_path}")

    if not all_ok:
        print("\nprepare failed — fix the issues above before running train.py")
        return 1

    print(json.dumps({"status": "ok", "elapsed_seconds": round(elapsed, 2)}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
