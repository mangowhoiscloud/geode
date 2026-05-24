<p align="center">
  <img src="assets/geode-mascot.png" alt="GEODE — Autonomous Execution Harness" width="360" />
</p>

<p align="center">
  <img src="https://img.shields.io/badge/while(tool__use)-agentic%20loop-1e293b?style=flat-square" alt="while(tool_use)">
  <img src="https://img.shields.io/badge/57%20agentic%20tools-MCP%20native-1e293b?style=flat-square" alt="57 Agentic Tools">
  <img src="https://img.shields.io/badge/LangGraph-StateGraph-1e293b?style=flat-square" alt="LangGraph">
  <a href="https://github.com/mangowhoiscloud/geode/actions"><img src="https://img.shields.io/github/actions/workflow/status/mangowhoiscloud/geode/ci.yml?style=flat-square&label=ci&logo=github&logoColor=white" alt="CI"></a>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Anthropic-Opus_4.7-cc785c?style=flat-square&logo=anthropic&logoColor=white" alt="Anthropic Opus 4.7">
  <img src="https://img.shields.io/badge/OpenAI-GPT--5.5-412991?style=flat-square&logo=openai&logoColor=white" alt="OpenAI GPT-5.5">
  <img src="https://img.shields.io/badge/ZhipuAI-GLM--5.1-1a73e8?style=flat-square" alt="ZhipuAI GLM-5.1">
  <img src="https://img.shields.io/badge/+10_fallback-models-555?style=flat-square" alt="+10 fallback models">
</p>

[English](README.md)

# GEODE v0.99.51 — Long-running Autonomous Execution Harness

탐색적 리서치와 시그널 예측을 위한 범용 자율 에이전트. 자연어로 물으면 GEODE 가 계획을 세우고, 도구를 호출해, 결과를 보고합니다. 1회성 프롬프트도, 장시간 세션도 동일하게.

