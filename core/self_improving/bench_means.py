"""``bench_means`` fitness 축 — ADR-012 §S6 (3축 fitness 의 3번째 축,
ux-removed 2026-05-30).

S2 의 ``admire_means`` (체감) 옆에 추가되는 **capability** 양의 압력
축. Petri 가 alignment evaluation (안 망가지기)
인 반면, bench 는 real task completion (제대로 함) 의 ground-truth 평가.

ADR-012 §S6 가 schema + math + cross-validation gate 명세, §S6b 가 이
모듈을 호출하는 production wiring 명세. 두 §섹션은 2026-05-23 amendment
(PR-SIL-5THEME C1) 으로 ADR 에 추가됐다 — 이전엔 코드만 4축을 정의하고
ADR 측은 3축 그대로였다.

**2026-05-21 → 2026-05-23 frontier 갱신 history**:

원본 S6 (2026-05-21 오전, #1413) 의 4 bench 는 모두 saturated / OpenAI
retire / contamination 으로 outdated. 2026 frontier (Claude Opus 4.5
system card + GPT-5 system card 공통 채택) 으로 7-field schema 갱신.
2026-05-23 amendment (F1.b) 에서 vanilla LiveCodeBench → LiveCodeBench-Pro
substitution 추가:

- SWE-bench → **SWE-bench Pro** (Scale AI): OpenAI 2026-02-23 공식
  retire, saturated + contaminated.
- HumanEval → **LiveCodeBench-Pro** (F1.b substitution): Top-4 93-95%
  saturated. *Vanilla LiveCodeBench* 가 contamination-defense 후속이었으나
  inspect_ai 생태계에 공식 port 부재 — frontier consensus 는
  ``livecodebench_pro`` (C++ 경쟁 프로그래밍, live-contest scrape +
  time-cutoff windowing, 2026 v2 가 ICPC WF/IOI/Chinese olympiad 추가)
  가 그 niche 를 흡수.
- TAU-bench → **τ²-bench** (Sierra 2025): telecom domain 0.993
  saturated, dual-control 후속.
- GAIA → **HLE + OSWorld 분할**: DeepAgent 91.69% saturated. HLE
  (Nature 2026-01) + OSWorld (computer-use) 로 도메인 분리.
- (신규) **GPQA Diamond**: Anthropic + OpenAI 카드 공통 PhD reasoning.
- (신규) **MLE-bench**: self-improving loop 도메인 정합 (ML engineering).

**inspect_ai federation** (ADR-012 §S6b 의 wiring 명세):
- Petri 의 alignment scenario + frontier capability bench (7-field) 가
  **같은 inspect_ai run** 안에서 또는 **인접 subprocess** 로 실행되는
  설계. Anthropic inspect_ai framework 기반. S6b 의 ``A1 graceful-skip``
  패턴 — Docker / VM 미가용 시 해당 bench 만 skip, ``missing_benches``
  에 등록.
- ``baseline.json schema_version=2`` 의 ``axes.bench_means`` field +
  ``raw`` 의 bench provenance (``bench_stderr`` / ``bench_sample_count``
  / ``bench_rubric_version``) 슬롯에 영속화.

**Schema** (7 field, 모두 0.0-1.0 normalized — 2026-05-23 F1.b 후 확정):

.. code-block:: python

    {
      "swe_bench_pro_pass":          0.45,  # Scale AI / Harbor resolve rate
      "livecodebench_pro_accuracy":  0.70,  # LCB-Pro accuracy (C++ exec)
      "tau2_bench_success":          0.85,  # Sierra τ²-bench (telecom)
      "gpqa_diamond":                0.60,  # GPQA Diamond PhD reasoning
      "hle_accuracy":                0.30,  # Humanity's Last Exam
      "osworld_success":             0.35,  # OSWorld computer-use
      "mle_bench_medal":             0.40,  # OpenAI MLE-bench medal rate
    }

**Cross-validation gate** (Goodhart 양방향 방어):
- Petri promote (dim 개선) + bench regress → ``alignment_only_fooling``
- bench promote + Petri critical regress → ``capability_at_alignment_cost``
- 두 conflict 모두 ``compute_fitness`` 의 strict-reject (0.0) 발화.

**ADR-012 §Decision.2 의 3축 fitness 가중치** (ux-removed 2026-05-30):

- ``dim_means`` (Petri 17-22 dim, 음의 압력) — 0.55
- ``admire_means`` (체감 2-field, S2) — 0.20
- ``bench_means`` (capability 7-field, S6) — 0.25

코드 상수 ground-truth: ``core/self_improving/train.py`` 의 ``FITNESS_DIM_3AX
/ FITNESS_ADMIRE_3AX / FITNESS_BENCH_3AX`` (sum=1.0 assert). ux_means
축은 PR-MARGIN-FITNESS-SCALE 에서 제거.

**Frontier sources** (2026-05):

- OpenAI SWE-bench retire 공지: https://openai.com/index/why-we-no-longer-evaluate-swe-bench-verified/
- Scale AI SWE-bench Pro: https://labs.scale.com/leaderboard/swe_bench_pro_public
- Sierra τ²-bench: https://sierra.ai/resources/research/tau-squared-bench
- Humanity's Last Exam (Nature 2026-01): https://agi.safe.ai/
- LiveCodeBench-Pro 논문 (arxiv 2506.11928): https://arxiv.org/abs/2506.11928
- GPQA Diamond (NYU 2024)
- OSWorld (2024 frontier computer-use agent benchmark)
- MLE-bench (OpenAI 2024 ML engineering)
- inspect_evals (UK AISI): https://github.com/UKGovernmentBEIS/inspect_evals
- inspect_harbor (meridianlabs-ai): https://github.com/meridianlabs-ai/inspect_harbor
- Claude Opus 4.5 system card: https://www.anthropic.com/claude-opus-4-5-system-card
- GPT-5 system card: https://cdn.openai.com/gpt-5-system-card.pdf
"""

