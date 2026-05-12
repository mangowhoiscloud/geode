"use client";

import { useEffect, useState, useRef } from "react";
import { ScrollReveal } from "../scroll-reveal";

/* ── 8-stage workflow (실제 운영 기반) ── */
const stages = [
  { id: 0, label: "Board", sub: "progress.md", color: "#F4B8C8" },
  { id: 1, label: "Audit", sub: "GAP 탐지", color: "#E87080" },
  { id: 2, label: "Plan", sub: "Research", color: "#818CF8" },
  { id: 3, label: "Implement", sub: "코드 작성", color: "#60A5FA" },
  { id: 4, label: "Ratchet", sub: "CI 래칫", color: "#34D399" },
  { id: 5, label: "Docs", sub: "Sync", color: "#4ECDC4" },
  { id: 6, label: "PR", sub: "GitFlow", color: "#C084FC" },
  { id: 7, label: "Done", sub: "Kanban Done", color: "#F5C542" },
];

const stageDetails: Record<number, { title: string; result: string; kanban: string; git: string }> = {
  0: {
    title: "Board + Worktree 할당",
    result: "docs/progress.md에 작업을 Backlog → In Progress로 이동합니다. git fetch로 로컬/리모트 동기화를 검증한 뒤, git worktree add .claude/worktrees/<작업명> -b feature/<name> develop으로 격리 공간을 할당합니다. .owner 파일에 세션 ID를 기록하여 타 세션의 삭제를 방지합니다.",
    kanban: "Backlog → In Progress",
    git: "git worktree add → feature/xxx",
  },
  1: {
    title: "GAP Audit — 소크라틱 게이트",
    result: "docs/plans/의 To-Be 항목과 실제 코드를 대조하여 GAP을 분류합니다(구현 완료 / 부분 구현 / 미구현). 미구현 항목에 소크라틱 5문항(코드에 있는가? 안 하면 뭐가 깨지나? 측정 가능한가? 최소 구현은? 프론티어 3종 패턴인가?)을 적용하여 실제 구현 대상만 필터링합니다.",
    kanban: "In Progress",
    git: "feature/xxx에서 GAP 분석",
  },
  2: {
    title: "Plan + Frontier Research",
    result: "신규 인프라 기능이면 frontier-harness-research 스킬로 Claude Code · Codex CLI · OpenClaw · Aider를 병렬 조사합니다. DISCOVER(조사) → COMPARE(기능 × 하네스 매트릭스) → DECIDE(Option A/B/C + 근거) → DOCUMENT(docs/plans/research-<topic>.md).",
    kanban: "In Progress",
    git: "docs/plans/research-*.md",
  },
  3: {
    title: "Implement — CANNOT/CAN 경계",
    result: "CLAUDE.md의 CANNOT 14개 규칙(worktree 없이 코드 작업 금지, main 직접 push 금지, type:ignore 남발 금지, live 테스트 무단 실행 금지 등) 안에서 구현합니다. CAN 6개(버그 수정, 기회적 개선, 테스트 선택, 언어 선택, 도구 선택, worktree 병렬 실험)는 자율 판단입니다.",
    kanban: "In Progress",
    git: "feature/xxx에서 코드 변경",
  },
  4: {
    title: "Pre-PR Quality Gate 래칫",
    result: "ruff check · ruff format · mypy · bandit · pytest 5개 도구를 전부 통과해야 커밋합니다. 하나라도 실패하면 수정 → 재실행 루프. 코드와 docs(CHANGELOG [Unreleased], CLAUDE.md 수치, progress.md)를 반드시 하나의 커밋에 포함합니다. docs만 별도 커밋은 금지.",
    kanban: "In Progress → In Review",
    git: "commit → push → PR 생성",
  },
  5: {
    title: "Docs-Sync — 이중 검증",
    result: "Pre-PR에서 CHANGELOG.md [Unreleased] 항목, CLAUDE.md Tests/Modules 수치, docs/progress.md 오늘 날짜 섹션을 작성합니다. main merge 후에는 README.md 수치 정합성, pyproject.toml coverage omit, 버전 4곳 일치(CHANGELOG · CLAUDE.md · README · pyproject.toml)를 최종 검증합니다.",
    kanban: "In Review",
    git: "docs 포함 커밋 → Post-merge 검증",
  },
  6: {
    title: "PR + Post-PR CI 래칫",
    result: "HEREDOC 포맷 PR body(요약 · 변경사항 · 영향범위 · 설계판단 · QG 체크리스트)를 작성합니다. gh pr checks --watch로 CI 전체 통과를 확인한 후에만 merge합니다. feature→develop 후 develop→main 배치 merge. Merge Queue 규칙: 한 번에 하나, 다음 worktree는 rebase 후 CI 재확인.",
    kanban: "In Review",
    git: "feature→develop PR, develop→main PR",
  },
  7: {
    title: "Board 정리 + Worktree 해제",
    result: "progress.md를 In Progress → Done으로 이동합니다. git worktree remove로 작업 공간을 해제하고, git branch -d + git push origin --delete로 로컬·리모트 브랜치를 정리합니다. git worktree list로 누수(닫히지 않은 worktree)를 점검합니다.",
    kanban: "In Review → Done",
    git: "worktree remove → branch -d → leak check",
  },
};

