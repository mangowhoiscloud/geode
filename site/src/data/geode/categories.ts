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
      "Organization(MonoLake/Snowflake SSOT) → Project(.claude/MEMORY.md) → Session(Redis L1 4hr TTL + PostgreSQL L2) 3계층 메모리. 우선순위: Project > Organization(루브릭 가중치), Organization = SSOT(IP 마스터 데이터). 세션 간 컨텍스트 유지와 분석 히스토리 누적을 관리합니다.",
    descriptionEn:
      "3-tier memory: Organization (MonoLake/Snowflake SSOT) → Project (.claude/MEMORY.md) → Session (Redis L1 4hr TTL + PostgreSQL L2). Priority: Project > Organization for rubric weights; Organization is SSOT for IP master data. Manages cross-session context and analysis history accumulation.",
    achievements: [
      { icon: "🏢", titleKo: "Organization Memory MonoLake/Snowflake SSOT — IP 마스터 데이터", titleEn: "Organization Memory MonoLake/Snowflake SSOT — IP master data", modalId: "modal-geode-org-context" },
      { icon: "📁", titleKo: "Project Memory .claude/MEMORY.md + rules — 루브릭 오버라이드", titleEn: "Project Memory .claude/MEMORY.md + rules — rubric override", modalId: "modal-geode-project-context" },
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
    statusKo: "6-Route Planner (GLM-5)",
    statusEn: "6-Route Planner (GLM-5)",
    techBadges: ["GLM-5", "6 Routes", "Plan Mode", "Pydantic Settings"],
    descriptionKo:
      "GLM-5 기반 Planner가 6개 라우트(full_pipeline $1.50, prospect $0.80, partial_rerun $0.15, data_refresh $0.30, direct_answer $0.02, script_route $0.05)로 최적 분기합니다. Plan Mode에서 사용자 승인 후 실행합니다.",
    descriptionEn:
      "GLM-5-based Planner routes to 6 optimal paths: full_pipeline ($1.50), prospect ($0.80), partial_rerun ($0.15), data_refresh ($0.30), direct_answer ($0.02), script_route ($0.05). Plan Mode requires user approval before execution.",
    achievements: [
      { icon: "⚙️", titleKo: "6-Route Planner full_pipeline~script_route 비용 최적화 분기", titleEn: "6-Route Planner full_pipeline~script_route cost-optimized routing", modalId: "modal-geode-settings" },
      { icon: "🏭", titleKo: "Plan Mode 분석 전략 수립 → 사용자 승인 → 실행", titleEn: "Plan Mode analysis strategy → user approval → execution", modalId: "modal-geode-factory" },
      { icon: "💉", titleKo: "LLMClientPort 추상화 Opus/Sonnet/Haiku/GPT/Gemini 5모델 DI", titleEn: "LLMClientPort abstraction Opus/Sonnet/Haiku/GPT/Gemini 5-model DI", modalId: "modal-geode-di" },
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
      "LangGraph StateGraph 기반 파이프라인: router → cortex → signals → analyst×4 (Send API fan-out) → evaluators×3 → scoring(PSM + LLM Judge) → verification → synthesizer. Confidence < 0.7이면 cortex로 루프백(최대 3회). Send API로 4명의 분석가를 analyses 필드 제거한 Clean Context에서 병렬 실행하여 앵커링 바이어스를 방지합니다.",
    descriptionEn:
      "LangGraph StateGraph pipeline: router → cortex → signals → analyst×4 (Send API fan-out) → evaluators×3 → scoring (PSM + LLM Judge) → verification → synthesizer. Loops back to cortex if confidence < 0.7 (max 3 iterations). Send API executes 4 analysts in parallel with Clean Context (analyses field removed) to prevent anchoring bias.",
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
    statusKo: "46 Hook Events + TaskSystem + Bootstrap",
    statusEn: "46 Hook Events + TaskSystem + Bootstrap",
    techBadges: ["11 Events", "CONTINUE/ABORT/MODIFY", "TaskSystem", "Bootstrap"],
    descriptionKo:
      "11개 Hook 이벤트(SESSION_START/END, PRE/POST_ANALYSIS, PRE/POST_TOOL_USE, TASK_START/COMPLETE/FAIL, ON_ERROR, ON_NOTIFICATION)로 파이프라인 라이프사이클을 관리합니다. Hook 결과는 CONTINUE/ABORT/MODIFY로 흐름을 제어합니다. TaskSystem으로 의존성 그래프 기반 분석 작업을 스케줄링합니다.",
    descriptionEn:
      "11 Hook events (SESSION_START/END, PRE/POST_ANALYSIS, PRE/POST_TOOL_USE, TASK_START/COMPLETE/FAIL, ON_ERROR, ON_NOTIFICATION) manage pipeline lifecycle. Hook results control flow via CONTINUE/ABORT/MODIFY. TaskSystem schedules analysis jobs based on dependency graph.",
    achievements: [
      { icon: "🪝", titleKo: "Hook System 11 이벤트 × CONTINUE/ABORT/MODIFY 제어", titleEn: "Hook System 11 events × CONTINUE/ABORT/MODIFY control", modalId: "modal-geode-hooks" },
      { icon: "📝", titleKo: "TaskSystem 의존성 그래프 기반 병렬/순차 작업 스케줄링", titleEn: "TaskSystem dependency graph-based parallel/sequential scheduling", modalId: "modal-geode-task-system" },
      { icon: "🧭", titleKo: "Planner GLM-5 6-route 분기 + Plan Mode 승인", titleEn: "Planner GLM-5 6-route branching + Plan Mode approval", modalId: "modal-geode-planner" },
      { icon: "🔌", titleKo: "Bootstrap 서비스 와이어링 + Hook Registry 초기화", titleEn: "Bootstrap service wiring + Hook Registry initialization", modalId: "modal-geode-bootstrap" },
    ],
    blogLink: "",
    color: "#F472B6",
  },
  {
    id: "verification",
    icon: "🛡️",
    title: "3-Layer Verification",
    postsCount: 3,
    statusKo: "Guardrails → BiasBuster → Cross-LLM 3단계",
    statusEn: "Guardrails → BiasBuster → Cross-LLM 3-layer",
    techBadges: ["G1-G4", "BiasBuster 4-Step", "Cross-LLM α≥0.80", "Decision Tree"],
    descriptionKo:
      "3단계 검증: Layer 1 Per-Agent Guardrail(G1 Schema, G2 Range, G3 Grounding, G4 Consistency), Layer 2 BiasBuster 4-Step(RECOGNIZE→EXPLAIN→ALTER→EVALUATE, CV 기반 앵커링 감지), Layer 3 Cross-LLM + Human 교차 검증(Krippendorff's α≥0.80 목표). Decision Tree는 D-E-F 축 코드 기반 원인 분류(LLM 미사용).",
    descriptionEn:
      "3-layer verification: Layer 1 Per-Agent Guardrail (G1 Schema, G2 Range, G3 Grounding, G4 Consistency), Layer 2 BiasBuster 4-Step (RECOGNIZE→EXPLAIN→ALTER→EVALUATE, CV-based anchoring detection), Layer 3 Cross-LLM + Human cross-validation (Krippendorff's α≥0.80 target). Decision Tree classifies causes via D-E-F axes code-only (no LLM).",
    achievements: [
      { icon: "🚧", titleKo: "G1-G4 Per-Agent Guardrail Schema·Range·Grounding·Consistency", titleEn: "G1-G4 Per-Agent Guardrail Schema·Range·Grounding·Consistency", modalId: "modal-geode-guardrails" },
      { icon: "⚖️", titleKo: "BiasBuster 4-Step RECOGNIZE→EXPLAIN→ALTER→EVALUATE", titleEn: "BiasBuster 4-Step RECOGNIZE→EXPLAIN→ALTER→EVALUATE", modalId: "modal-geode-biasbuster" },
      { icon: "🌳", titleKo: "Decision Tree D-E-F 축 코드 분류 6종 원인 + 액션 매핑", titleEn: "Decision Tree D-E-F axis code classification 6 causes + action mapping", modalId: "modal-geode-decision-tree" },
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
    techBadges: ["4 Trigger Types", "FeedbackLoop", "RLAIF", "NDC25 Expert"],
    descriptionKo:
      "4종 트리거(Manual CLI, Scheduled CronTimer, Event Hook, Webhook POST)와 10개 사전 정의 자동화 템플릿을 제공합니다. FeedbackLoop 5단계(T+0→T+30/90/180d→CORREL→TUNE→RLAIF)로 예측-성과 갭을 추적하고, NDC25 기반 Expert Panel(Tier 3: Score≥0.85, ρ≥0.50)이 LLM 판단을 검증합니다.",
    descriptionEn:
      "4 trigger types (Manual CLI, Scheduled CronTimer, Event Hook, Webhook POST) with 10 pre-defined automation templates. FeedbackLoop 5-stage (T+0→T+30/90/180d→CORREL→TUNE→RLAIF) tracks prediction-outcome gap. NDC25-based Expert Panel (Tier 3: Score≥0.85, ρ≥0.50) validates LLM judgments.",
    achievements: [
      { icon: "📊", titleKo: "Trigger Manager 4종 트리거 + 10 자동화 템플릿", titleEn: "Trigger Manager 4 trigger types + 10 automation templates", modalId: "modal-geode-cusum" },
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
    statusKo: "5모델 LLMClientPort + 14축 Rubric + PSM",
    statusEn: "5-model LLMClientPort + 14-axis Rubric + PSM",
    techBadges: ["Opus 4.6", "Sonnet 4.6", "Haiku", "GPT-5.4", "GLM-5"],
    descriptionKo:
      "LLMClientPort 추상화로 5개 모델을 역할별 배치: Claude Opus 4.6(Analyst×4, Evaluator×3, Synthesizer), Claude Sonnet 4(LLM Judge, Memory), Claude Haiku(Per-Agent Guardrail), GPT-5.4(Cortex SQL), GLM-5(Planner). 14축 루브릭(Quality 8 + Hidden Value 3 + Momentum 3)과 14-covariate PSM으로 정량 평가합니다.",
    descriptionEn:
      "LLMClientPort abstraction deploys 5 models by role: Claude Opus 4.6 (Analyst×4, Evaluator×3, Synthesizer), Claude Sonnet 4 (LLM Judge, Memory), Claude Haiku (Per-Agent Guardrail), GPT-5.4 (Cortex SQL), GLM-5 (Planner). 14-axis rubric (Quality 8 + Hidden Value 3 + Momentum 3) and 14-covariate PSM for quantitative evaluation.",
    achievements: [
      { icon: "🤖", titleKo: "5-Model 배치 역할별 최적 모델 할당 (Opus→Haiku)", titleEn: "5-Model deployment role-optimized model assignment (Opus→Haiku)", modalId: "modal-geode-claude-client" },
      { icon: "📐", titleKo: "14축 루브릭 Quality(8) + Hidden Value(3) + Momentum(3)", titleEn: "14-axis rubric Quality(8) + Hidden Value(3) + Momentum(3)", modalId: "modal-geode-structured-output" },
      { icon: "📝", titleKo: "PSM Engine 14-covariate Propensity Score Matching (ATT)", titleEn: "PSM Engine 14-covariate Propensity Score Matching (ATT)", modalId: "modal-geode-prompts" },
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
    techBadges: ["Typer", "Rich", "NL Router", "REPL", "17 Tools"],
    descriptionKo:
      "Typer 기반 CLI와 대화형 REPL로 분석을 실행합니다. Rich Live Display로 graph.stream() 이벤트를 실시간 렌더링하고, NL Router가 자연어 입력을 CLI 명령으로 자동 변환합니다. 5개 카테고리 17개 Tool(Data 3, Signal 5, Analysis 3, Memory 3, Output 3)을 제공합니다.",
    descriptionEn:
      "Typer-based CLI and interactive REPL for running analyses. Rich Live Display renders graph.stream() events in real-time, NL Router auto-converts natural language to CLI commands. 17 Tools across 5 categories (Data 3, Signal 5, Analysis 3, Memory 3, Output 3).",
    achievements: [
      { icon: "⌨️", titleKo: "Typer CLI analyze, batch, compare + 17 Tools 5카테고리", titleEn: "Typer CLI analyze, batch, compare + 17 Tools 5 categories", modalId: "modal-geode-cli" },
      { icon: "🎨", titleKo: "Rich Live Display graph.stream() 실시간 파이프라인 시각화", titleEn: "Rich Live Display graph.stream() real-time pipeline visualization", modalId: "modal-geode-rich-display" },
      { icon: "🗣️", titleKo: "NL Router 자연어 → CLI 명령 자동 변환", titleEn: "NL Router natural language → CLI command auto-conversion", modalId: "modal-geode-nl-router" },
    ],
    blogLink: "",
    color: "#2DD4BF",
  },
];