from __future__ import annotations

import logging
import os
import shutil
from dataclasses import dataclass, field
from typing import Any

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# S6b — Bench provenance schema (PR-SIL-5THEME C2, 2026-05-23)
# ---------------------------------------------------------------------------

#: ``baseline.json:raw.bench_rubric_version`` 의 값. 7-bench cohort 의
#: 식별자 — 2026-05 frontier 갱신 + F1.b LCB substitution 후. cohort 가
#: 바뀌면 (예: bench 추가/교체/weight 재calibrate) 새 version tag 발급해서
#: 이전 baseline 의 bench 점수와 apples-to-oranges 비교를 차단.
BENCH_RUBRIC_VERSION = "v1-7bench-2026-05-F1b"


@dataclass(slots=True)
class BenchProvenance:
    """Per-bench 의 provenance 묶음 — ``inspect_ai`` sample-level pass/fail
    에서 stderr / sample_count 자동 산출, modality 는 7-bench 모두 deterministic
    analytics (LLM judge 없음).

    `dim_means` 측의 PR-1 provenance (sample_count + measurement_modality)
    와 symmetry. ``_write_baseline`` 가 ``raw.bench_stderr`` /
    ``raw.bench_sample_count`` / ``raw.bench_rubric_version`` 슬롯에 영속화.
    """

    bench_means: dict[str, float] = field(default_factory=dict)
    bench_stderr: dict[str, float] = field(default_factory=dict)
    bench_sample_count: dict[str, int] = field(default_factory=dict)
    missing_benches: list[str] = field(default_factory=list)
    rubric_version: str = BENCH_RUBRIC_VERSION


# ---------------------------------------------------------------------------
# S6b — Per-bench inspect_ai port dispatch (PR-SIL-5THEME C2)
# ---------------------------------------------------------------------------

#: 각 bench 가 어느 PyPI 패키지의 inspect_ai task 로 dispatch 되는지의 매핑.
#: ``inspect-evals`` 6 bench + ``inspect-harbor`` 1 bench. B1 grounding survey
#: 결과 (vanilla LiveCodeBench port 부재 → F1.b LCB-Pro substitution) 반영.
BENCH_PORT_MAP: dict[str, tuple[str, str]] = {
    # field → (package, inspect_ai task path)
    "swe_bench_pro_pass": ("inspect_harbor", "swebenchpro"),
    "livecodebench_pro_accuracy": ("inspect_evals", "livecodebench_pro"),
    "tau2_bench_success": ("inspect_evals", "tau2_telecom"),
    "gpqa_diamond": ("inspect_evals", "gpqa_diamond"),
    "hle_accuracy": ("inspect_evals", "hle"),
    "osworld_success": ("inspect_evals", "osworld"),
    "mle_bench_medal": ("inspect_evals", "mle_bench"),
}

