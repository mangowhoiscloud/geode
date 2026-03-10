# P3: Batch 분석 + 비교 리포트

> Priority: P3 | Effort: Medium | Impact: 다수 IP 일괄 분석 및 랭킹

## 현황

- CLI에서 단일 IP만 분석 가능 (`geode analyze "Cowboy Bebop"`)
- 200+ fixture 존재하지만 일괄 처리 불가
- IP 간 비교/랭킹 기능 없음

## 목표

- `geode batch --top 20` 으로 상위 N개 IP 일괄 분석
- IP 간 비교 매트릭스 생성
- 최종 랭킹 리포트 (CSV + HTML)

## 구현 계획

### 1. Batch CLI 명령

```python
@app.command()
def batch(
    top: int = 20,
    genre: str | None = None,
    output: str = "batch_report.html",
    concurrency: int = 2,
    dry_run: bool = False,
):
    """Run GEODE analysis on multiple IPs."""
    ips = select_ips(top=top, genre=genre)

    results = []
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        futures = {pool.submit(run_single, ip, dry_run): ip for ip in ips}
        for future in as_completed(futures):
            results.append(future.result())

    # 랭킹 생성
    ranked = sorted(results, key=lambda r: r["final_score"], reverse=True)
    generate_batch_report(ranked, output)
```

### 2. IP 선정 전략

```python
def select_ips(*, top: int, genre: str | None) -> list[str]:
    """Fixture에서 분석 대상 IP 선정."""
    from core.fixtures import FIXTURE_MAP

    candidates = list(FIXTURE_MAP.keys())
    if genre:
        candidates = [ip for ip in candidates if genre_matches(ip, genre)]

    # 무작위 또는 알파벳순
    return candidates[:top]
```

### 3. 비교 매트릭스

| IP | Tier | Score | Cause | Analyst Avg | Quality | Momentum |
|---|---|---|---|---|---|---|
| Hades | S | 92.1 | niche_gem | 4.6 | 95 | 89 |
| Cowboy Bebop | A | 74.8 | conversion_failure | 3.9 | 65 | 77 |
| ... | ... | ... | ... | ... | ... | ... |

### 4. HTML 리포트 생성

```python
def generate_batch_report(ranked: list[dict], output: str):
    """Rich HTML 리포트 생성."""
    # Jinja2 템플릿으로 렌더링
    # 포함: 랭킹 테이블, 점수 분포 차트, 원인별 분류, 권장 액션 요약
    ...
```

## 수정 파일

| 파일 | 변경 |
|---|---|
| `geode/cli/__init__.py` | `batch` 커맨드 추가 |
| `geode/cli/batch.py` | 신규: 배치 로직 |
| `geode/cli/report.py` | 신규: HTML 리포트 생성 |
| `templates/batch_report.html` | 신규: Jinja2 템플릿 |
