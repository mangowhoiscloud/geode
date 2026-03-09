# CUSUM Drift Detection과 Automation Triggers — AI Agent의 자가 교정 시스템

> Date: 2026-03-09 | Author: geode-team | Tags: CUSUM, drift-detection, automation, scheduler, hooks, PSI

## 목차

1. 도입: Agent는 왜 드리프트를 감지해야 하는가
2. CUSUM 알고리즘 구현
3. PSI(Population Stability Index) 보완
4. Automation Scheduler — 3-Type 스케줄링
5. Hook System — 18개 이벤트 기반 트리거
6. 사전 정의 자동화 템플릿
7. 마무리

---

## 1. 도입: Agent는 왜 드리프트를 감지해야 하는가

LLM 기반 Agent 시스템은 시간이 지남에 따라 성능이 변화합니다. 모델 업데이트, 데이터 분포 변화, 평가 기준의 미묘한 이동이 누적되면 출력 품질이 저하됩니다. GEODE는 CUSUM(Cumulative Sum) 통계적 프로세스 제어를 적용하여 이러한 드리프트(Drift)를 실시간으로 감지하고, 자동화 트리거로 교정 조치를 실행합니다.

## 2. CUSUM 알고리즘 구현

CUSUM은 Page(1954)가 제안한 순차적 분석 기법으로, 작은 변화의 누적을 감지하는 데 최적화되어 있습니다.

```python
# geode/automation/drift.py
class CUSUMDetector:
    """Page(1954) CUSUM 드리프트 감지기.

    WARNING >= 2.5, CRITICAL >= 4.0
    """
    WARNING_THRESHOLD = 2.5
    CRITICAL_THRESHOLD = 4.0
    DEFAULT_ALLOWANCE_K = 0.5  # 반-시그마 허용치

    def __init__(self, metric_configs: list[DriftMetricConfig] | None = None,
                 allowance_k: float = DEFAULT_ALLOWANCE_K) -> None:
        self._baselines: dict[str, tuple[float, float]] = {}  # (mean, std)
        self._cusum_pos: dict[str, float] = {}
        self._cusum_neg: dict[str, float] = {}
        self._allowance_k = allowance_k
```

### 핵심 감지 로직

```python
# geode/automation/drift.py
def detect(self, metric_name: str, value: float) -> DriftAlert:
    """CUSUM 감지 실행."""
    mean, std = self._baselines[metric_name]

    # 정규화된 편차
    z = (value - mean) / std

    # CUSUM 누적기 업데이트 (Page 1954)
    k = self._allowance_k
    self._cusum_pos[metric_name] = max(0.0, self._cusum_pos[metric_name] + z - k)
    self._cusum_neg[metric_name] = max(0.0, self._cusum_neg[metric_name] - z - k)

    cusum_score = max(self._cusum_pos[metric_name], self._cusum_neg[metric_name])

    if cusum_score >= self.CRITICAL_THRESHOLD:
        severity = DriftSeverity.CRITICAL
    elif cusum_score >= self.WARNING_THRESHOLD:
        severity = DriftSeverity.WARNING
    else:
        severity = DriftSeverity.NONE

    return DriftAlert(
        metric_name=metric_name,
        severity=severity,
        cusum_score=cusum_score,
        current_value=value,
        baseline_mean=mean,
        baseline_std=std,
    )
```

> `k`(allowance)는 소규모 변동을 무시하는 슬랙 파라미터입니다. `k=0.5`(반-시그마)로 설정하면 1σ 미만의 노이즈를 필터링하면서도 지속적인 0.5σ 이상의 이동을 감지합니다. 양방향(positive/negative) CUSUM으로 상승과 하락 드리프트를 모두 포착합니다.

### 모니터링 메트릭

```python
# geode/automation/drift.py
DEFAULT_METRIC_CONFIGS = [
    DriftMetricConfig(name="spearman_rho", threshold=0.50),
    DriftMetricConfig(name="human_llm_alpha", threshold=0.80),
    DriftMetricConfig(name="precision_at_10", threshold=0.60),
    DriftMetricConfig(name="tier_accuracy", threshold=0.70),
]
```

| 메트릭 | 의미 | 임계 |
|---|---|---|
| spearman_rho | 순위 상관 | 0.50 |
| human_llm_alpha | 인간-LLM 일치도 | 0.80 |
| precision_at_10 | Top-10 정밀도 | 0.60 |
| tier_accuracy | 티어 분류 정확도 | 0.70 |

