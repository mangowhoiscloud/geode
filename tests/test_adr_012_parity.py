"""ADR-012 ↔ code parity invariants — catches silent drift between the
ADR (`docs/adr/ADR-012-self-improvement-surface-tiers.md`) and the
ground-truth runtime constants (`autoresearch/train.py` /
`autoresearch/bench_means.py`).

PR-SIL-5THEME C1 (2026-05-23) — codifies the
CHANGELOG/PR-body-parity anti-deception lesson (CLAUDE.md DONT row
1, PR-G5b #1350) for the §S6/§S6b ADR amendments. Without these
tests a future ADR edit could regress the doc to "3축" or drop
``§S6`` and the build would stay green.
"""

from __future__ import annotations

import re
from pathlib import Path

from autoresearch.bench_means import BENCH_DIM_WEIGHTS
from autoresearch.train import (
    FITNESS_ADMIRE_4AX,
    FITNESS_BENCH_4AX,
    FITNESS_DIM_4AX,
    FITNESS_UX_4AX,
)

ADR_PATH = (
    Path(__file__).resolve().parent.parent
    / "docs"
    / "adr"
    / ("ADR-012-self-improvement-surface-tiers.md")
)


def _adr_text() -> str:
    return ADR_PATH.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# §Decision.2 — 4축 명세 invariants
# ---------------------------------------------------------------------------


def test_adr012_decision2_header_says_4axis() -> None:
    """§Decision.2 의 헤더가 "4축" 명시 (이전 "3축" 에서 amend).

    Why: amendment 가 빠지면 doc 가 코드의 `FITNESS_BENCH_4AX` 명세와
    drift — PR-G5b #1350 의 "X-driven" 거짓 claim 과 동형 anti-deception.
    """
    txt = _adr_text()
    assert "### 2. Fitness 다축화 — 4축 multi-axis strict-reject ratchet" in txt


def test_adr012_decision2_weights_match_code_constants() -> None:
    """§Decision.2 의 "축별 권장 가중치" 줄 4 개 weight 가 코드 상수와 일치.

    코드 상수는 ``autoresearch/train.py:344-350`` 의 ``FITNESS_*_4AX``
    (합 1.0 assert). 이 테스트가 ADR 측 표기 ``0.30 / 0.25 / 0.20 / 0.25``
    가 코드와 같은지 검증 — 둘 다 1.0 이라도 분배가 다르면 fail.
    """
    txt = _adr_text()
    # 첫 amendment 의 가중치 줄
    pattern = (
        r"`dim_means`\s*(\d+\.\d+)\s*,\s*"
        r"`ux_means`\s*(\d+\.\d+)\s*,\s*"
        r"`admire_means`\s*(\d+\.\d+)\s*,\s*"
        r"`bench_means`\s*(\d+\.\d+)"
    )
    match = re.search(pattern, txt)
    assert match is not None, "ADR §Decision.2 의 4-axis 가중치 표기 미발견"
    adr_weights = tuple(float(g) for g in match.groups())
    code_weights = (
        FITNESS_DIM_4AX,
        FITNESS_UX_4AX,
        FITNESS_ADMIRE_4AX,
        FITNESS_BENCH_4AX,
    )
    assert adr_weights == code_weights, f"ADR weights {adr_weights} != code weights {code_weights}"


def test_adr012_deprecates_seed_pool_diversity() -> None:
    """§Decision.2 의 ``seed_pool_diversity`` 가 명시적 deprecate.

    초안의 4번째 묶음으로 명시됐으나 코드 0 grep (PR-SIL-5THEME C1
    grounding). amendment 가 deprecate 결정을 명시 — 미명시 시 future
    reader 가 "코드에 있어야 하나" 혼동.
    """
    txt = _adr_text()
    assert "Deprecated slot — `seed_pool_diversity`" in txt


# ---------------------------------------------------------------------------
# §S6 — Bench fitness axis 신설 invariants
# ---------------------------------------------------------------------------


def test_adr012_has_s6_section() -> None:
    """ADR 에 ``### S6.`` 섹션 헤더 존재.

    Why: ``autoresearch/bench_means.py`` docstring 의 "ADR-012 §S6"
    인용이 grep-provable — PR-G5b #1350 lesson.
    """
    txt = _adr_text()
    assert "### S6. Bench fitness axis" in txt


def test_adr012_s6_schema_field_names_match_code() -> None:
    """§S6.2 의 7-bench schema field name 이 ``BENCH_DIM_WEIGHTS`` 와 일치.

    F1.b substitution: ``livecodebench_pass1`` → ``livecodebench_pro_accuracy``.
    ADR 표기와 코드 상수가 어긋나면 collector 가 어느 쪽 ID 로 emit 할지
    모호해짐.
    """
    txt = _adr_text()
    for field in BENCH_DIM_WEIGHTS:
        # Markdown 의 backtick 인용 또는 plain 둘 다 OK
        assert f"`{field}`" in txt or field in txt, f"ADR §S6 에 field 누락: {field}"


def test_adr012_s6_weights_match_bench_dim_weights() -> None:
    """§S6.2 표의 weight column 이 ``BENCH_DIM_WEIGHTS`` 와 일치.

    표 행의 ``| `<field>` | <weight> | <metric> |`` 패턴을 파싱해서
    weight 일치 확인.
    """
    txt = _adr_text()
    # 표 라인 패턴: | `field` | 0.NN | ...
    pattern = re.compile(r"\|\s*`(\w+)`\s*\|\s*(\d+\.\d+)\s*\|")
    rows = dict(pattern.findall(txt))
    for field, expected_weight in BENCH_DIM_WEIGHTS.items():
        assert field in rows, f"ADR §S6.2 의 표에 field 누락: {field}"
        assert float(rows[field]) == expected_weight, (
            f"ADR §S6.2 weight mismatch for {field}: ADR={rows[field]} vs code={expected_weight}"
        )


def test_adr012_has_s6b_section() -> None:
    """ADR 에 ``### S6b.`` (production wiring) 섹션 존재.

    Why: ``autoresearch/bench_means.py`` docstring 의 "§S6b 의 wiring
    명세" 인용이 grep-provable.
    """
    txt = _adr_text()
    assert "### S6b. Bench production wiring" in txt


def test_adr012_pr_sequence_lists_s6_and_s6b() -> None:
    """ "후속 PR 시퀀스" 표가 S6 / S6b 모두 포함.

    Amendment 가 leakage 없이 doc 의 모든 정합 지점을 갱신했는지 확인.
    """
    txt = _adr_text()
    assert "**S6** — `bench_means`" in txt
    assert "**S6b** — `bench_means` production wiring" in txt
