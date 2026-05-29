export interface Achievement {
  icon: string;
  titleKo: string;
  titleEn: string;
  modalId: string;
}

export interface CategoryData {
  id: string;
  icon: string;
  title: string;
  postsCount: number;
  statusKo: string;
  statusEn: string;
  techBadges: string[];
  descriptionKo: string;
  descriptionEn: string;
  achievements: Achievement[];
  blogLink: string;
  color: string;
}

export const geodeCategories: CategoryData[] = [
  {
    id: "memory",
    icon: "🧠",
    title: "3-Tier Memory",
    postsCount: 3,
    statusKo: "Organization > Project > Session 우선순위 해소",
    statusEn: "Organization > Project > Session priority resolution",
    techBadges: ["MonoLake", "Redis", "PostgreSQL", "MEMORY.md"],
    descriptionKo:
      "Organization(MonoLake/Snowflake SSOT) → Project(.claude/MEMORY.md) → Session(Redis L1 4hr TTL + PostgreSQL L2) 3계층 메모리. 우선순위: Project > Organization, Organization = 외부 지식/정책 데이터. 세션 간 컨텍스트 유지와 분석 히스토리 누적을 관리합니다.",
    descriptionEn:
      "3-tier memory: Organization (MonoLake/Snowflake SSOT) → Project (.claude/MEMORY.md) → Session (Redis L1 4hr TTL + PostgreSQL L2). Priority: Project > Organization; Organization is the source for external knowledge and policy data. Manages cross-session context and analysis history accumulation.",
    achievements: [
      { icon: "🏢", titleKo: "Organization Memory MonoLake/Snowflake SSOT. 외부 지식/정책", titleEn: "Organization Memory MonoLake/Snowflake SSOT, external knowledge/policy", modalId: "modal-geode-org-context" },
      { icon: "📁", titleKo: "Project Memory .claude/MEMORY.md + rules. 루브릭 오버라이드", titleEn: "Project Memory .claude/MEMORY.md + rules, rubric override", modalId: "modal-geode-project-context" },
      { icon: "💬", titleKo: "Session Memory Redis L1 (4hr TTL) + PostgreSQL L2 영구 저장", titleEn: "Session Memory Redis L1 (4hr TTL) + PostgreSQL L2 permanent storage", modalId: "modal-geode-session-context" },
    ],
    blogLink: "",
    color: "#34D399",
  },
  {
    id: "runtime",
    icon: "▶️",
    title: "Runtime & Router",
    postsCount: 2,
    statusKo: "Planner (GLM-5) 비용 기반 라우팅",
    statusEn: "Planner (GLM-5) cost-aware routing",
    techBadges: ["GLM-5", "Planner", "Plan Mode", "Pydantic Settings"],
    descriptionKo:
      "GLM-5 기반 Planner가 작업의 비용과 깊이에 맞춰 라우트를 고릅니다. full_pipeline부터 script_route, direct_answer까지 비용 폭이 넓고, Plan Mode에서 사용자 승인 후 실행합니다.",
    descriptionEn:
      "A GLM-5 Planner picks the route by the task's cost and depth, from full_pipeline down to script_route and direct_answer. Plan Mode requires user approval before execution.",
    achievements: [
      { icon: "⚙️", titleKo: "Planner full_pipeline~script_route 비용 최적화 분기", titleEn: "Planner full_pipeline~script_route cost-optimized routing", modalId: "modal-geode-settings" },
      { icon: "🏭", titleKo: "Plan Mode 분석 전략 수립 → 사용자 승인 → 실행", titleEn: "Plan Mode analysis strategy → user approval → execution", modalId: "modal-geode-factory" },
      { icon: "💉", titleKo: "LLMClientPort 추상화로 Claude·GPT·GLM 계열 역할별 DI", titleEn: "LLMClientPort abstraction wires Claude/GPT/GLM families by role", modalId: "modal-geode-di" },
    ],
    blogLink: "",
    color: "#60A5FA",
  },
  {
    id: "pipeline",
    icon: "🔀",
    title: "LangGraph Pipeline",
    postsCount: 5,
    statusKo: "StateGraph + Send API 병렬 Fan-out",
    statusEn: "StateGraph + Send API Parallel Fan-out",
    techBadges: ["LangGraph", "StateGraph", "Send API", "Reducer", "Confidence Loop"],
    descriptionKo:
      "LangGraph StateGraph 기반 파이프라인: router → gather → tools → scoring → verification → synthesizer. Confidence < 0.7이면 gather로 루프백(최대 3회). Send API fan-out은 외부 도메인 패키지가 필요한 경우 확장합니다.",
    descriptionEn:
      "LangGraph StateGraph pipeline: router → gather → tools → scoring → verification → synthesizer. Loops back to gather if confidence < 0.7 (max 3 iterations). External domain packages can add Send API fan-out when needed.",
    achievements: [
      { icon: "🗺️", titleKo: "StateGraph stream() 기반 실시간 진행 + Confidence Loop", titleEn: "StateGraph stream()-based real-time progress + Confidence Loop", modalId: "modal-geode-stategraph" },
      { icon: "📡", titleKo: "Send API Fan-out 4 분석가 Clean Context (analyses 제거) 병렬", titleEn: "Send API Fan-out 4 analysts Clean Context (no analyses) parallel", modalId: "modal-geode-send-api" },
      { icon: "➕", titleKo: "Reducer analyses: Annotated[list, operator.add] 자동 병합", titleEn: "Reducer analyses: Annotated[list, operator.add] auto-merge", modalId: "modal-geode-reducer" },
      { icon: "📋", titleKo: "Node Contract 각 노드 → dict(output keys only) 반환 규약", titleEn: "Node Contract each node → dict(output keys only) return rule", modalId: "modal-geode-node-contract" },
    ],
    blogLink: "",
    color: "#818CF8",
  },
  {
    id: "orchestration",
    icon: "🎛️",
    title: "Orchestration",
    postsCount: 4,
    statusKo: "Hook 이벤트 + TaskSystem + Bootstrap",
    statusEn: "Hook events + TaskSystem + Bootstrap",
    techBadges: ["Hook events", "CONTINUE/ABORT/MODIFY", "TaskSystem", "Bootstrap"],
    descriptionKo:
      "Hook 이벤트(SESSION_START/END, PRE/POST_ANALYSIS, PRE/POST_TOOL_USE, TASK_START/COMPLETE/FAIL, ON_ERROR, ON_NOTIFICATION)로 파이프라인 라이프사이클을 관리합니다. Hook 결과는 CONTINUE/ABORT/MODIFY로 흐름을 제어합니다. TaskSystem으로 의존성 그래프 기반 분석 작업을 스케줄링합니다.",
    descriptionEn:
      "Hook events (SESSION_START/END, PRE/POST_ANALYSIS, PRE/POST_TOOL_USE, TASK_START/COMPLETE/FAIL, ON_ERROR, ON_NOTIFICATION) manage the pipeline lifecycle. Hook results control flow via CONTINUE/ABORT/MODIFY. TaskSystem schedules analysis jobs from a dependency graph.",
    achievements: [
      { icon: "🪝", titleKo: "Hook System 이벤트 × CONTINUE/ABORT/MODIFY 제어", titleEn: "Hook System events × CONTINUE/ABORT/MODIFY control", modalId: "modal-geode-hooks" },
      { icon: "📝", titleKo: "TaskSystem 의존성 그래프 기반 병렬/순차 작업 스케줄링", titleEn: "TaskSystem dependency graph-based parallel/sequential scheduling", modalId: "modal-geode-task-system" },
      { icon: "🧭", titleKo: "Planner GLM-5 비용 기반 분기 + Plan Mode 승인", titleEn: "Planner GLM-5 cost-aware branching + Plan Mode approval", modalId: "modal-geode-planner" },
      { icon: "🔌", titleKo: "Bootstrap 서비스 와이어링 + Hook Registry 초기화", titleEn: "Bootstrap service wiring + Hook Registry initialization", modalId: "modal-geode-bootstrap" },
    ],
    blogLink: "",
    color: "#F472B6",
  },
  {
    id: "verification",
    icon: "🛡️",
    title: "Core Verification",
    postsCount: 3,
    statusKo: "Guardrails → Cross-LLM → Rights Risk",
    statusEn: "Guardrails → Cross-LLM → Rights Risk",
    techBadges: ["G1-G4", "Cross-LLM α≥0.80", "Rights Risk", "Plugin Extension"],
    descriptionKo:
      "코어 검증: Per-Agent Guardrail(G1 Schema, G2 Range, G3 Grounding, G4 Consistency), Cross-LLM 교차 검증(Krippendorff's α≥0.80 목표), Rights Risk 평가. 편향 검사와 golden-set 캘리브레이션은 외부 도메인 플러그인이 소유합니다.",
    descriptionEn:
      "Core verification: Per-Agent Guardrail (G1 Schema, G2 Range, G3 Grounding, G4 Consistency), Cross-LLM cross-validation (Krippendorff's α≥0.80 target), and Rights Risk assessment. Bias checks and golden-set calibration are owned by external packages.",
    achievements: [
      { icon: "🚧", titleKo: "G1-G4 Per-Agent Guardrail Schema·Range·Grounding·Consistency", titleEn: "G1-G4 Per-Agent Guardrail Schema·Range·Grounding·Consistency", modalId: "modal-geode-guardrails" },
      { icon: "🔁", titleKo: "Cross-LLM 독립 재스코어링 + 일치도 게이트", titleEn: "Cross-LLM independent re-scoring + agreement gate", modalId: "modal-geode-cross-llm" },
      { icon: "⚖️", titleKo: "Rights Risk 평가 + 외부 검증 패키지", titleEn: "Rights Risk assessment + external verification packages", modalId: "modal-geode-rights-risk" },
    ],
    blogLink: "",
    color: "#FBBF24",
  },
  {
    id: "automation",
    icon: "🔄",
    title: "Automation Sidecar",
    postsCount: 4,
    statusKo: "Trigger Manager + Feedback Loop + Expert Panel",
    statusEn: "Trigger Manager + Feedback Loop + Expert Panel",
    techBadges: ["Trigger types", "FeedbackLoop", "RLAIF", "NDC25 Expert"],
    descriptionKo:
      "Manual CLI, Scheduled CronTimer, Event Hook, Webhook POST 트리거와 사전 정의 자동화 템플릿을 제공합니다. FeedbackLoop(T+0→T+30/90/180d→CORREL→TUNE→RLAIF)로 예측-성과 갭을 추적하고, NDC25 기반 Expert Panel(Tier 3: Score≥0.85, ρ≥0.50)이 LLM 판단을 검증합니다.",
    descriptionEn:
      "Manual CLI, Scheduled CronTimer, Event Hook, and Webhook POST triggers, with pre-defined automation templates. FeedbackLoop (T+0→T+30/90/180d→CORREL→TUNE→RLAIF) tracks the prediction-outcome gap, and an NDC25-based Expert Panel (Tier 3: Score≥0.85, ρ≥0.50) validates LLM judgments.",
    achievements: [
      { icon: "📊", titleKo: "Trigger Manager 트리거 종류 + 자동화 템플릿", titleEn: "Trigger Manager trigger types + automation templates", modalId: "modal-geode-cusum" },
      { icon: "🎯", titleKo: "Outcome Tracking T+30/90/180d 예측 vs 실제 Delta 추적", titleEn: "Outcome Tracking T+30/90/180d prediction vs actual Delta tracking", modalId: "modal-geode-outcome-tracking" },
      { icon: "🔁", titleKo: "FeedbackLoop T+0→T+30/90/180d→CORREL→TUNE→RLAIF 5단계", titleEn: "FeedbackLoop T+0→T+30/90/180d→CORREL→TUNE→RLAIF 5-stage", modalId: "modal-geode-feedback" },
      { icon: "👨‍🏫", titleKo: "Expert Panel NDC25 기반 Tier 3 검증 전문가 (Score≥0.85)", titleEn: "Expert Panel NDC25-based Tier 3 verified expert (Score≥0.85)", modalId: "modal-geode-expert-panel" },
    ],
    blogLink: "",
    color: "#A78BFA",
  },
  {
    id: "llm",
    icon: "✨",
    title: "Multi-LLM Orchestration",
    postsCount: 4,
    statusKo: "LLMClientPort + 구조화 출력",
    statusEn: "LLMClientPort + structured output",
    techBadges: ["Opus", "Sonnet", "Haiku", "GPT-5", "GLM-5"],
    descriptionKo:
      "LLMClientPort 추상화로 모델을 역할별로 배치합니다. Claude 계열, GPT-5 계열, GLM 계열을 라우팅 매니페스트와 노드별 정책으로 선택하고, 구조화 출력과 guardrail로 평가 품질을 유지합니다.",
    descriptionEn:
      "The LLMClientPort abstraction deploys models by role across the Claude, GPT-5, Codex, and GLM families. Routing manifests and node policies choose the model, while structured output and guardrails preserve evaluation quality.",
    achievements: [
      { icon: "🤖", titleKo: "역할별 모델 배치 최적 할당 (Opus→Haiku)", titleEn: "Role-based model deployment, optimized assignment (Opus→Haiku)", modalId: "modal-geode-claude-client" },
      { icon: "📐", titleKo: "구조화 출력 + schema guard", titleEn: "Structured output + schema guard", modalId: "modal-geode-structured-output" },
      { icon: "📝", titleKo: "프롬프트 해시 래칫", titleEn: "Prompt hash ratchet", modalId: "modal-geode-prompts" },
    ],
    blogLink: "",
    color: "#FB923C",
  },
  {
    id: "cli",
    icon: "💻",
    title: "CLI + REPL",
    postsCount: 3,
    statusKo: "Typer + Rich + NL Router",
    statusEn: "Typer + Rich + NL Router",
    techBadges: ["Typer", "Rich", "NL Router", "REPL", "Deferred tools"],
    descriptionKo:
      "Typer 기반 CLI와 대화형 REPL로 작업을 실행합니다. Rich Live Display로 graph.stream() 이벤트를 실시간 렌더링하고, NL Router가 자연어 입력을 CLI 명령으로 자동 변환합니다. 도구는 상시 로드와 지연 로드로 나뉘어, 필요할 때만 컨텍스트에 올라옵니다.",
    descriptionEn:
      "Typer-based CLI and interactive REPL for running tasks. Rich Live Display renders graph.stream() events in real-time, and the NL Router auto-converts natural language to CLI commands. Tools split into always-loaded and deferred sets so the context only carries what a task needs.",
    achievements: [
      { icon: "⌨️", titleKo: "Typer CLI + 자연어 입력 + 지연 로드 도구 카탈로그", titleEn: "Typer CLI + natural-language input + deferred tool catalog", modalId: "modal-geode-cli" },
      { icon: "🎨", titleKo: "Rich Live Display graph.stream() 실시간 파이프라인 시각화", titleEn: "Rich Live Display graph.stream() real-time pipeline visualization", modalId: "modal-geode-rich-display" },
      { icon: "🗣️", titleKo: "NL Router 자연어 → CLI 명령 자동 변환", titleEn: "NL Router natural language → CLI command auto-conversion", modalId: "modal-geode-nl-router" },
    ],
    blogLink: "",
    color: "#2DD4BF",
  },
];