> **ChatGPT Plus, Pro, Business, Edu, Enterprise 결제 중이신가요?** 그 구독을 GEODE 가 그대로 씁니다. API 키 필요 없습니다. [구독 setup ↓](#path-a--chatgpt-구독-openai-사용자에게-권장)
>
> **Claude Pro / Max 사용자라면** — 2026-01-09 발효된 Anthropic 약관이 Claude Code OAuth 토큰의 외부 도구 재사용을 금지합니다. 그래서 GEODE 는 그 토큰을 읽지 않습니다. 대신 Anthropic API 키 (Path B) 를 쓰시면 됩니다. Console 계정은 같고, 신규 가입자는 $5 무료 크레딧을 받습니다.

---

## 무엇을 시킬 수 있나요

복붙해서 바로 시도해보세요:

```
"이번 달 arXiv 의 최신 RAG 논문 요약해줘"
"내 프로필에 맞는 LinkedIn 채용 공고 찾아서 우선순위 매겨줘"
"평일 오전 9시 스탠드업 알림 만들어줘"
"hacker news 에서 LangGraph 관련 글 모니터링하다가 Slack 으로 DM 보내줘"
"코드 리뷰용으로 gpt-5.5 와 claude-opus-4.7 비교해줘"
```

GEODE 는 적합한 도구(웹 검색, 파일 작업, MCP 서버, 서브에이전트)를 골라 실행한 뒤, 출처와 비용까지 포함해 답을 보여줍니다.

---

## 5분 setup

### 사전 준비물

<details>
<summary><strong>이게 뭔지 모르세요?</strong> 클릭하면 1줄 설명이 나옵니다.</summary>

- **Python 3.12 이상** — GEODE 가 작성된 언어. 대부분의 노트북엔 충분히 최신 버전이 안 깔려 있습니다. [python.org/downloads](https://www.python.org/downloads/) 에서 macOS 또는 Windows 인스톨러 다운로드 후 설치.
- **Git** — GitHub 에서 GEODE 소스를 복사해오는 도구. Mac 은 `xcode-select --install`. Windows 는 [git-scm.com](https://git-scm.com/) 인스톨러.
- **uv** — 빠른 Python 패키지 매니저(pip 대체). 아래 `curl` 명령을 터미널/PowerShell 에 그대로 붙여넣기.

이 중 하나라도 안 되면 아래 [트러블슈팅](#트러블슈팅) 참고.
</details>

| 도구 | 설치 | 확인 |
|------|------|------|
| Python 3.12+ | [python.org/downloads](https://www.python.org/downloads/) | `python3 --version` |
| Git | [git-scm.com](https://git-scm.com/) | `git --version` |
| uv | `curl -LsSf https://astral.sh/uv/install.sh \| sh` | `uv --version` |

### 1단계 — GEODE 설치

GEODE 의 PyPI 배포명은 **`geode-agent`** 입니다. 설치되는 실행 명령은 **`geode`** 입니다.

```bash
uv tool install geode-agent
geode version
```

현재 릴리즈가 아직 PyPI 에 공개되지 않았거나 GEODE 자체를 개발하려면 소스 체크아웃으로 설치하세요:

```bash
git clone https://github.com/mangowhoiscloud/geode.git
cd geode
uv sync                              # 의존성 설치 (~30초)
uv tool install -e . --force         # `geode` 를 어디서나 쓸 수 있게 등록
```

### 2단계 — setup wizard 실행

```bash
geode setup
```

Wizard 가 세 가지 경로를 제시합니다: ChatGPT 구독 (이미 `codex auth login` 했다면 자동 감지), API 키 (붙여넣기), dry-run 으로 일단 둘러보기. 본인에 맞는 걸 고르면 됩니다.

GEODE 설치 전에 이미 `codex auth login` 을 해뒀다면 이 단계 건너뛰어도 됩니다 — 다음 `geode` 실행 시 토큰을 자동 감지하고 바로 시작합니다.

### 3단계 — 경로별 수동 안내 (참고용)

위 wizard 가 아래 내용을 다 처리합니다. 이 섹션은 각 경로가 실제로 무엇을 하는지 알고 싶을 때 참고하세요.

---

#### Path A — ChatGPT 구독 (OpenAI 사용자에게 권장)

Codex CLI 로 한 번 로그인하면, GEODE 가 `~/.codex/auth.json` 의 토큰을 그대로 가져다 씁니다. 비용은 구독으로 결제되고, 추가로 설정할 게 없습니다.

```bash
brew install codex                    # macOS  (또는: npm install -g @openai/codex)
codex auth login                      # 브라우저가 열립니다. ChatGPT 계정으로 로그인.
geode                                 # 끝. GEODE 가 토큰을 자동으로 찾습니다.
```

**지원 플랜** ([Codex CLI 공식 문서](https://developers.openai.com/codex/cli/) 기준): Plus, Pro, Business, Edu, Enterprise.

**할당량** (OpenAI 공시 기준, 5시간 윈도): Plus 는 약 15–80 메시지, Pro 20x 는 최대 1,600 메시지. Edu / Enterprise 는 고정 한도 없이 워크스페이스 크레딧으로 정산됩니다. 이 두 플랜은 워크스페이스 관리자가 "Allow members to use Codex Local" 을 켜야 사인인이 작동합니다.

**참고할 점**:
- **gpt-5.5 는 구독 전용입니다.** API 키 (Path B) 는 gpt-5.4 까지만 가능. 5.5 가 필요하면 ChatGPT 구독이 필요합니다.
- **ChatGPT Team 은 현재 Codex CLI 미지원**. Team 사용자는 Path B 로 가세요.
- **Free / Go** 는 OpenAI 가격 페이지엔 있지만 CLI README 엔 없습니다. 동작하면 다행, 보장은 안 합니다.

토큰 만료가 임박하면 GEODE 가 알아서 갱신합니다 (만료 120초 전 + 401 재시도). 사용자가 따로 신경 쓸 일은 없습니다.

**Claude Pro 가 Path A 가 아닌 이유.** 2026-01-09 부로 Anthropic 약관이 바뀌어, 외부 도구가 Claude Code OAuth 토큰을 재사용할 수 없습니다. GEODE 는 사용자 계정 보호를 위해 `~/.claude/.credentials.json` 을 읽지 않습니다. Anthropic 은 API 키 (Path B) 만 받습니다. ([Reference](https://www.theregister.com/2026/02/20/anthropic_clarifies_ban_third_party_claude_access))

---

#### Path B — API 키 (사용량 과금)

Anthropic 사용자 (Claude Pro / Max 포함 — OAuth 안 되니까), ChatGPT Team 사용자, 그리고 OpenAI 유료 구독이 없는 분이 여기 해당. API 크레딧을 직접 충전하는 방식입니다. 신규 Anthropic 계정은 $5 무료 크레딧을 받고, 이걸로 수백 번 프롬프트 가능합니다.

**Anthropic API 키 발급** (4클릭):

1. [console.anthropic.com](https://console.anthropic.com) 가입
2. 우상단 메뉴 → **Settings** → **API Keys**
3. **Create Key** → 이름 "geode" → `sk-ant-...` 문자열 **Copy**
4. GEODE 가 찾을 위치에 저장:

```bash
mkdir -p ~/.geode
echo 'ANTHROPIC_API_KEY=sk-ant-여기에-붙여넣기' > ~/.geode/.env
chmod 600 ~/.geode/.env
```

OpenAI 또는 ZhipuAI GLM 도 쓰고 싶다면 같은 파일에 `OPENAI_API_KEY=sk-proj-...` 또는 `ZAI_API_KEY=...` 추가. GEODE 는 사용 가능한 키를 자동으로 선택합니다.

**실제 비용 감각.** 단일 프롬프트는 약 3,000 토큰, $0.01 정도. 도구 호출 10개 들어간 긴 리서치 세션은 보통 $0.05–$0.30. 무료 $5 크레딧이면 약 500번 프롬프트 가능합니다. 한도를 명시적으로 잠그고 싶으면 `.env` 에 `cost_limit_usd=5` 추가하세요.

---

### 4단계 — 실행

```bash
geode                                                # 인터랙티브 채팅
geode "오늘 AI 새 소식 뭐야?"                         # 1회성 프롬프트
```

이런 모습이 보이면:

```
● AgenticLoop
  ✓ web_search → ok (1.5s)
  ✓ web_fetch → ok (1.1s)

  오늘의 AI 주요 뉴스:
  • Anthropic, 1M 토큰 컨텍스트 Claude Opus 4.7 출시...
  • OpenAI, GPT-5.5 시스템 카드 공개; 가격은 4.6 와 동일...
  • LangGraph 0.6, 도구 호출 네이티브 스트리밍 지원...

  ✢ Worked for 8s · claude-opus-4-7 · ↓2.1k ↑412 · $0.018
```

성공입니다. 에러가 나면 `geode doctor` 로 진단하거나 [트러블슈팅](#트러블슈팅) 으로.

### 그 외 유용한 명령

```bash
geode about           # 버전, 모델, 등록된 auth, 경로, 데몬 상태
geode doctor          # 7-항목 부트스트랩 진단 + fix 힌트
uv tool upgrade geode-agent  # PyPI 로 설치한 CLI 업데이트
geode update          # 소스 체크아웃 업데이트 + editable CLI 갱신
geode uninstall       # 런타임 데이터와 설치된 CLI 제거
geode setup --reset   # ~/.geode/.env 지우고 wizard 재실행
```

---

### 업데이트

PyPI 설치라면 uv 로 CLI 패키지를 업데이트합니다.

```bash
uv tool upgrade geode-agent
geode version
```

소스 체크아웃 설치라면 GEODE가 업데이트 절차를 직접 실행하게 할 수 있습니다.

```bash
geode update
```

이 명령은 `git pull --ff-only`, `uv sync`, `uv tool install -e . --force`, `geode version`을 순서대로 실행합니다.
`geode serve` 데몬이 떠 있었다면 새 코드를 로드하도록 재시작합니다. 변경 없이 절차만 확인하려면:

```bash
geode update --dry-run
```

---

### 삭제

`geode uninstall` 은 GEODE 런타임 데이터를 지우고, 데몬을 중지하며, `geode-agent` uv tool 설치까지 제거합니다. 먼저 어떤 항목이 지워질지 확인할 수 있습니다.

```bash
geode uninstall --dry-run
geode uninstall
```

`~/.geode/` 런타임 데이터는 유지하고 PyPI 로 설치한 CLI 만 제거하려면 uv 를 직접 사용하세요.

```bash
uv tool uninstall geode-agent
```

부분 삭제 모드:

```bash
geode uninstall --keep-config   # .env 와 config.toml 보존
geode uninstall --keep-data     # vault, identity, user profile 보존
geode uninstall --force         # 자동화용 확인 생략
```

제거 확인:

```bash
which geode               # 출력 없어야 함
uv tool list | grep geode # geode-agent 가 없어야 함
pgrep -f "geode serve"    # 출력 없어야 함
```

---

### Optional — Slack / Discord / Telegram 연결

터미널에서 GEODE 가 동작한 뒤에는, 이미 쓰는 메신저 채널에서도 답하게 할 수 있습니다:

```bash
geode serve                          # 백그라운드 Gateway 데몬 시작
```

`.geode/config.toml` 에 채널 바인딩 설정 (Slack 봇 토큰, Discord 웹훅 등). 자세한 setup 은 [docs/setup.md → Gateway](docs/setup.md#gateway) 참고. 설정 후엔 채널에서 봇을 멘션하면 로컬에서 쓰는 그 동일한 에이전트 루프로 메시지가 라우팅됩니다.

### Optional — Self-improving loop 설정 (`~/.geode/config.toml`)

autoresearch / seed-generation / petri audit 드라이버의 model / dim set / banner threshold / PAYG fallback 정책을 조정하려면 [`docs/examples/self_improving_loop.config.toml.example`](docs/examples/self_improving_loop.config.toml.example) 의 `[self_improving_loop.*]` 섹션을 `~/.geode/config.toml` 로 복사하세요. 미설정 섹션은 문서화된 default 로 폴백합니다. 기존 `~/.geode/petri.toml` 의 role 별 entry 를 이전하려면:

```bash
geode config migrate-petri-toml          # dry-run 미리보기
geode config migrate-petri-toml --yes    # [self_improving_loop.petri.*] 를 config.toml 에 append
```

---

## 트러블슈팅

먼저 `geode doctor` 부터 실행하세요. Python 버전, `geode` PATH, `~/.geode/.env`, Codex CLI OAuth, ProfileStore, serve 소켓, `~/.local/bin` PATH 까지 확인하고, 실패한 항목마다 fix 명령을 알려줍니다. 아래 expander 들은 같은 내용을 글로 풀어쓴 것입니다.

<details>
<summary><strong>"command not found: python3"</strong> — Python 미설치 또는 PATH 누락.</summary>

Mac: `xcode-select --install` 후 `brew install python@3.12`. Windows: [python.org](https://www.python.org/downloads/) 에서 인스톨러 다운로드, 설치 시 "Add Python to PATH" 체크 필수. `python3 --version` 으로 3.12 이상인지 확인.
</details>

<details>
<summary><strong>"command not found: uv"</strong> — uv 가 PATH 에 안 잡힘.</summary>

설치 스크립트는 uv 를 `~/.local/bin` 에 둡니다. 터미널 재시작 또는 `source ~/.bashrc` (bash) / `source ~/.zshrc` (zsh) 실행. `uv --version` 으로 확인.
</details>

<details>
<summary><strong>"command not found: geode"</strong> — 글로벌 install 미실행.</summary>

PyPI 설치라면 `uv tool install geode-agent` 실행. 소스 체크아웃이라면 `geode/` 디렉토리에서 `uv tool install -e . --force` 실행. 두 경로 모두 `geode` 명령을 `~/.local/bin/` 에 둡니다. 그 경로가 PATH 에 없으면 셸 설정에 `export PATH="$HOME/.local/bin:$PATH"` 추가.
</details>

<details>
<summary><strong>"401 Unauthorized" 또는 "Invalid API key"</strong> — 잘못된 키, 만료된 키, 또는 잘못된 파일 위치.</summary>

`cat ~/.geode/.env` 로 확인 — 키는 `sk-ant-` (Anthropic), `sk-proj-` (OpenAI), `id.secret` (ZhipuAI GLM) 으로 시작해야 함. 공백이나 따옴표 추가되지 않았는지 체크. ChatGPT 구독 경로(Path A)면 `codex auth login` 재실행해서 OAuth 토큰 갱신.
</details>

<details>
<summary><strong>"Address already in use" — `geode serve` 실행 시 포트 충돌.</strong></summary>

`ps aux | grep "geode serve"` 로 PID 찾아 `kill <PID>`. 또는 `geode serve --port <other>` 로 다른 포트 사용.
</details>

<details>
<summary><strong>모델이 도구를 안 쓰거나, 빙빙 도는 느낌.</strong></summary>

`geode model` 로 확인 — 모델마다 도구 사용 능력이 다릅니다. 기본은 `claude-opus-4-7` (가장 강력). `gpt-5.5` 사용 중이면 `.geode/config.toml` 에 `effort: "high"` 설정. `tail -f ~/.geode/logs/serve.log` 로 모델이 실제로 뭘 하고 있는지 관찰.
</details>

<details>
<summary><strong>GEODE 내부 동작을 보고 싶어요.</strong></summary>

`tail -f ~/.geode/logs/serve.log` (또는 `geode serve` 수동 실행 시 리다이렉트한 로그 파일). 모든 LLM 호출, 도구 invocation, 의사결정이 타이밍과 함께 기록됩니다. `core.audit.diagnostics` 의 fa4 채널은 cross-process trace 를 월별 파일 `~/.geode/diagnostics/<YYYY-MM>.log` 에 작성합니다.
</details>

<details>
<summary><strong>업데이트는 어떻게 하나요?</strong></summary>

```bash
uv tool upgrade geode-agent   # PyPI 설치
geode update                  # 소스 체크아웃
```
</details>

---

## 내부 구성

| 기능 | 설명 |
|------|------|
| **`while(tool_use)` 루프** | 모든 자율 행동의 단일 원시 동작. 서브에이전트, 플랜, 배치 — 전부 같은 루프의 인스턴스 |
| **57 agentic tools + MCP 카탈로그** | 웹 검색, 파일 작업, 스케줄링, 메모리, 캘린더, Slack/Discord, 한국 채용공고 검색, 그리고 Anthropic 발행 MCP 레지스트리 (200 서버, `~/.geode/mcp/registry-cache.json` 에 캐시). 첫 사용 시 자동 설치 |
| **3-프로바이더 페일오버** | Anthropic + OpenAI + ZhipuAI. 구독 OAuth (Codex) 자동 감지; 사용량 과금 API 키도 사용 가능; 페일오버는 동일 프로바이더 내에서만 (예상치 못한 vendor 횡단 과금 없음, v0.53.0 거버넌스) |
| **5-tier 메모리** | SOUL (0) → User Profile (0.5) → Organization (1) → Project (2) → Session (3). 영속화, 데몬 재시작 후에도 유지 |
| **Plan-mode + audit trail** | `create_plan` + `approve_plan` + `list_plans` 로 다단계 작업 관리. 디스크 영구화 (`.geode/plans.json`), 재시작 후에도 유지 |
| **장시간 데몬** | `geode serve` 가 백그라운드로 상주. Slack / Discord / Telegram 폴러 + 스케줄러 tick + thin CLI 용 IPC |
| **서브에이전트** | 부모 권한 완전 상속, depth/cost 가드, Lane 격리 |
| **코어 검증** | Guardrails G1-G4 (structural) + Cross-LLM (inter-model, Krippendorff α ≥ 0.67) + Rights Risk (legal). 전문 편향 / 캘리브레이션 계층은 외부 패키지가 추가 |

---

## GEODE 비교

각 frontier 하네스의 실제 상태 기준 (2026 년 5 월): **Claude Code v2.1.72** (빌드 2026-03-09), **Codex CLI v0.130.0** (2026-05-08 릴리즈), **OpenClaw v2026.5.12-beta.1**, **GEODE v0.99.51**. 마커: ✅✅ 해당 축의 리더 · ✅ 지원 · ⚠️ 부분 / 제한적 · ❌ 없음 · n/a 적용 불가.

<details>
<summary><strong>A. 런타임 자세</strong> — 에이전트가 어떻게 떠 있는가</summary>

| | Claude Code | Codex CLI | OpenClaw | **GEODE** |
|---|---|---|---|---|
| 상시 데몬 | ❌ per-invocation | ⚠️ opt-in `codex remote-control` (v0.130+) | ✅✅ launchd / systemd 컨트롤 plane | ✅ `geode serve` 데몬 |
| 네이티브 스케줄러 (cron) | ❌ (claude.ai 웹 전용) | ❌ (Codex Cloud Automations 전용 — [issue #8317](https://github.com/openai/codex/issues/8317)) | ✅ `cron add/edit/list` CLI | ✅ cron + 이벤트 트리거 |
| Thin CLI ↔ 데몬 IPC | ❌ | ⚠️ remote-control 서버 모드 | ✅ Gateway / Agent 분리 | ✅ IPC 서버 (v0.48+) |
| Sub-agent 격리 | ✅ Agent 도구 + `run_in_background` | ✅ `multi_agent` 기능, 기본 `max_threads=6` | ✅✅ Lane Queue + Session bindings | ✅ Lane + depth / cost 가드 |
| 세션 resume / fork | ✅ JSONL 트랜스크립트 | ✅ `/resume` + `/fork` 슬래시 커맨드 | ✅ Session bindings + TTL | ✅ session resume (v0.21+) |

</details>

<details>
<summary><strong>B. 채널 & UX 표면</strong> — 사용자에게 어떻게 닿는가</summary>

| | Claude Code | Codex CLI | OpenClaw | **GEODE** |
|---|---|---|---|---|
| Slack | ❌ (MCP 플러그인 가능) | ⚠️ Codex Cloud 전용, CLI 는 미지원 | ✅ Socket Mode, first-class | ✅ Socket Mode, first-class |
| Discord / Telegram / 기타 chat | ❌ | ❌ | ✅✅ 23+ 채널 (Discord, Telegram, WhatsApp, Signal, iMessage, Teams, Matrix, Feishu, LINE, ...) | ✅ Discord + Telegram 폴러 |
| IDE 플러그인 | ❌ (Chrome MCP 확장만) | ✅✅ VS Code · JetBrains · Cursor · Windsurf | ❌ | ❌ |
| Web UI | ✅ claude.ai/code | ✅ Codex Cloud | ⚠️ WebChat 플러그인 | ❌ (문서 사이트만) |
| MCP 서버 카탈로그 | ✅ first-class | ✅ first-class | ✅ first-class | ✅ Anthropic 배포 레지스트리 (200 서버, `~/.geode/mcp/registry-cache.json` 캐시) |

</details>

<details>
<summary><strong>C. LLM 프로바이더 & 비용 거버넌스</strong></summary>

| | Claude Code | Codex CLI | OpenClaw | **GEODE** |
|---|---|---|---|---|
| 멀티 프로바이더 페일오버 | ✅ Anthropic + AWS Bedrock + Google Vertex (환경변수 라우팅) | ✅✅ OpenAI + Azure + Bedrock + Ollama + OpenAI-호환 엔드포인트 전체 (`model_providers` 설정) | ✅ `auth.order` 쿨다운 기반 자동 페일오버 | ✅ Anthropic + OpenAI + ZhipuAI, in-provider 전용 |
| 구독 OAuth tier | ✅ Pro / Max | ✅✅ Plus · Pro · Business · Edu · Enterprise | ⚠️ OpenAI + Gemini 온보딩 | ⚠️ ChatGPT 만 (Plus / Pro / Business / Edu / Enterprise) — Anthropic 약관 (2026-01-09) 이 3rd-party Claude OAuth 차단 |
| 토큰 / 비용 예산 가드 | ⚠️ 캐시 토큰 추적만 | ⚠️ 재시도 cap 만 (`request_max_retries`) | ⚠️ 부분 | ✅ **200K 토큰 가드** (v0.40), 명시적 예산 거버넌스 |
| 컨텍스트 overflow 처리 | ✅ 자동 컴팩션 | ⚠️ Skills progressive disclosure (~2% 예산) + fork | ✅ 컴팩션 + 트랜스크립트 스트리밍 (252 MB → 27 MB 피크) | ✅✅ **5-layer 컨텍스트 overflow** (v0.39+) |
| 벤더 간 페일오버 정책 | ❌ | ⚠️ `model_providers` 수동 전환 | ✅ 자동 | ❌ 의도적 (v0.53 거버넌스 — 예기치 못한 cross-vendor 과금 방지) |

</details>

<details>
<summary><strong>D. 영속성, 메모리 & 검증</strong></summary>

| | Claude Code | Codex CLI | OpenClaw | **GEODE** |
|---|---|---|---|---|
| 메모리 tier | ⚠️ 3 (user / project / local 세팅 머지) | ✅ 계층적 AGENTS.md (전역 `~/.codex/` + repo + nested dirs) | ⚠️ 세션 범위 | ✅✅ **5-tier** (SOUL · User · Org · Project · Session) |
| 디스크 영구 plan | ✅ TodoWrite 영속화 | ⚠️ resumable 스레드 경유 | ✅ task registry | ✅ `.geode/plans.json` |
| 권한 / 샌드박스 계층 | ✅ 3-mode (default / auto / bypass) + Confirmation UI | ✅ `sandbox_mode` 3 단계 (read-only / workspace-write / danger-full-access) | ✅✅ Policy Chain (40+ 감사 표면) | ✅ Policy Chain + 도구 게이트 |
| 다중 계층 가드레일 | ⚠️ 권한 + hooks | ⚠️ hooks + 샌드박스 | ✅ `audit.runtime` 엔진 | ✅✅ **코어 검증** (G1-G4 + Cross-LLM Krippendorff α ≥ 0.67 + Rights Risk, 편향/캘리브레이션용 플러그인 확장점) |
| Hook 이벤트 수 | ⚠️ 5 (PreToolUse / PostToolUse / SessionStart / Notification / ConfigChange) | ⚠️ 6 (SessionStart / UserPromptSubmit / PreToolUse / PostToolUse / PermissionRequest / Stop) | ✅ 5 이벤트 타입 · 다수 번들 핸들러 | ✅✅ **58 이벤트** (`docs/architecture/hook-system.md`) |

</details>

<details>
<summary><strong>E. 확장성 & 관측성</strong></summary>

| | Claude Code | Codex CLI | OpenClaw | **GEODE** |
|---|---|---|---|---|
| 플러그인 / 확장 표면 | ✅ manifest + 마켓플레이스 (user / project / local 스코프) | ✅ `/plugins` 슬래시 커맨드 + 플러그인 공유 (v0.130+) | ✅✅ 4 확장 지점 (Channel · Tool · Skill · Hook) via `@openclaw/plugin-sdk` | ✅ 런타임 SkillRegistry + MCP/tool 표면 |
| Skill 시스템 | ✅ Deferred tools + SKILL.md manifest | ✅ SKILL.md + progressive disclosure (`.agents/skills/`) | ✅ 스킬 필터 + archive 업로드 | ✅ 런타임 `SkillRegistry` (14 skills · bundled/global/project 스코프) |
| **교체 가능한 파이프라인 DAG** | ❌ | ❌ | ⚠️ flows (channel-setup / doctor / provider — DAG 추상화 아님) | ⚠️ 외부 패키지 책임. GEODE core 는 더 이상 파이프라인 포트를 제공하지 않음 |
| 트레이스 / 리플레이 / Run Log | ✅ `tengu_*` 텔레메트리 + `/insights` HTML | ⚠️ `/status` + `/debug-config` 만 | ✅ ACP 세션 lineage + Task Registry | ✅ 자체 RunLog + Petri eval 통합 (v0.90+) |
| Cross-LLM 검증 | ❌ | ❌ | ❌ | ✅✅ Krippendorff α ≥ 0.67 평가자 간 일치도 게이트 |

</details>

---

IDE 내부 또는 클라우드 동기화로 짧은 코딩 세션을 돌릴 땐 **Claude Code** / **Codex**. 23+ 메시징 표면에 걸친 멀티 채널 chat 에이전트 fleet 을 운영할 땐 **OpenClaw**. 다중 tier 메모리 + 다중 계층 검증 + 스케줄링 + 데몬 기반 도구 실행으로 몇 시간 / 며칠 작업을 이어갈 땐 **GEODE**.

> 출처 — Claude Code v2.1.72 (빌드 2026-03-09, 역공학 레퍼런스). Codex CLI v0.130.0 릴리즈 노트 + [developers.openai.com/codex/config-reference](https://developers.openai.com/codex/config-reference) + [github.com/openai/codex](https://github.com/openai/codex). OpenClaw v2026.5.12-beta.1 (1.8M LoC TypeScript). GEODE — `CHANGELOG.md` (`v0.39` 컨텍스트 overflow, `v0.40` 200K 가드, `v0.85` 4-layer stack, `v0.90` Petri 관측성).

---

<details>
<summary><strong>아키텍처 개요</strong> (기여자용)</summary>

GEODE 는 두 개의 컨트롤 레이어가 있습니다:

- **Scaffold (생산)** — Claude Code + `CLAUDE.md` + 개발 Skills + CI Hooks. GEODE 의 코드를 만들고 품질을 보장하는 외부 하네스.
- **GEODE Runtime (에이전트)** — `while(tool_use)` 루프 + 57 agentic tools + native ToolRegistry + 런타임 Skills + 69 런타임 Hooks + 5-Layer Verification. 자율 실행 에이전트의 내부 시스템.

4-Layer Stack (Model → Runtime → Harness → Agent) + 서브에이전트 시스템 + 5-Tier 메모리.

```mermaid
graph LR
    AG["Agent<br/>AgenticLoop, SubAgent<br/>CLIPoller, Gateway"] --> HA["Harness<br/>SessionLane, PolicyChain<br/>TaskGraph, HookSystem"]
    HA --> RT["Runtime<br/>Agentic tools(53), MCP catalog<br/>Memory, Skills"]
    RT --> MD["Model<br/>Claude, OpenAI, GLM"]

    style AG fill:#1e293b,stroke:#3b82f6,color:#e2e8f0
    style HA fill:#1e293b,stroke:#f59e0b,color:#e2e8f0
    style RT fill:#1e293b,stroke:#10b981,color:#e2e8f0
    style MD fill:#1e293b,stroke:#8b5cf6,color:#e2e8f0
```

| Layer | 핵심 | Entry points |
|-------|------|--------------|
| **Agent** | AgenticLoop, SubAgentManager, CLIPoller, Gateway | `core/cli/`, `core/gateway/` |
| **Harness** | SessionLane, LaneQueue(global:8), PolicyChain, TaskGraph, HookSystem(69) | `core/orchestration/`, `core/hooks/` |
| **Runtime** | Agentic tools(53), native ToolRegistry(16), MCP Catalog (200 via Anthropic registry plus project-configured servers), 런타임 Skills, Memory(5-Tier), PlanStore | `core/tools/`, `core/memory/`, `core/orchestration/plan_store.py` |
| **Model** | ClaudeAdapter, OpenAIAdapter, CodexAdapter, GLMAdapter | `core/llm/` |

`.geode/` — 에이전트 컨텍스트 라이프사이클 (모든 LLM 호출에 5-tier 계층 어셈블):

```
Tier 0    SOUL            GEODE.md — 에이전트 정체성 + 제약
Tier 0.5  User Profile    ~/.geode/user_profile/ — 역할, 전문성, 언어
Tier 1    Organization    크로스-프로젝트 데이터 (시그널, 이력)
Tier 2    Project         .geode/memory/PROJECT.md — 분석 이력 (LRU-50)
Tier 3    Session         메모리 — 대화, 도구 결과, 플랜
```

```
.geode/
├── config.toml         # Gateway, MCP 서버, 모델
├── memory/             # T2: 프로젝트 메모리 (LRU 회전)
├── rules/              # 자동 생성 도메인 규칙
├── vault/              # 영구 산출물 (리포트, 리서치)
├── skills/             # 프로젝트 런타임 스킬 (5-tier discovery)
├── plans.json          # 디스크 영구 PlanStore (v0.53.3)
└── result_cache/       # 파이프라인 LRU (SHA-256, 24h TTL)
```

[전체 아키텍처 →](docs/architecture/) | [Hook System →](docs/architecture/hook-system.md) | [Wiring Audit →](docs/architecture/wiring-audit-matrix.md)

</details>

<details>
<summary><strong>개발 워크플로 (Scaffold)</strong></summary>

CANNOT (가드레일) 이 CAN (자유) 보다 먼저. 7-step 워크플로 + 품질 게이트. CI 래칫 — 5 잡 (pytest, mypy, ruff, import-order, test-count) 통과해야 머지. 테스트 카운트는 단조 증가만 허용.

| Gate | 명령 | 목표 |
|------|------|------|
| Lint | `uv run ruff check core/ tests/` | 0 에러 |
| Type | `uv run mypy core/` | 0 에러 |
| Test | `uv run pytest tests/ -q` | 4700+ pass |

[CONTRIBUTING.md](CONTRIBUTING.md) 와 [docs/workflow.md](docs/workflow.md) 참고.

</details>

<details>
<summary><strong>Why — 동기</strong></summary>

2026년, AI 코딩 에이전트는 놀랍게 발전했습니다. 코드를 읽고, 쓰고, 고치고, 테스트합니다. 그런데 실제 업무 중 코딩이 차지하는 비중은 얼마나 될까요? 리서치, 문서 분석, 스케줄링, 알림, 데이터 파이프라인, 의사결정용 다축 평가 — 코딩 *너머* 자율 실행이 필요한 공간이 훨씬 넓습니다.

그런데 모든 자율 행동의 핵심은 의외로 단순합니다: LLM 이 도구를 호출하고, 결과를 관찰하고, 다음 행동을 결정하는 것 — `while(tool_use)` 루프. Claude Code, Codex, OpenClaw — 모든 프론티어 하네스가 이 원시 동작 위에 서 있습니다. GEODE 는 이를 장시간 도구 작업을 위한 데몬 기반, 메모리 보유 런타임으로 일반화합니다.

</details>

---

## License

Apache License 2.0 — [LICENSE](./LICENSE)