/* ── Track geometry ── */
const TRACK_PATH =
  "M 70,130 L 850,130 C 885,130 900,155 900,175 C 900,195 885,220 850,220 L 70,220 C 35,220 20,195 20,175 C 20,155 35,130 70,130 Z";

// All 8 nodes evenly on the top line (y=130)
const nodeX = [90, 200, 310, 420, 530, 640, 740, 830];
const NODE_Y = 130;

/* ── 15 pre-baked particles — pure SVG animateMotion + CSS fade lifecycle ── */
const PARTICLE_COLORS = ["#4ECDC4","#F4B8C8","#F5C542","#818CF8","#34D399","#E87080","#60A5FA","#C084FC"];

const particles = Array.from({ length: 15 }, (_, i) => {
  const orbitDur = 5 + (i % 7) * 1.4;     // 5s~14.8s per lap — faster particles exist
  const laps = 2 + (i % 3);               // 2~4 laps visible
  const lifeDur = orbitDur * laps;         // total CSS animation cycle
  const delay = i * 2.6;                   // stagger entry
  return {
    color: PARTICLE_COLORS[i % PARTICLE_COLORS.length],
    orbitDur: `${orbitDur.toFixed(1)}s`,
    lifeDur: `${lifeDur.toFixed(1)}s`,
    delay: `${delay.toFixed(1)}s`,
    beginOffset: `${(-i * 1.3).toFixed(1)}s`,  // spread along track initially
  };
});

const AUTO_CYCLE_MS = 2750;

