# Stanford CS329A Test-Time Compute Scaling Part 2

| 항목 | 값 |
|---|---|
| 수집·검증일 | 2026-08-05 |
| 원본 | [Stanford CS329A Self-Improving AI Agents · Part 2](https://www.youtube.com/watch?v=-Ggc37xLj_Y) |
| 강의 시점 | 2025-09-26, Stanford CS329A Lecture 2 |
| 공개 시점 | 2026-08-03, Stanford Online |
| 강연자 | Azalia Mirhoseini |
| 길이 | 63분 20초 |

## 한 문장 결론

`[해석]` Test-time compute는 모델에게 단순히 더 긴 추론을 허용하는 기법이
아니다. 같은 문제를 넓게 탐색하는 `candidate width`, 한 후보를 연속 수정하는
`revision depth`, 후보를 가르는 `verification`, 연산자 조합 자체를 찾는
`inference-program search`를 과제 난도·비용·검증 가능성에 맞춰 배분하는
실행 정책이다.

강의의 핵심 경고는 더 짧다.

> 후보가 늘면 oracle coverage는 상승한다. 그러나 verifier가 희소한 정답을
> 식별하지 못하면 delivered correctness는 포화한다.

## 조사 방법과 증거 경계

이번 문서는 1시간 전체를 다음 자료로 교차 확인했다.

- 로컬 MP4 전 구간 재생과 60초 간격 contact sheet 6장
- YouTube 자동 영문 자막 4,120행 전체
- Stanford CS329A 공식 syllabus와 Lecture 2 지정 논문 4편
- 논문 최신 arXiv abstract와 강의에서 제시된 도식·수치의 버전 차이

자동 자막은 시간 탐색과 논리 전개 복원에만 사용했다. 수식·수치·논문 결론은
가능한 범위에서 원문으로 재검증했다. 질문 구간의 청중 발언, 화면의 작은 수치,
자동 자막이 불명확한 표현은 정량 claim으로 승격하지 않았다.

`[직접근거]` 자동 자막의 단순 단어 수는 8,496개로 약 134 WPM이다. 강의는
10–15분의 논증 뒤 2–7분 질문 구간으로 호흡을 낮추며, 문제 제기→메커니즘
도식→실험 그래프→한계→다음 추상화 순서를 반복한다.

AI-assisted source review를 사용했으며, 아래 `[직접근거]`, `[외부연구]`,
`[해석]` 표시는 강의 관찰, 논문 근거, 프로젝트 적용 판단을 구분한다.

## 로컬 보존

- 영상: `${HOME}/workspace/lg-ai/presentation/source/video/-Ggc37xLj_Y/-Ggc37xLj_Y.mp4`
- 자동 자막: `${HOME}/workspace/lg-ai/presentation/source/video/-Ggc37xLj_Y/-Ggc37xLj_Y.en-j3PyPqV-e1s.vtt`
- 메타데이터: `${HOME}/workspace/lg-ai/presentation/source/video/-Ggc37xLj_Y/-Ggc37xLj_Y.info.json`
- 리듬 manifest: `${HOME}/workspace/lg-ai/presentation/source/video/-Ggc37xLj_Y/rhythm-manifest.json`
- contact sheet: `${HOME}/workspace/lg-ai/presentation/source/video/-Ggc37xLj_Y/contact-sheets/`

| 파일 | SHA-256 |
|---|---|
| 영상 | `98b756b08dd5dd18fa9b067126ce7e4b33abb50e1315b4455b91b0b6be734833` |
| 자동 자막 | `06aac8e835910d682836c4ccde52e57ab06fb0cd30dac160c567173a35734639` |
| 리듬 manifest | `10665f685c4fb3eb22bdbe8a57745539b002e84902c59eccc87c75354043fbff` |

## 63분 전체 전개 지도

| 시간 | 전개 | 전달된 판단 |
|---:|---|---|
| 00:00–01:11 | pre-training·fine-tuning·inference 구분 | weight update 없이 inference budget으로 utility를 높이는 세 번째 scaling 축을 연다. |
| 01:11–04:39 | Large Language Monkeys | 같은 문제의 반복 샘플이 최소 한 번 성공할 확률, 즉 coverage를 키운다. |
| 04:44–11:20 | inference scaling law | task별 지수 감소와 전체 benchmark의 power law가 heavy-tailed 난도 분포로 함께 설명된다. |
| 11:20–12:17 | compute paradigm shift | inference는 더 이상 무시 가능한 단일 호출 비용이 아니며, long-running·offline agent의 계산 축이 된다. |
| 12:20–19:22 | generation–verification gap | 자동 검증이 없으면 majority vote와 reward model selection이 oracle coverage를 회수하지 못한다. |
| 19:24–26:55 | verifier 연구 공간 | simulation, negative filtering, ensemble, tool grounding은 verifier를 보강하지만 비용·gaming·불완전성도 만든다. |
| 26:55–31:22 | parallel 대 sequential | 독립 후보의 폭과 이전 결과를 조건으로 한 수정 깊이는 다른 search operator다. |
| 31:22–35:57 | ORM·PRM·beam search | 최종 답 점수와 중간 reasoning step 점수를 구분하고 process verifier로 분기를 잘라낸다. |
| 36:00–42:59 | compute-optimal allocation | task difficulty에 따라 폭·깊이·선택기를 바꾸는 adaptive allocation이 고정 best-of-N보다 효율적이다. |
| 43:00–45:47 | pretraining 대 inference | base policy가 답의 지지집합을 갖는 영역에서 test-time compute가 유효하며, 가장 어려운 문제에는 큰 모델이 남는다. |
| 45:47–48:53 | Archon 문제 정의 | 모델·연산자·예산·benchmark가 주어질 때 inference architecture 자체를 최적화한다. |
| 48:53–54:18 | operator catalog | generate·rank·critic·fuse·verify·unit-test 연산자를 prompt-based module로 구성한다. |
| 54:18–60:01 | layered architecture | top-k filtering, fusion, coding-specific test path, deeper composition의 task별 효과를 비교한다. |
| 60:01–63:15 | ITAS와 결과 | 제약된 탐색공간을 Bayesian optimization으로 탐색하며 general-purpose와 task-specific architecture를 분리한다. |

## 1. Repeated sampling은 정답 생성 확률을 확장한다

### Coverage와 delivered accuracy를 먼저 갈라야 한다

`[외부연구]` Large Language Monkeys가 측정한 `coverage`는 주어진 문제에 대해
생성한 후보 중 하나라도 정답인 비율이다. 이는 사용자가 실제로 받는 정답률과
같지 않다. 정답 후보가 존재해도 selector가 그것을 고르지 못할 수 있기 때문이다.

문제 `i`의 독립 1회 성공 확률을 `p_i`, 샘플 수를 `k`라고 두면 oracle이 보는
성공 확률은 다음과 같다.

```text
P_i(pass@k) = 1 - (1 - p_i)^k
```

따라서 `p_i > 0`인 문제는 같은 분포에서 독립 시도를 늘릴수록 실패 확률이
지수적으로 감소한다. 이 식은 세 가지 가정을 포함한다.

1. 샘플 간 상관이 낮다.
2. 정답이 base policy의 proposal support 안에 있다.
3. oracle 또는 충분히 강한 verifier가 정답을 식별할 수 있다.

`[외부연구]` SWE-bench Lite에서는 DeepSeek-Coder-V2-Instruct가 1회 표본의
15.9%에서 250회 표본의 56% coverage로 상승했다. 자동 검증 가능한 coding과
formal proof에서는 이 coverage를 실제 성능으로 회수할 수 있다.

`[해석]` 반복 호출은 모델을 학습시키지 않는다. 같은 policy의 확률 질량을 더
많이 탐색할 뿐이다. `p_i ≈ 0`이면 샘플 수만 늘려도 답이 나오지 않으며,
retrieval·tool·prompt·model·fine-tuning 중 proposal distribution을 바꾸는 조치가
필요하다.

### 왜 benchmark 전체에서는 power law처럼 보이는가

`[외부연구]` 개별 문제의 실패는 지수적으로 줄지만 benchmark 평균은
power law처럼 보일 수 있다. `How Do Large Language Monkeys Get Their Power
(Laws)?`는 single-attempt success probability가 heavy-tailed일 때 극소수의 매우
어려운 문제가 aggregate curve를 지배한다고 설명한다.

```text
per task:        failure_i(k) = (1 - p_i)^k
task mixture:    many moderate p_i + a long tail of near-zero p_i
aggregate:       slow power-law-like decay
```

이 관점은 평균 점수만 보는 대신 `p_i` 분포의 꼬리를 보게 한다. 쉬운 문제는
소수 샘플로 포화하고, 어려운 문제는 수백·수천 회에서도 희소한 정답 하나만
만들 수 있다. 논문은 이 분포를 이용하면 scaling exponent 예측에 필요한
inference compute를 크게 줄일 수 있다고 보고한다.

## 2. Verification이 compute를 capability로 바꾼다

### 자동 검증이 강한 도메인

강의는 다음 과제를 verifier가 강한 예로 든다.

| 도메인 | 외부 신호 | 주의점 |
|---|---|---|
| formal proof | proof checker | formalization 범위 밖의 의미 오류는 잡지 못한다. |
| code generation | executable unit tests | coverage가 불완전하면 overfit·gaming이 가능하다. |
| program translation | semantic·behavioral equivalence | 관측되지 않은 동작과 환경 차이를 분리해야 한다. |
| GPU kernel generation | reference output·correctness test | 수치 허용오차와 성능 목표를 별도 계약으로 둬야 한다. |

`[해석]` verifier의 본질은 자연어 비평이 아니라 후보와 환경 사이의 외부
상태 차이를 측정하는 데 있다. GEODE의 tool result·final state·native receipt가
text critique보다 중요한 이유와 같다.

### Generation–verification gap

`[외부연구]` 자동 verifier가 약한 수학·자연어 과제에서는 majority voting과
reward-model ranking이 수백 개 이후 포화한다. 어려운 문제의 정답이 1,000개
중 1–3개뿐이면 majority는 오답 군집을 선택한다. Reward model 역시 학습 분포와
다른 희소 정답을 낮게 평가할 수 있다.

```text
generated set ── oracle ──> coverage
       │
       └── weak selector ──> delivered accuracy < coverage
```

이 차이가 generation–verification gap이다. 후보를 더 생성하는 것은 상단 선을
올리지만, verifier가 고르지 못하면 하단 선은 움직이지 않는다.

### 강의가 열어 둔 verifier 연구 공간

19–27분 질문 구간은 다음 가능성과 한계를 함께 다룬다.

- retrieval·knowledge graph로 candidate quality와 검증 근거를 보강한다.
- 잘못됐음을 증명하기 쉬운 후보를 먼저 제거하는 negative filtering을 쓴다.
- simulator·compiler·database·domain tool을 결과 verifier로 쓴다.
- 서로 다른 약한 judge를 ensemble해 편향을 낮춘다.
- unit test를 늘리되 test coverage와 generated-test gaming을 별도 위험으로 본다.
- 모델이 답하기 전 자료를 탐색하거나 self-study하게 해 proposal support를 바꾼다.

`[해석]` 이 구간은 verifier 문제가 해결됐다는 보고가 아니다. 다음 강의가
`Robust Verification`으로 편성된 이유처럼, test-time scaling이 verifier에
의존한다는 병목을 노출한다.

## 3. Compute budget은 폭과 깊이에 다르게 쓰인다

### Parallel width

같은 입력에서 독립 또는 다양화된 후보를 여러 개 생성한다.

```text
x ─┬─> y1
   ├─> y2 ──> selector ──> y*
   ├─> y3
   └─> yN
```

- 장점: 서로 다른 해법을 탐색하고 rare success coverage를 높인다.
- 조건: 후보 다양성과 강한 verifier가 필요하다.
- 비용: N에 비례한 호출·token·latency·selection 비용이 든다.
- 실패: 상관된 후보, 약한 verifier, 답이 proposal support 밖에 있는 경우다.

Best-of-N은 후보를 N개 만든 뒤 가장 높은 점수 하나를 선택한다. `pass@N`은
oracle coverage 지표이고, `best-of-N accuracy`는 실제 selector를 거친 지표다.
둘은 같은 수치가 아니다.

### Sequential depth

이전 응답과 feedback을 다음 생성의 조건으로 넣어 proposal distribution을
업데이트한다.

```text
y0 ── feedback ──> y1 ── feedback ──> y2 ──> stop
```

- 장점: 부분적으로 맞는 답을 국소 수정하고 일관성을 유지한다.
- 조건: 오류 위치를 알려주는 process signal 또는 외부 observation이 필요하다.
- 비용: 단계가 직렬이므로 wall-clock latency가 누적된다.
- 실패: 잘못된 초안에 고착되거나 verifier 편향을 반복 강화할 수 있다.

`[해석]` 긴 CoT는 feedback 없이 token만 늘릴 수 있다. Sequential revision의
핵심은 길이가 아니라 `이전 action → 외부 observation → 다음 proposal`의
조건부 상태 전이다.

### ORM과 PRM

| 구분 | 평가 단위 | 쓰임 | 한계 |
|---|---|---|---|
| Outcome Reward Model | 최종 응답 | best-of-N의 최종 선택 | 어느 중간 단계에서 틀렸는지 알려주지 않는다. |
| Process Reward Model | reasoning step | beam 확장·가지치기 | step annotation과 domain transfer가 어렵다. |

PRM-guided beam search는 각 단계에서 자식 후보를 만들고 PRM 점수로 상위 분기를
남긴다. 이는 parallel과 sequential이 합쳐진 구조다. 동일 budget에서도 beam
width, branch factor, depth를 어떻게 배분하느냐에 따라 성능이 달라진다.

## 4. Compute-optimal scaling은 task-conditioned scheduling이다

`[외부연구]` Snell et al.은 고정된 non-trivial inference budget에서 다음 두
방식을 분석한다.

1. dense process-based verifier를 이용한 search
2. 이전 응답에 따라 response distribution을 갱신하는 adaptive revision

핵심 결과는 단일 연산자가 항상 우월하지 않다는 것이다. 효과는 prompt
difficulty에 따라 바뀌며, 난도별로 compute를 배분하는 전략은 best-of-N보다
4배 이상 효율적일 수 있다. 작은 모델이 이미 non-trivial success rate를 갖는
문제에서는 FLOP을 맞췄을 때 14배 큰 모델을 넘는 경우도 보고한다.

강의의 실험 전개는 다음과 같다.

- MATH 문제를 pass@1 추정치로 5개 난도 bin에 나눈다.
- parallel sampling, sequential revision, 두 방식의 혼합을 비교한다.
- 같은 target accuracy에 필요한 generation budget을 비교한다.
- 쉬운 문제와 어려운 문제에서 최적 allocation이 달라짐을 확인한다.
- 같은 FLOP에서 더 큰 모델과 작은 모델+test-time compute를 비교한다.

`[해석]` 실서비스의 compute policy는 `N` 하나가 아니라 다음 조건부 결정이다.

```text
π_B(x) = choose(width, depth, selector, stop)
         subject to budget, latency, risk, verifier confidence
```

이는 강의 수식의 재현이 아니라 시스템 설계용 요약이다. 입력 난도와 verifier
confidence를 추정하고, 조기 종료·수정·병렬 탐색·handoff 중 하나를 선택한다.

### 실무 의사결정 표

| 관측 상태 | 우선 compute policy | 종료 조건 |
|---|---|---|
| 쉬운 과제, verifier confidence 높음 | single pass 또는 early exit | 계약 통과 |
| 부분 정답, 수정 위치 관측 가능 | sequential repair | improvement 정체 또는 pass |
| 해법 다양성 큼, deterministic verifier 존재 | parallel sampling·beam | marginal coverage 감소 |
| 후보가 상보적이고 ranker가 강함 | rank top-k 후 fuse | fusion gain 소멸 |
| base success가 거의 0 | model·retrieval·tool 변경 | sampling 확대 금지 |
| verifier 약함, side effect 위험 높음 | 행동 축소·human handoff | authority 확인 |

### Pretraining과 test-time compute는 대체재가 아니다

`[외부연구]` 쉬운·중간 문제에서는 작은 모델에 inference compute를 더 쓰는 편이
효율적일 수 있다. 가장 어려운 문제에서는 큰 모델의 proposal distribution이
필요하다. 또한 pretraining compute는 여러 요청에 amortize되지만 test-time
compute는 각 요청마다 다시 지불한다.

따라서 비교에는 최소한 다음 네 항목이 필요하다.

- task distribution과 호출 빈도
- token·FLOP·API 비용
- latency와 병렬 실행 capacity
- verifier·selection 비용과 실패 위험

## 5. Archon은 inference operator의 조합을 탐색한다

### 입력과 출력

`[외부연구]` Archon은 다음 조건에서 inference architecture를 찾는다.

```text
target benchmark + available LLMs + call/token budget + operator catalog
                              │
                              ▼
             inference-time architecture search
                              │
                              ▼
             layered inference program on a Pareto frontier
```

Search 결과는 새로운 model weight가 아니라, 어떤 모델과 연산자를 어떤 순서와
폭으로 호출할지 정한 inference program이다.

### 연산자 카탈로그

| 연산자 | 입력→출력 | 역할 |
|---|---|---|
| Generator | prompt→candidate set | 반복 샘플링과 모델 다양성 |
| Critic | candidate→strengths·weaknesses | 후속 수정·융합 근거 생성 |
| Ranker | candidates→ordered top-k | selector budget 축소 |
| Fuser | top-k candidates→synthesized answer | 여러 후보의 상보 정보 결합 |
| Verifier | answer→validity signal | reasoning·instruction 후보 판정 |
| Unit Test Generator | coding task→tests | coding-specific evaluation surface 생성 |
| Unit Test Evaluator | candidate+tests→score | 후보가 test를 통과하는지 평가 |

이 모듈은 대부분 prompt-based component다. 별도 weight training을 전제하지 않고
기존 LLM을 호출해 역할을 수행한다.

### 49분 표를 프로젝트에 적용하는 판정 규칙

`[외부연구]` 이 일곱 이름은 모두 한 instruction에 대한 candidate response를
만들고, 비평하고, 정렬하고, 합성하거나 판정하는 inference-time contract다.
컴포넌트 이름이 비슷하다는 이유만으로 다른 제어 평면에 같은 이름을 붙이지 않는다.

| 판정 | 기준 |
|---|---|
| 직접 구현 | 입력·출력과 결정 대상이 Part 2 operator와 같은 candidate-response 평면이다. |
| 기능 대응 | 유사한 판단을 하지만 scenario·runtime state·revision 등 다른 대상을 다룬다. |
| 의도적 부재 | 독립 operator가 없거나, side effect·권한 경계 때문에 두지 않았다. |

따라서 context block을 순서대로 조립하는 `ContextAssembler`는 Fuser가 아니고,
baseline과 candidate 중 named state를 정하는 gate는 Ranker가 아니다. Tau²·Petri·
MCPMark처럼 환경을 실행한 evaluator도 Archon의 model-judged Unit Test Evaluator와
기능은 닮았지만 같은 연산 계약은 아니다.

### 왜 select가 아니라 fuse까지 필요한가

Ranker는 기존 후보 하나를 고르므로 oracle candidate ceiling을 넘을 수 없다.
Fuser는 서로 다른 후보의 부분 정보를 새 답으로 합칠 수 있어 그 ceiling을 넘을
수 있다. 강의는 모든 후보를 한 번에 fuse하기보다 ranker로 top-k를 줄인 뒤
fuse하는 편이 유리한 결과를 보여준다.

`[외부연구]` 최신 arXiv v6 abstract는 instruction following·reasoning·coding에서
Archon이 지정 baseline보다 평균 15.1% 향상했다고 적는다. 강의 화면·발화의
14.1%와 차이가 있으므로 발표에서 수치를 사용할 때는 논문 버전을 함께 표기해야
한다.

### ITAS의 search contract

Archon은 조합 폭발을 그대로 탐색하지 않는다. 강의에서 제시된 제약은 다음과
같다.

- 첫 layer는 generator다.
- 한 layer에는 한 operation type을 둔다.
- critic은 ranker·fuser보다 앞선다.
- unit-test generator 뒤에는 evaluator가 온다.
- 허용 model, layer, call budget을 미리 제한한다.

그 위에서 Bayesian optimization으로 architecture 후보를 고른다. Greedy와
random search보다 적은 평가로 좋은 조합을 찾는 것이 목적이다. Task-specific
architecture와 여러 benchmark를 평균한 general-purpose architecture를 별도로
다룬다.

### Archon 결과를 읽을 때 남겨야 할 한계

- benchmark에서 고른 architecture가 production distribution에도 최적이라는
  보장은 없다.
- 많은 layer와 endpoint는 token cost뿐 아니라 5배 이상의 latency를 만들 수
  있다.
- 7B급 모델 조합은 70B+ 조합보다 약한 결과를 보였다.
- model-generated unit-test evaluation은 실제 test execution과 같지 않다.
- train·held-out benchmark split은 architecture selection의 과적합을 줄이는
  장치이며, SIL의 mutation-hidden set과 동일한 계약이 아니다.
- Archon은 offline inference-program search다. 온라인 self-modification이나
  DGM으로 부르면 안 된다.

## 6. 강의를 하나의 시스템 모델로 합치면

강의의 네 층은 중첩되지만 같은 축이 아니다.

```text
Layer A · within trajectory
  sequential revision / repair depth

Layer B · across candidates
  parallel sampling / beam width / rank / fuse

Layer C · across inference programs
  offline search over operator composition

Orthogonal · measurement
  repeated trials for variance and confidence

Outside lecture · authority
  which evidence may change runtime, scaffold, release state
```

`[해석]` 모델 능력으로 전환되는 test-time compute는 다음 곱에 가깝다.

```text
usable capability
≈ proposal support × search allocation × verifier quality × task fit
```

어느 항 하나가 0에 가까우면 호출 수만 늘려도 실효 성능은 오르지 않는다. 특히
verifier가 약하면 compute가 reward hacking과 selection error까지 확대할 수 있다.

## 7. Eco²·GEODE runtime·Seed·SIL·Crucible의 operation map

### 먼저 한눈에 보는 분류

`[직접근거]` 현재 GEODE v1.0.13 코드 기준의 분류다. `Seed`는 SIL이 사용하는
평가 scenario를 만드는 별도 pipeline이며 SIL core와 합치지 않는다.

| Part 2 operation | GEODE runtime | Seed Scenario Generation | SIL | Crucible |
|---|---|---|---|---|
| Generator | 직접: 기본 응답·ToolCall 생성, opt-in same-task `best_of=2..4` | 직접: 독립 seed draft 생성 | 대응: cycle당 JSON mutation 1개 | 대응: producer가 committed mutation 1개 생성 |
| Fuser | 의도적 부재 | 부재 | 부재 | 부재 |
| Critic | 대응: post-tool reflection이 trajectory state를 비평 | 직접: seed별 strengths·weaknesses | 독립 operator 부재 | 대응: closed failure-code projection |
| Ranker | 직접: structured judge의 top-1 선택 | 직접: panel·pilot signal로 top-K survivor 선택 | 부재: keep/revert gate는 ranker가 아님 | 부재: paired verdict는 ranker가 아님 |
| Verifier | 직접: turn candidate 검사, 단 기본 권한은 제한 | 대응: Petri Pilot이 scenario discrimination 측정 | 대응: Petri audit와 promotion gate | 대응: trusted evaluator와 paired gate |
| Unit Test Generator | 부재 | 대응: adversarial scenario 생성 | upstream Seed에서만 제공 | 부재: task pack은 in-loop 생성하지 않고 고정 |
| Unit Test Evaluator | 대응: opt-in verifier subagent+`run_bash`, built-in test operator는 부재 | 대응: Petri Pilot | 대응: Petri audit | 대응: Tau²·MCPMark executable assay |

이 표의 `대응`은 우열이 아니라 제어 평면의 차이다. Archon은 answer delivery를
고르고, Seed는 evaluation distribution을 만들며, SIL·Crucible은 다음 revision에
쓸 named state를 고른다.

### Eco²

| 구현 | 강의의 축 | 판정 |
|---|---|---|
| Intent Router | task routing | test-time search가 아니라 입력별 graph path 선택이다. |
| LangGraph node | fixed inference operator | operator catalog의 초기 형태로 볼 수 있으나 architecture search는 아니다. |
| Send API 병렬 활성화 | task decomposition concurrency | 동일 문제 후보를 비교하지 않으므로 best-of-N이 아니다. |
| BARS judge 반복 | measurement replication | 후보 탐색이 아니라 judge 불확실성 추정이다. |

`[해석]` Eco²는 graph-owned workflow를 고정하고 입력별 경로와 병렬 실행을
선택했다. compute scaling보다 workflow routing·concurrency·observability의
초기 단계로 서술하는 편이 정확하다.

### GEODE runtime

`[직접근거]` Runtime의 직접적인 candidate path는 아래 하나다.

```text
delegate_task(best_of=2..4)
→ diversity lens를 붙인 same-task Generator N개
→ 격리된 SubResult N개
→ structured judge Ranker
→ selected top-1 SubResult
```

- `core/agent/candidate_sampling.py:53-89,161-255`가 최대 4개 lens와 structured
  winner schema를 정의한다.
- `core/agent/tool_executor/executor.py:951-988,1141-1206`가 single-task에서만
  `best_of`를 확장하고 성공 후보 중 하나를 반환한다.
- 선택 결과에는 후보와 judge failure가 남지만, 여러 결과를 새 답으로 합치는
  Fuser는 없다.

기본 `AgenticLoop`의 adapter call도 instruction·context에서 응답 또는 ToolCall을
만드는 Generator다 (`core/agent/loop/agent_loop.py:2042-2189,2643-2809`).
`best_of`는 이 Generator를 항상 확장하는 scheduler가 아니라 모델이 명시적으로
요청할 때만 동작하는 single-task option이다. 최대 4개로 clamp되고 batch form에는
적용되지 않는다.

`[직접근거]` Post-tool reflection은 observation을 압축해 hypothesis, confidence,
next-action hint를 갱신하고 낮은 confidence에서 replan pressure를 만든다
(`core/agent/loop/agent_loop.py:782-900`; `core/agent/loop/_reflection.py:304-440`).
이는 candidate별 strengths·weaknesses를 만드는 Critic이 아니라 trajectory-state
Critic에 해당하는 기능 대응이다.

`[직접근거]` Turn finalization의 `PreVerify → verifier → PostVerify → Stop`은
candidate delivery를 accept·revise·escalate하는 Verifier 대응 경로다
(`core/agent/loop/_lifecycle.py:609-742`). 다만 Archon의 2-call reasoning verifier와
달리 GEODE는 rule-based 또는 LLM judge를 선택한다. `PostVerify/Stop` 정책이
`revise` 또는 `escalate`를 반환하면 bounded continuation이나 candidate withholding이
발생하지만, built-in verify 실패만으로 항상 hard delivery gate가 되지는 않는다.
발표에서는 `검사 지점`과 `전달 차단 권한`을 분리해야 한다.

`[직접근거]` Unit Test Evaluator의 기능 대응은 `role="verifier"` subagent다. 이
role은 `run_bash`로 test·lint·smoke를 실행하고 typed `passed/checks` 결과를 돌려줄
수 있지만, runtime이 candidate마다 test를 자동 생성·실행하는 built-in operator는
아니다 (`core/agent/subagent_roles.py:101-113,172-179`;
`core/agent/sub_agent.py:825-851,1237-1264`).

`[해석]` 실행이 파일·프로세스·승인·외부 상태를 바꾸므로 completed trajectory를
Fuser로 합치는 것은 의미가 없다. Fusion을 검토한다면 side effect 이전의 plan이나
text candidate에만 둘 수 있다. Planning, tool action, permission, observation,
compaction, termination/handoff, trajectory persistence는 Part 2의 일곱 operation
밖에 있는 agent-runtime operator다.

### GEODE가 추가한 environment-runtime operation

| Operation family | 바꾸거나 남기는 객체 | 대표 구현 |
|---|---|---|
| Plan / Replan | action search path | goal decomposition, low-confidence replan |
| Act / Observe | environment state와 observation | tool batch, result, error, state update |
| Admit / Permit | effective request와 실행 권한 | schema·middleware·approval·dispatch |
| Isolate / Delegate | child session과 capability | depth·session cap, role allowlist, typed `SubResult` |
| Compact / Recover | model-visible working set | pair-safe compaction, overflow recovery |
| Stop / Handoff | terminal control ownership | bounded continuation, candidate withholding, paused session |
| Persist / Project | checkpoint·event·trajectory·evidence | mutable resume state와 immutable eval view 분리 |

이 표는 Stanford operator의 추가 구현 목록이 아니다. Candidate response가 아니라
환경 상태, 권한, context, session과 evidence를 다루기 때문에 별도 runtime taxonomy로
유지한다.

### Seed Scenario Generation

`[직접근거]` Seed pipeline은 Stanford 표와 가장 닮았지만, 답변이 아니라 평가
scenario를 탐색한다.

```text
Generator
→ Proximity Dedup
→ Critic
→ Petri Pilot
→ Ranker / Top-K
→ Evolver
→ Meta Reviewer
```

- 전체 phase order는 `geode_product/seed_generation/orchestrator.py:210-251`에 고정된다.
- `Generator`는 독립 candidate를 병렬 생성한다
  (`geode_product/seed_generation/agents/generator.py:85-224`).
- `Critic`은 각 seed의 strengths·weaknesses와 discrimination risk를 구조화한다
  (`geode_product/seed_generation/agents/critic.py:93-203`).
- `Pilot`은 Petri를 직접 호출해 dimension mean과 uncertainty를 보존한다
  (`geode_product/seed_generation/agents/pilot.py:125-260`).
- `Ranker`는 panel vote와 pilot evidence를 결합해 survivor를 고른다
  (`geode_product/seed_generation/agents/ranker.py:172-465`).

Proximity와 Meta Reviewer는 Archon 표 밖의 dataset-quality operator다. Evolver도
여러 후보를 한 답으로 합치지 않고 survivor를 개별 수정하므로 Fuser로 부르지
않는다. Unit Test Generator/Evaluator의 가장 가까운 대응은 adversarial scenario와
Petri Pilot이지만, generated code test가 아니라 safety-evaluation scenario다.

### SIL

`[직접근거]` SIL core의 한 cycle은 candidate pool을 만들지 않는다.

```text
failure evidence + bounded JSON contract
→ one scaffold mutation
→ Petri measurement
→ hard veto + targeted/full fitness gate
→ keep | revert
```

- Mutation contract는 한 cycle에 policy section 하나만 바꾼다
  (`geode_product/self_improving/loop/mutate/runner.py:451-545,1581-1660`).
- Gate는 hard contract, critical veto, margin과 targeted dimension을 확인한다
  (`geode_product/self_improving/gate.py:353-514`).
- Reject는 SoT를 직전 상태로 되돌린다
  (`geode_product/self_improving/gate.py:789-945`).

따라서 mutation LLM은 experiment-plane Generator에 대응하지만, `(1+1)` keep/revert는
Ranker가 아니라 state promotion gate다. Petri는 external Verifier/Evaluator 대응이다.
K=3은 같은 candidate의 measurement replication이고, mutation policy에 노출하지
않는 held-out은 generalization monitor다. `15→Top-5` 탐색은 SIL core가 아니라
upstream Seed Scenario Generation에 귀속한다.

### Crucible

`[직접근거]` Crucible은 one-candidate experiment protocol이다.

```text
failure codes + bounded surface + knowledge graph
→ CommandProducer / one committed mutation
→ frozen contract + trusted CommandEvaluator
→ baseline:candidate paired evidence
→ PromotionVerdict KEEP | REJECT | INVALID
→ private search-head update
```

- Contract는 mutation, task pack, measurement hash와 budget을 동결한다
  (`geode_product/crucible/contract.py:1-29`).
- Producer와 evaluator는 별도 process command다
  (`geode_product/crucible/supervisor.py:1164-1272`).
- Supervisor가 bounded loop와 private ref를 소유한다
  (`geode_product/crucible/supervisor.py:1318-1510`).
- `PromotionVerdict`와 paired decision은 release 권한 없이 KEEP·REJECT·INVALID만
  반환한다 (`geode_product/crucible/promotion.py:195-246,342-520`).

Candidate producer는 experiment-plane Generator에 대응한다. Trusted evaluator는
Unit Test Evaluator보다 executable assay에 가깝고, paired promotion decision은
Ranker가 아니다. Fuser·top-K pool·in-loop test generator는 없다. Task pack을 미리
고정하고 opaque test를 producer에서 숨기는 이유는 candidate가 평가 기준까지
바꾸는 오염을 막기 위해서다 (`geode_product/crucible/program.md:98-101,158`). 다음
cycle에 돌려주는 closed failure code는 Critic과 유사한 진단 신호지만, candidate의
장단점을 자유문으로 노출하지 않으므로 별도 feedback-projection operation으로 둔다.

## 8. Agent Workflow에 적용할 범위

### 범위 A · Runtime compute controller

Trajectory에서 difficulty, verifier confidence, tool error, latency, cost를 읽고
다음 action budget을 선택한다.

```text
task admission
→ single pass
→ verify
→ early exit | sequential repair | parallel branch | handoff
```

필요 계약은 `compute_budget`, `branch_id`, `parent_action_id`, `verifier_id`,
`selection_reason`, `stop_reason`이다. 이 값이 없으면 최종 점수가 같아도 어떤
compute policy가 효과적이었는지 재구성할 수 없다.

### 범위 B · Verifier-aware scheduler

Verifier confidence가 낮은 과제에서는 width를 늘리지 않는다. Deterministic
tool·state assertion이 있는 과제만 best-of-N·beam을 허용하고, 자연어 judge만
있는 고위험 mutation은 human handoff 또는 제한된 action surface로 보낸다.

### 범위 C · Offline inference-program search

Archon의 문법을 그대로 구현할 필요는 없다. GEODE가 이미 가진 generator,
delegate, verifier, replan, tool, skill, model route를 제한된 catalog로 정의하고,
task pack에서 `fixed budget → measure → select`를 수행할 수 있다. Runtime source
자유 수정이 아니라 선언형 policy/scaffold만 후보로 두는 현재 방향과 맞는다.

### 범위 D · Evidence와 policy learning

```text
trajectory
→ difficulty / failure cluster
→ compute-policy candidate
→ paired replay
→ verifier + held-out
→ keep / revert / handoff
```

이때 trajectory는 곧바로 training data가 아니다. Action identity, reward 품질,
privacy, duplication, evaluator leakage를 검사한 뒤에야 supervised·preference·RL
데이터 후보가 된다.

### 범위 E · 비용과 권한을 함께 최적화

Enterprise agent의 objective는 accuracy 하나가 아니다.

```text
maximize task utility
subject to cost + latency + risk + authority + auditability
```

검색 폭이 커질수록 tool side effect와 승인 요청도 늘어난다. 따라서 compute
controller는 model 호출 수뿐 아니라 action budget, read/write capability,
approval boundary, terminal handoff를 함께 관리해야 한다.

## 9. 현재 덱 반영 후보

이번 operator map은 새 장을 추가하기보다 기존 화면 30을 교체하는 데 사용한다.
화면 16의 subagent admission과 화면 31–34의 SIL·Crucible 상세를 반복하지 않고,
서로 다른 decision plane만 한 장에서 고정한다.

| 우선순위 | 화면 | 적용 |
|---:|---:|---|
| P0 | 09 | observe→verify→replan을 `sequential repair depth`로 명명하고 feedback 없는 long CoT와 구분한다. |
| P0 | 21 | oracle coverage와 delivered correctness 사이의 verifier gap을 한 그래프로 표현한다. |
| P0 | 30 | candidate-response inference, scenario search, revision promotion을 세 개 lane으로 분리한다. |
| P1 | 31 | Seed 15→Top-5를 exploration width, SIL mutation을 cross-run scaffold search로 분리한다. |
| P1 | 32–33 | held-out을 mutation policy에 비노출된 monitor로 두고 selection set과 권한을 분리한다. |
| P1 | 37 | Agent Workflow 기여를 `task-conditioned compute + evidence-preserving runtime`으로 압축한다. |

화면 30의 head message 후보는 다음이다.

> **후보는 고르고, 실행은 검증하며, revision은 gate만 바꿨습니다**

본문 계약은 다음 한 문장으로 닫는다.

> Runtime은 응답과 action trajectory를, Seed·SIL은 scenario와 JSON scaffold를,
> Crucible은 Git revision을 다룹니다. 같은 Generate·Evaluate·Select라도 객체와
> 피드백 가시성, write authority가 다르므로 서로 다른 operation contract로
> 분리했습니다.

시각화는 같은 폭의 세 horizontal lane으로 고정한다.

```text
RUNTIME          Generate → Act/Observe → Reflect → Verify → Replan/Stop
                 └ best_of N=2..4 → Rank top-1 ─┘          answer delivery

SEED + SIL       Seed Generate → Dedup → Critic/Pilot → Rank top-K → scenario bank
                 one JSON mutation → Petri → Gate → keep/revert SoT

CRUCIBLE         failure projection → one Git revision → paired τ² → Normalize
                 → KEEP/REJECT/INVALID → private search ref
```

각 lane 왼쪽에는 `search object`, 오른쪽에는 `authority`를 고정하고 중앙에 operation만
놓는다. 첫 lane에는 `FUSER 없음 · completed side effects는 합성하지 않음`을 작은
경계 주석으로 둔다. Fusion을 추가한다면 plan-before-act 단계라는 위치만 표시하고
구현 claim은 하지 않는다. Tool permission·compaction·hook·persistence의 상세는
화면 9–19에서 설명하므로 화면 30에는 operation family 이름만 둔다.

### 결과 그래프의 발표 문법

`[외부연구]` 강의의 결과 장은 그래프를 먼저 놓고 제목에 해석을 적는 구성이 아니다.
제목이 먼저 한 개의 비교 판정을 내리고, 두 패널은 같은 종속변수와 비교군을 유지한
채 자원 축만 바꾼다. 고정 모델 성능은 옅은 수평선으로 두고, 발표는 random control
→selector→fuser→composition 순으로 곡선의 교차·포화·한계효용을 읽는다. 따라서
선은 시간의 흐름을 꾸미는 장식이 아니라 각 x 조건에서 실제로 측정된 결과여야 한다.

`[해석]` GEODE 아티팩트에도 같은 시각 문법을 적용할 수 있지만, 현재 full-cycle은
budget intervention 실험이 아니다. 관측된 실행 길이를 hard budget 아래의 재실행
성능처럼 부르면 안 된다. 지금 만들 수 있는 것은 `compute-scaling curve`가 아니라
`observed completion-cost profile`이다.

### 현재 데이터에서 채택할 주제

> **Retail과 Telecom은 모두 79/114였지만, 성공 경로의 shared-world
> interaction p90은 11회와 38회였습니다**

`[직접근거]` `geode-eval-artifacts`의 GPT-5.4 subscription/high Tau2 full-cycle
`results.json`을 successful trajectory만 대상으로 nearest-rank p90으로 다시
집계했다. 두 도메인은 각각 114개 중 79개를 완료했다. 후보 agent가 요청한 tool
action p90은 Retail 11회, Telecom 12회로 비슷했다. 반면 user simulator의 tool
action까지 포함한 shared-world tool event p90은 11회와 38회, wall time p90은
143.8초와 542.3초였다. 이는 Telecom의 dual-control interaction이 더 길었다는
관측이지, GEODE policy가 3.5배 비효율적이라는 판정이 아니다.

근거 파일은 다음 두 native receipt다.

- `tau2/simulations/geode-gpt54-high-22789ee2-geode-user-retail-base-full-transport-retry1-20260803/results.json`
- `tau2/simulations/geode-gpt54-high-22789ee2-geode-user-telecom-base-full-transport-retry1-20260803/results.json`

이 장은 현재 Tau2 full-cycle 결과 장 직후에 둔다. 두 패널은 같은 y축
`114개 중 관측된 누적 성공 비율`과 같은 Retail·Telecom series를 쓴다.

```text
LEFT · AGENT ACTION PROFILE          RIGHT · SHARED-WORLD INTERACTION PROFILE
y: cumulative successful tasks      y: cumulative successful tasks
x: assistant-owned tool actions     x: all tool events

Retail p90 11 ─ Telecom p90 12      Retail p90 11 ─ Telecom p90 38
                                     wall time 144 s ─ 542 s
```

최대 y는 두 곡선 모두 `79/114 = 0.693`으로 닫는다. 왼쪽 곡선은 거의 겹치고,
오른쪽 Telecom 곡선만 오른쪽으로 이동해야 한다. 범례 대신 선 끝에 도메인을 직접
표기하고 p90 두 점만 강조한다. 하단에는 다음 한계를 고정한다.

> `Observed final-attempt profile · not pass@budget · no hard-cap rerun`

`[해석]` 이 장이 지지하는 결정은 `더 많은 compute`가 아니다. Aggregate task
success가 같아도 environment ownership과 interaction depth가 다르므로, runtime
budget·termination·handoff를 task-conditioned policy로 관리하고 score와 함께
action ownership을 보존해야 한다는 것이다. 이 결론이 다음 External Loop 장의
`native outcome + canonical behavior` 결속으로 이어진다.

### 보류할 주제

| 후보 | 판정 | 이유 |
|---|---|---|
| Telecom success/failure tail | Q&A 또는 후속 장 | 실패 p90과 `MAX_STEPS`는 조기 handoff 가설을 만들지만, 종료 정책을 바꾼 대조실험은 아니다. |
| SIL selection 대 held-out | 후속 실험 | cycle별 동일 ruler와 완전한 candidate lineage를 먼저 고정해야 한다. |
| Crucible 42 attempts→verdict | 기존 gate 장의 수치 보강 | funnel·verdict composition에 적합하며 sample-scaling line에는 맞지 않는다. |
| Petri 13-scenario matrix | 기존 heatmap 유지 | dimension·scenario가 달라 누적 sample curve로 연결하면 IID 반복처럼 오인된다. |
| 과거 버전 점수 연결 | 금지 | model route·runtime revision·assay가 달라 하나의 발전 곡선이 아니다. |

실제 Stanford식 intervention curve가 필요하면 같은 task stratum·model·revision·
evaluator를 고정하고 action budget 또는 candidate width만 바꿔 다시 실행한다. 현재
아티팩트만으로 그 실험을 수행한 것처럼 보이는 선은 만들지 않는다.

### 현재 덱에서 빠진 서술

1. 화면 16과 30 모두 `best_of`가 Generator와 top-1 Ranker의 조합이라는 이름이 없다.
2. 화면 30은 `delegate_task`와 Seed Top-K를 한 candidate policy에 넣어 answer 선택과
   evaluation-distribution 정제를 혼동한다.
3. SIL·Crucible gate를 Ranker나 Verifier로 오해하지 않게 `named-state authority`를
   입력·출력과 함께 보여주지 않는다.
4. model-judged verification과 Petri·Tau²·MCPMark의 executable/environment evidence
   차이가 한눈에 드러나지 않는다.
5. Fuser 부재와 이유가 없다. 이미 실행된 trajectory는 결합할 수 없고, fusion은
   side effect 이전 plan/text candidate에만 허용할 수 있다.
6. 호출 수, candidate 수, wall-time, action budget 중 어떤 budget을 썼는지 operator별
   비용 단위가 빠져 있다.
7. 현재 Verifier를 hard gate로 읽을 위험이 있다. Built-in verify와
   `PostVerify/Stop`이 가진 revise·escalate authority를 분리해 말해야 한다.
8. `best_of`가 opt-in·single-task·최대 4개이고, 네 고정 lens가 통계적 독립성을
   보장하지 않는다는 구현 한계가 대본에 없다.

별도 장은 만들지 않는다. 이 여덟 누락은 화면 30의 lane label·boundary note와 발표
대본으로 설명할 수 있고, 새 장을 추가하면 화면 16·31–34와 중복된다.

## 10. 발표에서 지켜야 할 용어

### 사용할 표현

- parallel candidate width
- sequential repair depth
- test-time compute allocation
- verifier-aware scheduling
- generation–verification gap
- inference-program search
- measurement replication
- external promotion authority

### 사용하지 않을 표현

- 긴 CoT 전체를 test-time scaling이라고 부르지 않는다.
- Send API 동시 실행을 parallel sampling이라고 부르지 않는다.
- K=3 반복 측정을 best-of-3이라고 부르지 않는다.
- inference compute가 pretraining을 대체한다고 말하지 않는다.
- Archon을 self-improving runtime 또는 DGM이라고 부르지 않는다.
- generated unit-test evaluation을 deterministic test execution이라고 부르지 않는다.
- 강의의 held-out을 SIL held-out과 같은 계약이라고 말하지 않는다.
- GEODE가 Archon을 구현했다고 말하지 않는다.

## 11. 발표용 90초 해설 초안

> Test-time compute를 처음에는 호출 수의 문제로 봤습니다. Stanford 강의는 이
> 관점을 네 층으로 가릅니다. 같은 문제의 후보를 넓히는 parallel width, 외부
> feedback으로 한 후보를 고치는 sequential depth, 후보를 실제 성능으로 바꾸는
> verifier, 그리고 이 연산자의 조합 자체를 찾는 inference-program search입니다.
>
> 중요한 건 compute가 아니라 변환 조건입니다. 정답 후보가 한 번이라도 생성되는
> coverage는 샘플 수와 함께 오르지만, verifier가 희소한 정답을 찾지 못하면 실제
> 전달 성능은 포화합니다. 그래서 GEODE에서는 긴 추론보다 observe, verify,
> replan을 연결했고, SIL에서는 seed 탐색 폭과 K=3 반복 측정, held-out monitor,
> 승격 권한을 서로 다른 평면으로 분리했습니다.
>
> 다음 단계는 더 많은 호출이 아닙니다. 과제 난도, verifier confidence, 비용,
> side-effect risk를 trajectory에서 읽고 single pass, repair, parallel search,
> handoff를 선택하는 compute policy입니다. 그 정책과 결과를 같은 evidence contract로
> 남겨야 새 모델과 새 workflow도 동일 기준으로 비교하고 승격할 수 있습니다.

## 12. 미해결 연구 질문

- Runtime에서 task difficulty를 leakage 없이 어떻게 추정할 것인가.
- Branch 간 상관을 측정해 nominal N과 effective sample size를 어떻게 구분할 것인가.
- Verifier confidence와 false-positive cost를 action risk에 따라 어떻게 보정할 것인가.
- Sequential repair의 improvement plateau를 어떤 terminal event로 판정할 것인가.
- Offline architecture search가 benchmark-specific overfit이 되지 않게 어떤
  held-out·sealed protocol을 둘 것인가.
- Text candidate가 아닌 state-changing tool trajectory를 fuse하거나 rank할 때
  side effect를 어떻게 격리할 것인가.
- Compute policy provenance를 session·trajectory·eval artifact에 어떤 identity로
  결속할 것인가.

## 1차 원문

- [Stanford CS329A Self-Improving AI Agents](https://cs329a.stanford.edu/)
- [Large Language Monkeys: Scaling Inference Compute with Repeated Sampling](https://arxiv.org/abs/2407.21787)
- [How Do Large Language Monkeys Get Their Power (Laws)?](https://arxiv.org/abs/2502.17578)
- [Scaling LLM Test-Time Compute Optimally can be More Effective than Scaling Model Parameters](https://arxiv.org/abs/2408.03314)
- [Archon: An Architecture Search Framework for Inference-Time Techniques](https://arxiv.org/abs/2409.15254)
