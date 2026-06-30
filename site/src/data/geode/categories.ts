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
    title: "5-Tier Memory",
    postsCount: 3,
    statusKo: "Identity > Profile > Org > Project > Session 병합",
    statusEn: "Identity > Profile > Org > Project > Session merge",
    techBadges: ["SOUL.md", "UserProfile", "ProjectMemory", "SessionStorePort"],
    descriptionKo:
      "Identity(SOUL.md) → User Profile → Organization → Project → Session 5계층 메모리. 더 구체적인 계층이 앞 계층을 덮고, 요약 뒤에는 프로젝트 환경, 최근 실행 기록, 저널, Vault 요약이 붙습니다.",
    descriptionEn:
      "5-tier memory: Identity (SOUL.md) → User Profile → Organization → Project → Session. More specific tiers override earlier ones, followed by compact project environment, run history, journal, and Vault summaries.",
    achievements: [
      { icon: "🏢", titleKo: "Identity + Organization Memory. SOUL과 조직 맥락", titleEn: "Identity + Organization Memory, SOUL and org context", modalId: "modal-geode-org-context" },
      { icon: "📁", titleKo: "Project Memory + runtime rules. 프로젝트별 override", titleEn: "Project Memory + runtime rules, project-level override", modalId: "modal-geode-project-context" },
      { icon: "💬", titleKo: "Session Memory + run history. 최근 맥락 우선 유지", titleEn: "Session Memory + run history, recent context first", modalId: "modal-geode-session-context" },
    ],
    blogLink: "",
    color: "#34D399",
  },
  {
    id: "runtime",
    icon: "▶️",
    title: "Runtime & Router",
    postsCount: 2,
    statusKo: "Planner 진행 상태 + 체크포인트",
    statusEn: "Planner progress + checkpoints",
    techBadges: ["Planner", "Progress Plan", "Review Checkpoint", "Pydantic Settings"],
    descriptionKo:
      "Planner는 메인 루프 모델을 그대로 사용해 요청을 분해하고 진행 상태를 드러냅니다. 일반 작업은 진행 체크리스트로 계속 실행하고, 명시적 검토가 필요할 때만 승인 checkpoint를 둡니다.",
    descriptionEn:
      "The Planner uses the main loop model to decompose work and surface progress. Routine work uses a live checklist and keeps going; explicit review checkpoints remain available when needed.",
    achievements: [
      { icon: "⚙️", titleKo: "Planner가 메인 루프 모델을 상속해 작업 분해", titleEn: "Planner inherits the main loop model for task decomposition", modalId: "modal-geode-settings" },
      { icon: "🏭", titleKo: "Progress Plan 진행 상태 표시 + 명시적 checkpoint 분리", titleEn: "Progress Plan updates with explicit checkpoints separated", modalId: "modal-geode-factory" },
      { icon: "💉", titleKo: "LLMClientPort 추상화로 Claude·GPT·GLM 계열 역할별 DI", titleEn: "LLMClientPort abstraction wires Claude/GPT/GLM families by role", modalId: "modal-geode-di" },
    ],
    blogLink: "",
    color: "#60A5FA",
  },
  {
    id: "pipeline",
    icon: "🔀",
    title: "AgenticLoop Runtime",
    postsCount: 5,
    statusKo: "while(tool_use) 루프 + 컨텍스트 가드",
    statusEn: "while(tool_use) loop + context guards",
    techBadges: ["AgenticLoop", "ToolExecutor", "ContextWindowManager", "SubAgent"],
    descriptionKo:
      "GEODE core runtime은 AgenticLoop입니다. 모델이 tool_use를 내는 동안 루프가 계속되고, ToolExecutor가 도구 실행과 승인 게이트를 맡으며, ContextWindowManager가 오버플로와 압축 경로를 관리합니다.",
    descriptionEn:
      "GEODE core runtime is the AgenticLoop. The loop continues while the model emits tool_use, ToolExecutor owns execution and approval gates, and ContextWindowManager manages overflow and compaction paths.",
    achievements: [
      { icon: "🗺️", titleKo: "AgenticLoop while(tool_use) 실행과 종료 사유", titleEn: "AgenticLoop while(tool_use) execution and termination reasons", modalId: "modal-geode-stategraph" },
      { icon: "📡", titleKo: "SubAgent 격리 실행과 툴킷 기반 위임", titleEn: "SubAgent isolated execution with toolkit-based delegation", modalId: "modal-geode-send-api" },
      { icon: "➕", titleKo: "ContextWindowManager 오버플로 감지 + 압축", titleEn: "ContextWindowManager overflow detection + compaction", modalId: "modal-geode-reducer" },
      { icon: "📋", titleKo: "ToolExecutor 안전 게이트 + 도구 결과 오프로드", titleEn: "ToolExecutor safety gate + tool-result offload", modalId: "modal-geode-node-contract" },
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
      { icon: "🧭", titleKo: "Planner 진행 체크리스트 + 승인 checkpoint", titleEn: "Planner progress checklist + approval checkpoints", modalId: "modal-geode-planner" },
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