function RacingTrack({
  activeStage,
  onSelect,
}: {
  activeStage: number;
  onSelect: (id: number) => void;
}) {
  return (
    <div className="w-full overflow-x-auto -mx-6 px-6 pb-2">
      <svg viewBox="0 0 920 310" className="w-full min-w-[600px]" style={{ maxHeight: 360 }}>
        <defs>
          <filter id="agent-glow" x="-100%" y="-100%" width="300%" height="300%">
            <feGaussianBlur stdDeviation="4" result="blur" />
            <feMerge>
              <feMergeNode in="blur" />
              <feMergeNode in="SourceGraphic" />
            </feMerge>
          </filter>
        </defs>

        {/* Track surface + outline */}
        <path d={TRACK_PATH} fill="none" stroke="white" strokeOpacity={0.025} strokeWidth={55} />
        <path d={TRACK_PATH} fill="none" stroke="white" strokeOpacity={0.12} strokeWidth={1.5} />
        <path
          d="M 85,148 L 835,148 C 858,148 868,160 868,175 C 868,190 858,202 835,202 L 85,202 C 62,202 52,190 52,175 C 52,160 62,148 85,148 Z"
          fill="none" stroke="white" strokeOpacity={0.025} strokeWidth={1} strokeDasharray="4 8"
        />

        {/* Return lane label */}
        <text x={460} y={216} textAnchor="middle" fill="white" fillOpacity={0.18} fontSize={10} fontFamily="ui-monospace, monospace">
          ← next task from kanban
        </text>

        {/* ── Kanban state bar (top) ── */}
        <line x1={90} y1={90} x2={530} y2={90} stroke="#F4B8C8" strokeOpacity={0.08} strokeWidth={16} strokeLinecap="round" />
        <text x={310} y={86} textAnchor="middle" fill="#F4B8C8" fillOpacity={0.45} fontSize={12} fontFamily="ui-monospace, monospace" fontWeight={700}>In Progress</text>
        <line x1={530} y1={90} x2={740} y2={90} stroke="#4ECDC4" strokeOpacity={0.08} strokeWidth={16} strokeLinecap="round" />
        <text x={635} y={86} textAnchor="middle" fill="#4ECDC4" fillOpacity={0.45} fontSize={12} fontFamily="ui-monospace, monospace" fontWeight={700}>In Review</text>
        <text x={830} y={86} textAnchor="middle" fill="#F5C542" fillOpacity={0.45} fontSize={12} fontFamily="ui-monospace, monospace" fontWeight={700}>Done</text>

        {/* ── GitFlow bar (bottom) ── */}
        <text x={460} y={270} textAnchor="middle" fill="#C084FC" fillOpacity={0.25} fontSize={10} fontFamily="ui-monospace, monospace" letterSpacing="0.08em">
          feature/xxx → PR → develop → main
        </text>

        {/* ── Racing particles (rendered FIRST = behind nodes) ── */}
        {particles.map((p, i) => (
          <g
            key={i}
            style={{
              animation: `particle-life ${p.lifeDur} ease-in-out ${p.delay} infinite`,
              opacity: 0,
            }}
          >
            <circle r={7} fill={p.color} fillOpacity={0.2} filter="url(#agent-glow)">
              <animateMotion dur={p.orbitDur} repeatCount="indefinite" path={TRACK_PATH} begin={p.beginOffset} />
            </circle>
            <circle r={3} fill={p.color} fillOpacity={0.85}>
              <animateMotion dur={p.orbitDur} repeatCount="indefinite" path={TRACK_PATH} begin={p.beginOffset} />
            </circle>
          </g>
        ))}

        {/* ── Stage nodes (rendered LAST = in front of agents) ── */}
        {stages.map((s, i) => {
          const x = nodeX[i];
          const isActive = activeStage === s.id;
          return (
            <g key={s.id} style={{ cursor: "pointer" }} onClick={() => onSelect(s.id)}>
              {isActive && (
                <circle cx={x} cy={NODE_Y} r={24} fill="none" stroke={s.color} strokeOpacity={0.2}>
                  <animate attributeName="r" values="22;28;22" dur="2s" repeatCount="indefinite" />
                  <animate attributeName="stroke-opacity" values="0.2;0.06;0.2" dur="2s" repeatCount="indefinite" />
                </circle>
              )}
              {/* Solid background circle — blocks agents passing behind */}
              <circle cx={x} cy={NODE_Y} r={20} fill="#0B1628" />
              <circle
                cx={x} cy={NODE_Y} r={18}
                fill="#0A0F1A" stroke={s.color}
                strokeWidth={isActive ? 1.5 : 0.6}
                strokeOpacity={isActive ? 0.6 : 0.12}
                style={{ transition: "all 0.3s" }}
              />
              <text
                x={x} y={NODE_Y + 1}
                textAnchor="middle" dominantBaseline="central"
                fill={s.color} fontSize={11}
                fontFamily="ui-monospace, monospace" fontWeight={700}
                opacity={isActive ? 1 : 0.35}
              >
                {s.id}
              </text>
              {/* Label below node */}
              <text x={x} y={NODE_Y + 36} textAnchor="middle" fill={s.color} fillOpacity={isActive ? 0.7 : 0.2} fontSize={11} fontFamily="ui-monospace, monospace" fontWeight={600}>
                {s.label}
              </text>
              <text x={x} y={NODE_Y + 50} textAnchor="middle" fill={s.color} fillOpacity={isActive ? 0.35 : 0.1} fontSize={10} fontFamily="ui-monospace, monospace">
                {s.sub}
              </text>
            </g>
          );
        })}
      </svg>
    </div>
  );
}

/* ── Component Summary ── */
const components = [
  { label: "CLAUDE.md", sub: "CANNOT 23 / CAN 6", color: "#818CF8", badge: "SOT" },
  { label: "progress.md", sub: "5컬럼 칸반", color: "#F4B8C8", badge: "kanban" },
  { label: "21 Skills", sub: "YAML trigger 주입", color: "#F5C542", badge: "inject" },
  { label: "45 Hooks", sub: "4단계 성숙도", color: "#4ECDC4", badge: "event" },
  { label: "CI 5-Gate", sub: "Pre + Post 래칫", color: "#34D399", badge: "gate" },
  { label: "Worktree", sub: "malloc / free", color: "#C084FC", badge: "isolation" },
];