### 상태 영속화

```python
# geode/automation/drift.py
def save_results(self, path: str | Path) -> None:
    """감지 이력 JSON 저장 (baselines, CUSUM 상태, 통계)."""
    data = {
        "baselines": {n: {"mean": m, "std": s} for n, (m, s) in self._baselines.items()},
        "cusum_state": {
            n: {"s_pos": self._cusum_pos.get(n, 0.0), "s_neg": self._cusum_neg.get(n, 0.0)}
            for n in self._baselines
        },
    }
    Path(path).write_text(json.dumps(data, indent=2))
```

## 3. PSI(Population Stability Index) 보완

CUSUM은 점진적 드리프트에 강하지만, 분포 자체의 급격한 변화는 PSI로 보완합니다.

```python
# geode/automation/drift.py
@staticmethod
def compute_psi(expected: list[float], actual: list[float], n_bins: int = 10) -> float:
    """PSI 계산: 분포 안정성 지수.

    < 0.10: 유의한 변화 없음
    0.10-0.25: 중간 변화 (모니터링)
    > 0.25: 유의한 변화 (경고)
    """
    psi = float(np.sum((actual_pct - expected_pct) * np.log(actual_pct / expected_pct)))
    return psi
```

| PSI 값 | 판정 | 조치 |
|---|---|---|
| < 0.10 | 안정 | 정상 운영 |
| 0.10 - 0.25 | 중간 | 모니터링 강화 |
| > 0.25 | 유의 | 재교정 트리거 |

## 4. Automation Scheduler — 3-Type 스케줄링

드리프트 감지가 트리거되면 자동화 작업이 실행됩니다. GEODE의 Scheduler는 3가지 스케줄링 유형을 지원합니다.

```python
# geode/automation/scheduler.py
class ScheduleKind(Enum):
    AT = "at"        # 일회성 절대 시각
    EVERY = "every"  # 고정 간격 (앵커 기반)
    CRON = "cron"    # Cron 표현식

class SchedulerService:
    def compute_next_run(self, job: ScheduledJob, now_ms: float | None = None) -> float | None:
        if kind == ScheduleKind.AT:
            return job.schedule.at_ms if job.schedule.at_ms > now else None
        elif kind == ScheduleKind.EVERY:
            # 앵커 기반 정렬: 재시작 시 드리프트 방지
            anchor = job.schedule.anchor_ms or job.created_at_ms
            elapsed = now - anchor
            periods = int(elapsed / interval)
            return anchor + (periods + 1) * interval
        else:  # CRON
            return now + (60_000 - now % 60_000)
```

> EVERY 스케줄은 앵커 기반 정렬을 사용합니다. 서비스가 재시작되어도 원래 스케줄과 동일한 시간에 실행되므로 drift가 발생하지 않습니다.

### Active Hours Gate

```python
# geode/automation/scheduler.py
class ActiveHours:
    """자동화 실행 시간 제한. 자정 경유 지원."""
    start: str = ""  # "HH:MM"
    end: str = ""    # "HH:MM"
    timezone: str = ""

def is_within_active_hours(self, active_hours: ActiveHours) -> bool:
    if start_min <= end_min:
        return start_min <= current_min < end_min  # 일반: 09:00-22:00
    return current_min >= start_min or current_min < end_min  # 자정 경유: 22:00-06:00
```

### Per-Job Run Log

```python
# geode/automation/scheduler.py
class JobRunLog:
    """Job별 JSONL 실행 이력. 자동 정리."""
    MAX_LINES: int = 2000
    MAX_BYTES: int = 2 * 1024 * 1024  # 2MB

    def prune(self, job_id: str) -> int:
        """크기/줄 초과 시 원자적 정리 (tmp → rename)."""
        os.replace(str(tmp_path), str(path))
```

## 5. Hook System — 18개 이벤트 기반 트리거

GEODE의 Hook System은 파이프라인 생명주기에서 18개 이벤트를 발행합니다. 자동화 트리거는 이 이벤트에 등록됩니다.