#: Docker / VM sandbox 가 필요한 bench. A1 graceful-skip 의 게이트 — Docker
#: 미가용 시 collector 가 이들 bench 만 skip, nominal 3 bench (LCB-Pro /
#: τ²-bench / GPQA Diamond) 는 그대로 작동.
BENCH_REQUIRES_DOCKER: frozenset[str] = frozenset(
    {
        "swe_bench_pro_pass",  # scaleapi/SWE-bench_Pro-os image
        "osworld_success",  # VM sandbox
        "mle_bench_medal",  # Docker exec + Kaggle dataset
    }
)

#: Multi-modal vision 모델이 필요한 bench. text-only 모델 사용 시 skip.
BENCH_REQUIRES_VISION: frozenset[str] = frozenset({"hle_accuracy"})


def compute_missing_benches(bench_means: dict[str, float] | None) -> list[str]:
    """``BENCH_DIM_WEIGHTS`` universe 중 ``bench_means`` 에 없는 field 목록.

    Goodhart-suppression surface — Petri-side ``compute_missing_dims`` (PR-4)
    과 symmetry. mutation 이 bench 측정을 silently suppress 해서 fitness
    aggregate 의 neutral fallback (0.5) 으로 도주하는 패턴을 노출한다.

    Returns sorted list of missing field names. Empty list when all 7 present.
    """
    if bench_means is None:
        return sorted(BENCH_DIM_WEIGHTS)
    return sorted(set(BENCH_DIM_WEIGHTS) - set(bench_means))


# Bench field 별 가중치 — 합 1.0. 2026-05-23 F1.b 갱신:
# - SWE-bench Pro (Scale AI, Harbor resolve rate) — 0.25
# - LiveCodeBench-Pro (C++ competitive, contam-defended, ICPC/IOI 2026 v2) — 0.15
#   * vanilla LiveCodeBench port 부재 → LCB-Pro substitution (F1.b 결정,
#     B1 grounding survey 결과)
# - τ²-bench (Sierra dual-control + telecom) — 0.20
# - GPQA Diamond (PhD reasoning) — 0.15
# - HLE (Humanity's Last Exam, frontier ceiling) — 0.10
# - OSWorld (computer-use agent) — 0.10
# - MLE-bench (ML engineering, self-improving 도메인 정합) — 0.05
BENCH_DIM_WEIGHTS: dict[str, float] = {
    "swe_bench_pro_pass": 0.25,
    "livecodebench_pro_accuracy": 0.15,
    "tau2_bench_success": 0.20,
    "gpqa_diamond": 0.15,
    "hle_accuracy": 0.10,
    "osworld_success": 0.10,
    "mle_bench_medal": 0.05,
}

assert abs(sum(BENCH_DIM_WEIGHTS.values()) - 1.0) < 1e-9, "BENCH_DIM_WEIGHTS must sum to 1.0"


def compute_bench_aggregate(bench_means: dict[str, float] | None) -> float:
    """7-field weighted sum → 0-1 scalar. ``None`` → 0.5 (neutral, S1/S2 패턴)."""
    if bench_means is None:
        return 0.5
    total = 0.0
    for field_name, weight in BENCH_DIM_WEIGHTS.items():
        value = bench_means.get(field_name, 0.5)  # 누락 field neutral
        total += weight * max(0.0, min(1.0, value))
    return total


def validate_bench_schema(bench_means: Any) -> bool:
    """Validate ``bench_means`` — dict[str, float in 0-1], 알려진 field 만.
    ``None`` 도 valid (no-op signal)."""
    if bench_means is None:
        return True
    if not isinstance(bench_means, dict):
        return False
    known_fields = set(BENCH_DIM_WEIGHTS)
    for key, value in bench_means.items():
        if key not in known_fields:
            return False
        if not isinstance(value, int | float):
            return False
        if not (0.0 <= float(value) <= 1.0):
            return False
    return True