export function ScaffoldSection() {
  const [activeStage, setActiveStage] = useState(0);
  const [autoCycle, setAutoCycle] = useState(true);
  const containerRef = useRef<HTMLDivElement>(null);
  const [isVisible, setIsVisible] = useState(false);

  // IntersectionObserver for auto-cycle
  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const obs = new IntersectionObserver(([e]) => setIsVisible(e.isIntersecting), { threshold: 0.2 });
    obs.observe(el);
    return () => obs.disconnect();
  }, []);

  // Auto-cycle synced with Agent C (yellow, 22s / 8 = 2.75s per stage)
  useEffect(() => {
    if (!isVisible || !autoCycle) return;
    const interval = setInterval(() => {
      setActiveStage((p) => (p + 1) % 8);
    }, AUTO_CYCLE_MS);
    return () => clearInterval(interval);
  }, [isVisible, autoCycle]);

  function handleManualSelect(id: number) {
    setAutoCycle(false);
    setActiveStage(id);
    // Resume auto-cycle after 8s of inactivity
    setTimeout(() => setAutoCycle(true), 8000);
  }

  const detail = stageDetails[activeStage];
  const stageColor = stages[activeStage].color;

  return (
    <section ref={containerRef} className="relative py-28 sm:py-36 px-4 sm:px-6">
      <div className="max-w-5xl mx-auto">
        <ScrollReveal>
          <p className="text-sm font-mono font-bold text-[#818CF8]/60 uppercase tracking-[0.25em] mb-3">
            Scaffold
          </p>
          <h2 className="text-3xl sm:text-4xl font-bold tracking-tight text-white/90 mb-4">
            코드가 아닌 제어 계층
          </h2>
          <p className="text-sm sm:text-base text-[#8B9CC0] max-w-xl mb-10 leading-relaxed">
            칸반 등록부터 Worktree 정리까지 8단계.
            복수의 에이전트가 이 트랙을 동시에 순환하며, 각 관문을 통과해야 다음 단계로 진행합니다.
          </p>
        </ScrollReveal>

        {/* ── Racing Track ── */}
        <ScrollReveal delay={0.1}>
          <RacingTrack activeStage={activeStage} onSelect={handleManualSelect} />
        </ScrollReveal>

        {/* ── Active stage detail (auto-switches with Agent C) ── */}
        <div
          className="rounded-xl border px-5 sm:px-6 py-4 sm:py-5 transition-all duration-500 mt-4 mb-8 sm:mb-10"
          style={{
            borderColor: `${stageColor}20`,
            background: `linear-gradient(135deg, ${stageColor}06, transparent 60%)`,
          }}
        >
          <div className="flex items-center gap-3 mb-2">
            <span
              className="w-7 h-7 rounded-md flex items-center justify-center text-xs font-mono font-bold"
              style={{ color: stageColor, background: `${stageColor}12` }}
            >
              {activeStage}
            </span>
            <span className="font-semibold text-sm" style={{ color: `${stageColor}D0` }}>
              {detail.title}
            </span>
          </div>
          <p className="text-sm text-[#8B9CC0] leading-relaxed mb-3">
            {detail.result}
          </p>
          <div className="flex flex-wrap gap-3 sm:gap-4 text-[11px] font-mono">
            <div>
              <span className="text-[#F4B8C8]/40 mr-1.5">KANBAN</span>
              <span className="text-[#F4B8C8]/70">{detail.kanban}</span>
            </div>
            <div>
              <span className="text-[#C084FC]/40 mr-1.5">GIT</span>
              <span className="text-[#C084FC]/70">{detail.git}</span>
            </div>
          </div>
        </div>

        {/* ── Component grid ── */}
        <ScrollReveal delay={0.2}>
          <div className="grid grid-cols-2 sm:grid-cols-3 gap-2 sm:gap-3">
            {components.map((c) => (
              <div
                key={c.label}
                className="flex items-center gap-2 sm:gap-3 px-3 sm:px-4 py-2.5 sm:py-3 rounded-xl border border-white/[0.04] hover:border-white/[0.08] transition-colors duration-300"
                style={{ background: `linear-gradient(135deg, ${c.color}03, transparent 50%)` }}
              >
                <span
                  className="shrink-0 px-1.5 py-0.5 rounded text-[10px] font-mono font-bold uppercase"
                  style={{ color: c.color, background: `${c.color}10`, border: `1px solid ${c.color}18` }}
                >
                  {c.badge}
                </span>
                <div>
                  <div className="text-xs sm:text-sm font-semibold text-white/80">{c.label}</div>
                  <div className="text-[10px] sm:text-xs text-[#5A6A8A]">{c.sub}</div>
                </div>
              </div>
            ))}
          </div>
        </ScrollReveal>
      </div>
    </section>
  );
}
