<p align="center">
  <img src="assets/geodi-dot.svg" alt="GEODE의 도트 마스코트 Geodi" width="240" />
</p>

<p align="center">
  <a href="https://github.com/mangowhoiscloud/geode/actions/workflows/ci.yml"><img src="https://img.shields.io/github/actions/workflow/status/mangowhoiscloud/geode/ci.yml?style=flat-square&label=ci" alt="CI"></a>
  <a href="https://github.com/mangowhoiscloud/geode/releases/latest"><img src="https://img.shields.io/github/v/release/mangowhoiscloud/geode?style=flat-square&label=release" alt="최신 릴리스"></a>
</p>

<p align="center">
  <a href="https://mangowhoiscloud.github.io/geode/docs/">문서</a> ·
  <a href="https://github.com/mangowhoiscloud/geode-eval-artifacts">평가 아티팩트</a> ·
  <a href="README.md">English</a>
</p>

# GEODE v1.0.30 — Autonomous Agent Runtime + Evaluation Substrate

GEODE는 리서치, 파일 작업, 예약 작업을 위한 Python 에이전트 런타임입니다.
에이전트는 도구를 호출하고 결과를 읽으며 작업을 이어갑니다.
데몬이 실행과 세션을 관리하고, 터미널 클라이언트는 IPC로 연결됩니다.
MCP 서버와 메시징 연동으로 도구와 대화 채널을 확장할 수 있습니다.