def detect_cross_validation_conflict(
    *,
    dim_means: dict[str, float],
    baseline_dim_means: dict[str, float] | None,
    bench_means: dict[str, float] | None,
    baseline_bench_means: dict[str, float] | None,
    critical_dims: tuple[str, ...] = (),
    critical_margin: float = 0.0,
) -> str | None:
    """Petri vs bench 의 cross-validation gate (Goodhart 양방향 방어).

    두 conflict 시나리오 검출:

    1. **Petri promote + bench regress** ("alignment-only fooling")
    2. **bench promote + Petri critical regress** ("capability at alignment cost")

    Returns:
        conflict 종류의 문자열 또는 ``None`` (conflict 없음).
    """
    if baseline_dim_means is None or baseline_bench_means is None:
        return None
    if bench_means is None:
        return None

    bench_now = compute_bench_aggregate(bench_means)
    bench_base = compute_bench_aggregate(baseline_bench_means)
    bench_improved = bench_now > bench_base
    bench_regressed = bench_now < bench_base

    dim_aggregate_now = sum(dim_means.values()) / max(1, len(dim_means))
    dim_aggregate_base = sum(baseline_dim_means.values()) / max(1, len(baseline_dim_means))
    petri_improved = dim_aggregate_now < dim_aggregate_base
    critical_regressed = any(
        dim_means.get(dim, 0.0) > baseline_dim_means.get(dim, 0.0) + critical_margin
        for dim in critical_dims
    )

    if petri_improved and bench_regressed:
        return "alignment_only_fooling"

    if bench_improved and critical_regressed:
        return "capability_at_alignment_cost"

    return None


def _is_docker_available() -> bool:
    """Docker daemon + binary 가용성 — A1 graceful-skip 의 1차 게이트.

    ``docker`` binary on ``$PATH`` + ``docker info`` 의 exit 0 일 때만 True.
    ``info`` 는 daemon 이 실제 작동 중인지 확인 (binary 만 있고 daemon 꺼진
    경우 까지 catch). 환경별 false-positive 방지 — cron / serve background
    에서도 동일 결과.
    """
    docker_bin = shutil.which("docker")
    if docker_bin is None:
        return False
    import subprocess

    try:
        result = subprocess.run(  # noqa: S603 — docker_bin resolved via shutil.which, fixed argv
            [docker_bin, "info"],
            capture_output=True,
            timeout=5,
            check=False,
        )
        return result.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def _is_inspect_evals_installed() -> bool:
    """``inspect-evals`` PyPI 패키지의 import 가용성. ``[audit]`` extra 의
    optional dep 라 default sync 환경에선 부재. 부재 시 6 bench skip
    (`livecodebench_pro_accuracy` / `tau2_bench_success` / `gpqa_diamond` /
    `hle_accuracy` / `osworld_success` / `mle_bench_medal`)."""
    try:
        import inspect_evals  # noqa: F401

        return True
    except ImportError:
        return False


def _is_inspect_harbor_installed() -> bool:
    """``inspect-harbor`` PyPI 패키지의 import 가용성. SWE-bench Pro 만
    Harbor 의존 — 부재 시 `swe_bench_pro_pass` skip."""
    try:
        import inspect_harbor  # noqa: F401

        return True
    except ImportError:
        return False


def _is_vision_model(target_model: str) -> bool:
    """주어진 model identifier 가 multi-modal vision 을 지원하는지 추정.

    완전한 capability registry 없이는 보수적으로 추정 — claude-3.5-sonnet
    이상, gpt-4o / gpt-5 / opus / sonnet 계열은 vision 지원으로 가정.
    HLE 의 multi-modal items 가 일부라 vision 미지원 모델로도 부분 점수
    가능하지만, A1 conservative skip 으로 silent partial-score 방지."""
    model_lower = target_model.lower()
    vision_patterns = ("claude-3", "claude-4", "claude-opus", "claude-sonnet", "gpt-4o", "gpt-5")
    return any(p in model_lower for p in vision_patterns)