```python
# geode/orchestration/hooks.py
class HookEvent(Enum):
    # Pipeline
    PIPELINE_START = "pipeline_start"
    PIPELINE_END = "pipeline_end"
    PIPELINE_ERROR = "pipeline_error"
    # Node
    NODE_ENTER = "node_enter"
    NODE_EXIT = "node_exit"
    NODE_ERROR = "node_error"
    # Analysis
    ANALYST_COMPLETE = "analyst_complete"
    EVALUATOR_COMPLETE = "evaluator_complete"
    SCORING_COMPLETE = "scoring_complete"
    # Verification
    VERIFICATION_PASS = "verification_pass"
    VERIFICATION_FAIL = "verification_fail"
    # Automation (L4.5)
    DRIFT_DETECTED = "drift_detected"
    OUTCOME_COLLECTED = "outcome_collected"
    TRIGGER_FIRED = "trigger_fired"
    ...
```

### Drift Scan Hook 등록

```python
# geode/graph.py
def _register_drift_scan_hook(hooks: HookSystemPort) -> None:
    detector = CUSUMDetector()

    def _on_scoring_complete(event: HookEvent, data: dict[str, Any]) -> None:
        if not data.get("drift_scan_hint"):
            return
        score = data.get("final_score", 0.0)
        alerts = detector.scan_all({"final_score": score})
        if alerts:
            hooks.trigger(HookEvent.DRIFT_DETECTED, {
                "source": "scoring_complete_hook",
                "alerts": [a.to_dict() for a in alerts],
            })

    hooks.register(HookEvent.SCORING_COMPLETE, _on_scoring_complete,
                   name="drift_scan_on_scoring", priority=50)
```

> SCORING_COMPLETE 이벤트에 CUSUM 스캔을 등록합니다. 점수에서 드리프트가 감지되면 DRIFT_DETECTED 이벤트를 발행하여 하위 자동화가 트리거됩니다. 우선순위 50으로 다른 핸들러보다 먼저 실행됩니다.

## 6. 사전 정의 자동화 템플릿

```python
# geode/automation/predefined.py
PREDEFINED_AUTOMATIONS = [
    AutomationTemplate(
        id="weekly_discovery_scan",
        schedule="0 9 * * 1",  # 월요일 09:00 UTC
        description="Top 50 후보 IP 배치 스캔",
    ),
    AutomationTemplate(
        id="calibration_drift_scan",
        schedule="0 6 * * *",  # 매일 06:00 UTC
        description="일일 CUSUM 드리프트 감지",
        pipeline_config=PipelineConfig(
            mode="evaluation",
            extra={
                "metrics": ["spearman_rho", "human_llm_alpha", "precision_at_10"],
                "cusum_warning_threshold": 2.5,
                "cusum_critical_threshold": 4.0,
            },
        ),
    ),
    AutomationTemplate(
        id="outcome_tracker",
        schedule="0 0 1 * *",  # 매월 1일
        description="월간 Outcome 추적",
    ),
    # ... (총 10개 템플릿)
]
```

| 자동화 | 스케줄 | 트리거 조건 |
|---|---|---|
| Weekly Discovery | 월 09:00 | 크론 |
| Drift Scan | 매일 06:00 | 크론 |
| Outcome Tracker | 매월 1일 | 크론 |
| Re-calibration | DRIFT_DETECTED | 이벤트 |

## 7. 마무리

### 핵심 정리

| 항목 | 값/설명 |
|---|---|
| CUSUM 알고리즘 | Page(1954), 양방향 (positive + negative) |
| 임계값 | WARNING >= 2.5, CRITICAL >= 4.0 |
| Allowance (k) | 0.5 (반-시그마 슬랙) |
| PSI 보완 | < 0.10 안정, > 0.25 유의 |
| 스케줄 유형 | AT (일회성), EVERY (앵커 기반), CRON |
| Active Hours | 자정 경유 지원, IANA 타임존 |
| Hook 이벤트 | 18개 (Pipeline/Node/Analysis/Automation) |
| Run Log | Per-Job JSONL, 2000줄/2MB 자동 정리 |

### 체크리스트

- [ ] CUSUM 양방향(positive/negative) 누적기 구현
- [ ] Allowance k=0.5로 노이즈 필터링
- [ ] PSI 분포 안정성 보완 감지
- [ ] 3-Type Scheduler (AT/EVERY/CRON) 구현
- [ ] 앵커 기반 정렬로 재시작 드리프트 방지
- [ ] Active Hours 자정 경유 지원
- [ ] SCORING_COMPLETE → DRIFT_DETECTED 훅 체인
- [ ] Per-Job JSONL 원자적 정리