같은 배포판에 평가 도구와 실험적인 스캐폴드 탐색도 포함합니다.
각 구성요소의 책임은 [패키지 구성](#패키지-구성)에서 설명합니다.

## 빠른 시작

macOS 또는 Linux에서 Python 3.12 이상과
[uv](https://docs.astral.sh/uv/getting-started/installation/)를 준비하세요.
Git은 소스를 받아 개발할 때만 필요합니다.

```bash
uv tool install geode-agent
geode version
geode setup
geode
```

설치할 패키지 이름은 **`geode-agent`**, 실행 명령은 **`geode`**입니다.
설정 마법사에서 ChatGPT 로그인, API 키 입력, dry-run 중 하나를 선택합니다.
터미널 클라이언트는 필요할 때 데몬을 시작합니다.

세션에서 다음과 같이 요청해 보세요.

```text
이 디렉터리의 문서를 요약하고 근거가 되는 파일을 표시해줘.
두 설계안을 비교하고 아직 결정하지 않은 사항을 정리해줘.
```

웹 접근, 메시징 등 외부 연동에는 별도의 설정과 권한이 필요합니다.
자세한 내용은 [설정 가이드](docs/setup.ko.md)를 참고하세요.

### 인증과 모델 선택

GEODE 세션 안에서 사용합니다.

| 명령 | 용도 |
|---|---|
| `/login openai` | 이용 권한이 있는 ChatGPT 계정으로 기기 코드 로그인 |
| `/login anthropic` | 화면에 표시되지 않는 입력창으로 Anthropic API 키 등록 |
| `/login add` | 제공자와 계정 유형을 선택해 자격 증명 추가 |
| `/login status` | 설정된 인증 상태 확인 |
| `/model` | 사용 가능한 모델과 추론 노력(effort) 선택 |

OpenAI 구독 경로는 프로세스 내부의 OAuth 어댑터로 Codex 백엔드를 호출합니다.
기존 Codex 자격 증명도 읽을 수 있으며, 추론을 위해 Codex CLI를 실행하지는
않습니다. 계정별 이용 권한과 사용 한도는 그대로 적용됩니다.
Anthropic은 API 키를 사용하며, 이전 Claude CLI 구독 경로는 지원하지 않습니다.

API 키 경로는 Anthropic, OpenAI, OpenRouter, Z.AI를 지원합니다.
키를 명령이나 대화에 적는 대신 터미널의 숨김 입력을 사용하세요.
GEODE가 관리하는 제공자 키와 OAuth 계정은 `~/.geode/auth.toml`에 저장합니다.
이 파일은 소유자 전용 권한을 적용한 평문 파일이며 OS 키체인은 아닙니다.
외부에서 주입한 환경변수 자격 증명도 사용할 수 있습니다.

소스 선택, 자격 증명 우선순위, 계정 라우팅은
[제공자 설정](https://mangowhoiscloud.github.io/geode/docs/run/providers/)과
[인증 가이드](https://mangowhoiscloud.github.io/geode/docs/ops/oauth/)를 참고하세요.

### Jev 판정 선택

v1.0.30은 TypeSafe 또는 OpenRouter를 통한 Jev 판정을 지원합니다.
사용할 자격 증명을 설정한 뒤 판정 경로를 명시적으로 선택합니다.

```text
/model judgment typesafe
/model judgment openrouter
/model judgment llm
```

사용할 경로 하나를 선택하며, `llm`은 LLM 판정 경로로 돌아갑니다.
판정 경로를 바꿔도 생성 모델과 effort는 유지됩니다. 키 등록만으로 Jev가
활성화되지는 않습니다. Reflection은 런타임 보호 조건에 따라 도구 결과를
받은 라운드와 최종 응답 전에 수행합니다. 자격 증명, 사용량, 판정 범위는
[판정 설정](https://mangowhoiscloud.github.io/geode/docs/config/reference/)과
[검증·평가 가이드](https://mangowhoiscloud.github.io/geode/docs/verification/evaluation/)를
참고하세요.

## 설정과 운영

| 위치 | 역할 |
|---|---|
| `~/.geode/auth.toml` | GEODE가 관리하는 제공자 자격 증명과 계정 정보 |
| `~/.geode/.env` | 선택적으로 사용하는 환경변수 자격 증명과 연동 시크릿 |
| `~/.geode/config.toml` | 사용자 공통 동작 기본값 |
| `./.geode/config.toml` | 프로젝트별 동작 설정 |
| `~/.geode/` | 런타임 상태, 세션, 진단 기록, 비공개 산출물 |

프로젝트 동작 설정은 사용자 기본값보다 우선합니다. 자격 증명은 선택한
모델·소스·계정에 따라서도 결정되므로 모든 설정을 하나의 우선순위 목록으로
설명할 수는 없습니다. Google Workspace OAuth는 별도의
[계정·키링 저장소](https://mangowhoiscloud.github.io/geode/docs/run/google-workspace/)를
사용합니다.

```bash
geode about                    # 실효 모델, 경로, 데몬 상태
geode doctor                   # 로컬 설정과 자격 증명 가용성 진단
geode config explain MODEL     # 동작 설정을 결정한 층 확인
geode update --dry-run          # 업데이트 경로 미리 보기
geode update                   # 레지스트리 설치: 호환되는 최신 패치
geode update --latest          # 레지스트리 설치: 마이너·메이저 업데이트 허용
```

소스 체크아웃과 별도 옵션을 사용한 uv 설치는 처리 방식이 다릅니다.
[설치·업데이트 계약](docs/architecture/immutable-distribution-lifecycle.md)을
참고하세요. 런타임 데이터를 남기고 uv로 설치한 CLI만 삭제하려면
`uv tool uninstall geode-agent`를 사용합니다. `geode uninstall`은 런타임
데이터도 삭제하므로 먼저 `geode uninstall --dry-run`으로 범위를 확인하세요.

비용 가드는 관측된 사용량과 설정된 요율을 사용합니다. 제공자의 실제 청구액을
제한하는 장치는 아닙니다. 진행 중인 호출이 임계값을 넘길 수 있고, 사용량을
받지 못한 호출의 비용을 0으로 간주하지도 않습니다.
[사용량 회계](docs/architecture/usage-accounting.md)에서 자세히 설명합니다.

### 문제가 생기면

- **명령을 찾을 수 없음:** `uv tool dir --bin`과 셸의 PATH를 확인합니다.
- **인증 실패:** `/login status`를 확인한 뒤 `/login`으로 다시 로그인하거나
  키를 교체합니다. 자격 증명을 진단 자료나 이슈에 붙여넣지 마세요.
- **모델·설정이 예상과 다름:** `geode about`, `/model`,
  `geode config explain MODEL`을 확인합니다. 실행 중인 세션은 적용된 설정을
  유지합니다.
- **데몬 연결 실패:** `geode doctor`, 설정된 Unix 소켓,
  `~/.geode/logs/serve.log`를 확인합니다. 다른 세션이 사용 중일 수 있으므로
  종료하기 전에 프로세스의 소유자를 확인합니다.

## 연동

**메시징.** `geode serve`는 데몬과 설정된 Slack·Discord·Telegram·스케줄러
서비스를 실행합니다. 채널 자격 증명과 연결 대상은 별도로 설정합니다.
Gateway 세션의 원격 컴퓨터 사용은 명시적으로 허용하기 전까지 비활성화됩니다.
[Gateway 설정](docs/setup.md#slack-gateway)을 참고하세요.

**MCP 클라이언트.** GEODE의 MCP 설정으로 외부 도구 서버를 연결합니다.
[MCP 가이드](https://mangowhoiscloud.github.io/geode/docs/runtime/tools/mcp/)를
참고하세요.

**MCP 서버.** MCP 클라이언트의 stdio 실행 명령을 `geode-mcp`로 설정합니다.
코어 서버는 `run_agent`, `query_memory`, `get_health`를 제공합니다.
HTTP 연결은 `geode-mcp --http`를 사용하며 `GEODE_MCP_TOKEN`으로 bearer 인증을
설정합니다. 루프백 외 주소에 토큰 없이 바인딩하면 시작을 거부합니다.
이 엔드포인트는 에이전트 도구를 실행할 수 있으므로 접근 권한은 실행 권한을
포함합니다. 현재 전송 계약은 [서버 구현](core/mcp_server.py)에서 확인할 수 있습니다.

## 패키지 구성

| 패키지 | 역할 | 명령 |
|---|---|---|
| `core/` | 에이전트 런타임, 터미널 클라이언트, 데몬, 도구, 메모리, MCP | `geode`, `geode-mcp` |
| `evals/` | 감사, 벤치마크 어댑터, 평가 증거 | `geode-eval` |
| `evolve/` | 실험적 스캐폴드 탐색과 Crucible | `geode-evolve` |

설치된 코드·번들 자산은 변경 가능한 상태와 분리합니다.
스캐폴드를 수정하고 승격하려면 쓰기 가능한 GEODE Git 체크아웃이 필요합니다.

SIL과 Crucible은 **실험 단계**입니다. 모델 가중치를 바꾸지 않고 프롬프트,
도구 등 스캐폴드의 변경을 평가합니다. 안전성 감사와 벤치마크는 서로 다른
수락 기준을 사용합니다. 공개 기록은 아직 지속적인 자기개선을 입증하지 않습니다.
[Self-improving 허브](https://mangowhoiscloud.github.io/geode/self-improving/)와
[캠페인 가이드](docs/self-improving/campaign-quick-start.md)에서 시작할 수 있습니다.

## 평가 증거

결과를 읽을 때 소스 리비전, 과제 집합, 모델 경로, effort, 제한 시간, 시도
이력을 함께 확인해야 합니다. 런타임의 완료 메시지, 모델의 판단, 벤치마크
verifier의 결과는 서로 다른 관측입니다.

| 트랙 | 확인할 범위 |
|---|---|
| [Tau2](https://mangowhoiscloud.github.io/geode/docs/benchmarks/tau2/) | Native-user·GEODE-user 구분, 실행 완결성, 사용 한도 영향 |
| [MCPMark](https://mangowhoiscloud.github.io/geode/docs/benchmarks/mcpmark/) | 포함된 서비스, 동일 조건의 비교 관측, full-Verified 한계 |
| [Terminal-Bench 2.1](https://mangowhoiscloud.github.io/geode/docs/benchmarks/terminal-bench/) | 특정 계정의 단일 과제 스모크와 전체 과제 집합 결과의 차이 |
| [Jev 판정](https://mangowhoiscloud.github.io/geode/docs/verification/evaluation/) | 판정 품질, 완료 판단 시점, 전체 과제 수행 결과 |

실행 기록과 개인정보 검토를 통과한 trajectory는
[평가 아티팩트 저장소](https://github.com/mangowhoiscloud/geode-eval-artifacts)에
공개합니다. 이 트랙들을 하나의 제품 점수나 프론티어 하네스 순위로 합치지 않습니다.

## 개발

```bash
git clone https://github.com/mangowhoiscloud/geode.git
cd geode
uv sync --locked
uv run geode version
```

기여자 규칙은 [AGENTS.md](AGENTS.md), 개발·PR 안내는
[CONTRIBUTING.md](CONTRIBUTING.md)를 참고하세요.
[워크플로](docs/workflow.md)가 검증과 통합 절차를,
[아키텍처 문서](docs/architecture/)가 각 구성요소의 계약을 관리합니다.

개발 지침인 `.agents/skills/`와 런타임 스킬인 `.geode/skills/`는 별개입니다.
런타임 프롬프트의 지침도 실행 코드의 권한 검사를 대체하지 않습니다.
[프롬프트 조립](https://mangowhoiscloud.github.io/geode/docs/runtime/llm/prompt-system/)에서
적용 경로를 확인할 수 있습니다.

[변경 이력](CHANGELOG.md) · [보안 정책](SECURITY.md) · [Apache 2.0 라이선스](LICENSE)