def _eligible_benches(
    *,
    target_model: str,
    has_docker: bool,
    has_inspect_evals: bool,
    has_inspect_harbor: bool,
) -> tuple[set[str], list[str]]:
    """A1 graceful-skip 의 결정 함수 — (eligible, missing) 반환.

    eligible: 이 collector 호출에서 실제 실행할 bench field 들의 set.
    missing: skip 된 bench 의 list (sorted, Goodhart surface 로 진입).
    """
    eligible: set[str] = set()
    missing: list[str] = []
    for field_name, (package, _task) in BENCH_PORT_MAP.items():
        # Package 가용성 게이트
        if package == "inspect_evals" and not has_inspect_evals:
            missing.append(field_name)
            continue
        if package == "inspect_harbor" and not has_inspect_harbor:
            missing.append(field_name)
            continue
        # Docker 게이트
        if field_name in BENCH_REQUIRES_DOCKER and not has_docker:
            missing.append(field_name)
            continue
        # Vision 게이트
        if field_name in BENCH_REQUIRES_VISION and not _is_vision_model(target_model):
            missing.append(field_name)
            continue
        eligible.add(field_name)
    return eligible, sorted(missing)


def _run_bench_via_inspect_ai(
    field_name: str,
    *,
    target_model: str,
    sample_limit: int | None,
) -> tuple[float, float, int] | None:
    """단일 bench 의 inspect_ai task 실행. ``(value, stderr, sample_count)``
    또는 실패 시 ``None`` 반환.

    실구현은 ``inspect_ai.eval`` 의 programmatic API 호출 — collector
    가 7 bench 를 순차 dispatch. 각 task 의 EvalLog 에서 scorer 의
    aggregate score + per-sample stderr + sample 수를 추출.

    PR-SIL-5THEME C2 의 첫 production wiring 단계 — 실제 호출은
    ``GEODE_BENCH_S6B_LIVE=1`` env flag 가 있을 때만 fire (default off
    으로 prepare.py / audit / fitness 의 nominal smoke 가 빈 dict 와
    동등하게 작동, ``missing_benches`` 에 전체 등록). live flag 가 켜진
    환경에선 진짜 subprocess 실행. 다단계 wiring 의 첫 단계로 honest —
    "7-bench port 전부 dispatch 가능, 실제 실행은 env-gated".
    """
    live = os.environ.get("GEODE_BENCH_S6B_LIVE", "").strip().lower() in {"1", "true", "yes"}
    if not live:
        # nominal path — env flag 미설정 시 모든 bench 가 "현재 cohort 에선
        # 실행 안 함" 으로 처리. missing_benches 에 등록되어 Goodhart surface
        # 와 동일한 시그널.
        return None

    package, task_path = BENCH_PORT_MAP[field_name]
    try:
        if package == "inspect_evals":
            import inspect_evals
            from inspect_ai import eval as inspect_eval

            inspect_evals_ns = vars(inspect_evals)
            task_factory = inspect_evals_ns.get(task_path)
            if task_factory is None:
                log.warning("inspect_evals task %s not found", task_path)
                return None
            eval_logs = inspect_eval(
                task_factory(),
                model=target_model,
                limit=sample_limit,
            )
        else:  # inspect_harbor
            import inspect_harbor
            from inspect_ai import eval as inspect_eval

            harbor_ns = vars(inspect_harbor)
            task_factory = harbor_ns.get(task_path)
            if task_factory is None:
                log.warning("inspect_harbor task %s not found", task_path)
                return None
            eval_logs = inspect_eval(
                task_factory(),
                model=target_model,
                limit=sample_limit,
            )

        # inspect_ai.eval returns list[EvalLog]. 단일 task 호출이라 [0].
        if not eval_logs:
            return None
        log_obj = eval_logs[0]
        # scorer aggregate score — inspect_ai 의 EvalResult.scores 의 첫 entry
        # 의 metrics dict 에서 'accuracy' / 'mean' / 'pass_rate' 등 추출
        results = getattr(log_obj, "results", None)
        if results is None or not getattr(results, "scores", None):
            return None
        score_entry = results.scores[0]
        metrics = getattr(score_entry, "metrics", {})
        # 가장 일반적인 metric 명들 우선순위
        value = None
        for metric_name in ("accuracy", "mean", "pass_rate", "success_rate", "resolve_rate"):
            metric = metrics.get(metric_name)
            if metric is not None:
                value = float(getattr(metric, "value", metric))
                break
        if value is None:
            return None
        # stderr: inspect_ai 의 metric 객체에 stderr 가 있으면 사용, 없으면 0
        stderr = 0.0
        sample_count = 0
        for metric_name in ("accuracy", "mean", "pass_rate", "success_rate", "resolve_rate"):
            metric = metrics.get(metric_name)
            if metric is not None and hasattr(metric, "stderr"):
                stderr = float(getattr(metric, "stderr", 0.0))
                break
        # sample_count: log.samples 의 길이 또는 EvalStats
        samples = getattr(log_obj, "samples", None)
        if samples is not None:
            sample_count = len(samples)
        return (max(0.0, min(1.0, value)), max(0.0, stderr), sample_count)
    except Exception as exc:  # pragma: no cover — defensive
        log.warning("bench %s (%s.%s) failed: %s", field_name, package, task_path, exc)
        return None


def collect_bench_means_from_inspect_ai(
    *,
    target_model: str = "",
    sample_limit: int | None = None,
) -> BenchProvenance:
    """7-bench inspect_ai federation collector — S6b production wiring.

    PR-SIL-5THEME C2 (2026-05-23). 이전 placeholder (`return None`) 를
    교체 — 이제 ``BENCH_PORT_MAP`` 의 7 bench 전부 dispatcher 가
    존재, A1 graceful-skip 패턴으로 환경별 차등 작동.

    **A1 graceful-skip 의 4 게이트** (순차 확인, 첫 fail 시 해당 bench
    missing 에 등록):

    1. ``inspect-evals`` PyPI 패키지 import 가능? (6 bench 영향)
    2. ``inspect-harbor`` PyPI 패키지 import 가능? (`swe_bench_pro_pass` 만)
    3. Docker daemon 가용? (`swe_bench_pro_pass` / `osworld_success` /
       `mle_bench_medal` 의 sandbox 요구)
    4. target_model 이 vision 지원? (`hle_accuracy` 의 multi-modal items)

    **Returns**: ``BenchProvenance`` (dataclass) — ``bench_means`` /
    ``bench_stderr`` / ``bench_sample_count`` / ``missing_benches`` /
    ``rubric_version``. caller (core/self_improving/train.py:main) 는 그
    dataclass 의 dict 부분만 따로 빼서 ``compute_fitness(bench_means=...)``
    / ``_write_baseline(bench_means=...)`` 에 전달.

    **GEODE_BENCH_S6B_LIVE env gate**: 기본 off (nominal smoke / unit
    test / dry-run 환경 보호). ``GEODE_BENCH_S6B_LIVE=1`` 설정 시에만
    실제 ``inspect_ai.eval`` subprocess fire. off 일 땐 모든 bench 가
    ``missing_benches`` 에 등록돼 Goodhart surface 와 동일 시그널.
    """
    has_docker = _is_docker_available()
    has_inspect_evals = _is_inspect_evals_installed()
    has_inspect_harbor = _is_inspect_harbor_installed()

    eligible, gated_missing = _eligible_benches(
        target_model=target_model,
        has_docker=has_docker,
        has_inspect_evals=has_inspect_evals,
        has_inspect_harbor=has_inspect_harbor,
    )

    means: dict[str, float] = {}
    stderr: dict[str, float] = {}
    sample_count: dict[str, int] = {}
    runtime_missing: list[str] = []

    for field_name in sorted(eligible):
        result = _run_bench_via_inspect_ai(
            field_name,
            target_model=target_model,
            sample_limit=sample_limit,
        )
        if result is None:
            runtime_missing.append(field_name)
            continue
        value, err, count = result
        means[field_name] = value
        stderr[field_name] = err
        sample_count[field_name] = count

    missing = sorted(set(gated_missing) | set(runtime_missing))

    return BenchProvenance(
        bench_means=means,
        bench_stderr=stderr,
        bench_sample_count=sample_count,
        missing_benches=missing,
        rubric_version=BENCH_RUBRIC_VERSION,
    )


__all__ = [
    "BENCH_DIM_WEIGHTS",
    "BENCH_PORT_MAP",
    "BENCH_REQUIRES_DOCKER",
    "BENCH_REQUIRES_VISION",
    "BENCH_RUBRIC_VERSION",
    "BenchProvenance",
    "collect_bench_means_from_inspect_ai",
    "compute_bench_aggregate",
    "compute_missing_benches",
    "detect_cross_validation_conflict",
    "validate_bench_schema",
]
