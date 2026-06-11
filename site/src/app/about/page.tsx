import Link from "next/link";

type Entry = {
  id: string;
  href?: string;
  external?: boolean;
  clickable?: boolean;
  range: string;
  status: string;
  titleKo: string;
  taglineKo: string;
  bodyKo?: string;
  bulletsKo?: string[];
  chips: string[];
  accent: string;
};

const personal: Entry[] = [
  {
    id: "geode",
    href: "/portfolio",
    range: "2026.03 → 진행 중",
    status: "Self-evolving agent · solo",
    titleKo: "GEODE",
    taglineKo: "스스로를 고쳐 쓰는 자율 에이전트 하네스",
    bodyKo:
      "비-파라메트릭 계열의 자기 진화 에이전트입니다. 모델 가중치는 건드리지 않고, 자기 자신을 둘러싼 스캐폴드, 즉 시스템 프롬프트와 도구 정책, 작업 분해와 반성 루프를 직접 바꿔 나아집니다. 안쪽의 agentic 루프가 작업을 처리하고, 바깥쪽 루프가 그 시스템을 다듬습니다. 변화의 적합도는 능력 벤치마크가 아니라 적대적 안전 감사로 측정하고, 핵심 안전 차원에는 하한선을 둬 후퇴하는 변화는 거부합니다.",
    chips: ["Non-parametric self-evolution", "Adversarial safety audit", "Two loops", "Co-evolved seeds", "LangGraph"],
    accent: "var(--acc-artifact)",
  },
  {
    id: "eco2",
    href: "",  // no dedicated page on this site; renders as non-link
    range: "2025.10 → 2026.02",
    status: "SeSACTHON 2025 Excellence",
    titleKo: "Eco²",
    taglineKo: "멀티에이전트 재활용 챗봇 백엔드",
    bodyKo:
      "5인 팀 MVP에서 백엔드와 인프라를 단독으로 맡으면서, Cursor 기반 스캐폴드로 LLM을 “생산과 개발의 체계”로 처음 운용해 본 프로젝트입니다. 본선 이후 약 3개월간 단독으로 고도화하면서 Chat 도메인을 LangGraph 멀티 에이전트로 재구성해 사용자 입장에서의 Agent 사용성을 끌어올렸고, LLM × 2 + Rule-based 파이프라인을 부하 테스트로 검증했습니다. EFK · Prometheus · Grafana · Jaeger 관측 스택은 직접 세웠습니다. GEODE의 직접적인 발판이 된 작업입니다.",
    chips: [
      "Cursor + Scaffold (LLM as dev system)",
      "Chat Agent UX",
      "LangGraph multi-agent",
      "Event Bus tiers",
      "Swiss Cheese eval",
      "K8s autoscaling",
    ],
    accent: "var(--acc-line)",
  },
];

const freelance: Entry[] = [
  {
    id: "kiki",
    clickable: false,
    range: "2026.04 → 2026.05.16 (@ pinxlab)",
    status: "Legacy maintenance orchestration · Paperclip plugin",
    titleKo: "Kiki",
    taglineKo: "레거시 시스템 유지보수 + Slack 시그널 기반 자동화 향상 오케스트레이션",
    bulletsKo: [
      "타겟은 TTree 근태관리 레거시 시스템(Java / Spring · 19 도메인 4 그룹: attendance · organization · reporting · communication)입니다. 한국 근로기준법 56조 등 규제 제약과 야간 22:00 분기, 부서 N+1 쿼리 같은 실제 프로덕션 패턴 위에서 에이전트가 explore-before-act로 동작합니다.",
      "Slack 채널 관측에서 사용자 시그널만 추출하고(원문 미수집), Profile Merge(confidence scoring + temporal decay) → Directive Generation → Paperclip Company Skills API PATCH로 이어지는 파이프라인으로 에이전트 시스템 프롬프트에 주입해 자동화 정도를 점진적으로 올립니다.",
      "Hub-Spoke 에이전트 토폴로지(Engineering + Finance). CTO 라우터 → PO · Planner → Dual Squad(Squad 1: attendance · organization / Squad 2: reporting · communication) Lead · Dev · QA. Skill + event handler + Slack intent command 운용.",
      "Crack pipeline guardrails(C1.C21)가 \"YAML은 LLM에 대한 권고일 뿐\"이라는 전제 위에서 phase skip · scorecard 누락 · anti-deception을 이벤트 단위로 검출하고 자동 되돌립니다. 운영 안전선은 Per-agent + company-wide circuit breaker로 묶입니다.",
      "자매 코드베이스로 kiki-appmaker가 별도 운영됩니다(아래 항목). 2026-04-29 boundary 확정. Kiki는 정체성·플러그인·MCP·스킬·시그널 수집을 담당합니다.",
    ],
    chips: [
      "Legacy TTree maintenance",
      "Slack signal → directive",
      "Hub-Spoke 12 agents",
      "Dual squad",
      "Crack guardrails",
      "Paperclip Skills API",
    ],
    accent: "var(--acc-line)",
  },
  {
    id: "kiki-appmaker",
    clickable: false,
    range: "2026.04 → 2026.05.16 (@ pinxlab)",
    status: "Factory-style app production pipeline · sister of Kiki",
    titleKo: "Kiki AppMaker",
    taglineKo: "공장형 앱 생성 PDCA 오케스트레이션 파이프라인",
    bulletsKo: [
      "사용자 한 줄 프롬프트에서 출발해 PM Lead(SPEC) → CDO Lead(DESIGN_SYSTEM 9-섹션) → CTO Lead(구현 + SELF_CHECK) → QA Lead(QA_REPORT) → 자동 판정(합격 → 배포 / 불합격 → Do 최대 3회 복귀)을 1회전 돌리는 PDCA host-mode 워크플로우입니다.",
      "Production path는 User issue → CTO triage → PO + Planner SPEC → P4 검증 → Designer DESIGN → Lead FIFO → Developer → QA(최대 3 재작업) → Lead SCORECARD → PO ACCEPTANCE → CTO Release → DevOps 배포로 단계 스킵을 막습니다. 두 가지 모드(Paperclip claude_local 컨테이너 / 호스트 maintenance)를 분리합니다.",
      "external-company provisioning(Lead / Worker / Specialty 역할)과 install workspace 단계(core paperclip / kiki-patches rebase / plugins / team / dashboards)를 묶습니다. bkit automation L4(Full-Auto)는 가드레일 위에서 동작합니다.",
      "Design은 awesome-design-md 컬렉션을 npx getdesign으로 설치한 뒤 DESIGN_SYSTEM.md 9섹션을 커스터마이징합니다. 기본 스택은 Next.js App Router + MySQL + standalone.",
      "PIN system match-3 game series(PIN-36 daily challenge → PIN-44 daily seed + share URL → PIN-48 M2 howto-gen → PIN-59 / 60 audio + sprite → M3-A / B / C)는 manager-facing pitch demo로 운용합니다.",
    ],
    chips: [
      "PDCA host-mode",
      "Agent provisioning",
      "Staged install workspace",
      "awesome-design-md",
      "bkit L4 Full-Auto",
      "PIN match-3 demo",
    ],
    accent: "var(--acc-artifact)",
  },
];

const now = [
  { date: "2026-05-03", body: "포트폴리오 재구성. Eco² (SeSACTHON 2025 Excellence) · Kiki (TTree 레거시 유지보수) · Kiki AppMaker (공장형 PDCA) 세 작업물 합류, 개인 / pinxlab 프리랜서 분리." },
  { date: "2026-05-02", body: "Crumb 최종 설계 lock. 4-actor(Coord / Planner Lead / Engineering Lead / Builder.fallback) + Engineering Lead 내부 CourtEval(Grader · Critic · Defender · Re-grader, ACL 2025) + kind 단위 transcript JSONL + OpenTelemetry GenAI alias. GEODE messages cache_control 머지, CHANGELOG를 챕터 타임라인으로 재구성." },
  { date: "2026-05-01", body: "Bagelcode 신작팀 과제 전형 Crumb 착수(마감 2026-05-03 23:59 KST). PDCA chain 토폴로지를 ICML 2025 §F(Resilience, chain 10.5% 저하) 근거로 폐기하고 Hub-Ledger-Spoke로 재정렬. Phaser 3.80 single-file ≤ 60KB game.html(LLM 첫시도 성공률 94%)로 게임 스택 lock. Frontier 사료 80+종(orchestration · caching · XML · production · mobile-game · observability)으로 의사결정을 학술 grounding." },
];

const recognition = [
  {
    label: "SeSACTHON 2025 Excellence",
    detail: "Eco² · MVP 백엔드/인프라 단독 + 본선 이후 단독 고도화 (2025.10 → 2026.02)",
  },
  {
    label: "Furiosa AI · SWE, Agent System",
    detail: "서류 합격, 면접 탈락",
  },
  {
    label: "Nexon AI Engineer 면접 진출",
    detail: "코딩 과제 합격, 면접 탈락. GEODE의 시작점이 된 전형",
  },
  {
    label: "기술 블로그 / YouTube",
    detail: "rooftopsnow.tistory.com / Harness 카테고리",
  },
];

const influences = [
  { name: "Andrej Karpathy", note: "LLM-OS sketch (Intro to LLMs, 2023), autoresearch ratchet discipline (P1 to P10)" },
  { name: "Anthropic Claude Code", note: "while(tool_use) primitive, hook system, CLAUDE.md 스캐폴드 패턴" },
  { name: "OpenClaw", note: "Policy Chain, Lane Queue, Session 격리, Plugin discovery" },
  { name: "Hermes Agent", note: "system_and_3 cache_control, 멀티채널 personal agent 패턴" },
];

function ProjectEntry({ e }: { e: Entry }) {
  const inner = (
    <div className="grid grid-cols-1 sm:grid-cols-[170px_1fr] gap-x-8 gap-y-3 py-7">
      {/* Left rail — period + status */}
      <div>
        <div
          className="font-mono text-[11px] tracking-[0.04em] mb-1.5"
          style={{ color: e.accent }}
        >
          {e.range}
        </div>
        <div className="font-mono text-[10.5px] text-[var(--ink-3)] leading-snug">
          {e.status}
        </div>
      </div>

      {/* Body */}
      <div>
        <h3
          className="font-display text-[26px] font-semibold tracking-tight mb-1 leading-tight"
          style={{ color: e.accent }}
        >
          {e.titleKo}
          <span className="ml-2 font-sans text-[14px] font-normal text-[var(--ink-1)]">
            {e.taglineKo}
          </span>
        </h3>
        {e.bodyKo && (
          <p className="text-[14px] text-[var(--ink-2)] leading-[1.75] mb-3 max-w-2xl">
            {e.bodyKo}
          </p>
        )}
        {e.bulletsKo && (
          <ul className="text-[14px] text-[var(--ink-2)] leading-[1.7] mb-3 max-w-2xl space-y-1.5">
            {e.bulletsKo.map((b, i) => (
              <li key={i} className="flex gap-2.5">
                <span className="shrink-0 text-[var(--ink-3)] font-mono pt-0.5" style={{ color: e.accent }}>
                  ·
                </span>
                <span>{b}</span>
              </li>
            ))}
          </ul>
        )}
        <div className="flex flex-wrap gap-1.5">
          {e.chips.map((c) => (
            <span
              key={c}
              className="px-2 py-0.5 rounded text-[10.5px] font-mono text-[var(--ink-2)] bg-[var(--paper-2)] border border-[var(--rule)]"
            >
              {c}
            </span>
          ))}
        </div>
      </div>
    </div>
  );

  const wrapBase = "block border-b border-[var(--rule)] last:border-b-0";
  if (e.clickable === false || !e.href) {
    return <div className={wrapBase}>{inner}</div>;
  }
  if (e.external) {
    return (
      <a
        href={e.href}
        target="_blank"
        rel="noreferrer"
        className={`${wrapBase} group hover:bg-[var(--paper-2)]/40 transition-colors`}
      >
        {inner}
      </a>
    );
  }
  return (
    <Link
      href={e.href}
      className={`${wrapBase} group hover:bg-[var(--paper-2)]/40 transition-colors`}
    >
      {inner}
    </Link>
  );
}

export default function Home() {
  return (
    <main className="min-h-screen bg-[var(--paper)] text-[var(--ink)] px-6 py-24">
      <div className="max-w-3xl mx-auto">
        {/* Header */}
        <header className="mb-20">
          <span className="font-mono text-[11px] tracking-[0.18em] uppercase text-[var(--ink-3)]">
            Portfolio · 2026-05-03
          </span>
          <h1 className="mt-6 font-display tracking-tight text-[clamp(3rem,7vw,4.5rem)] leading-[1.05] font-semibold text-[var(--ink)]">
            Jihwan Ryu
          </h1>
          <p className="mt-3 font-display text-[clamp(1.1rem,2vw,1.4rem)] text-[var(--ink-1)]">
            Backend · Agentic AI · Harness Engineering
          </p>
          <p className="mt-6 max-w-2xl text-[16px] leading-[1.75] text-[var(--ink-2)]">
            자율 에이전트를 컴퓨팅의 운영체제로 다루는 작업을 하고 있습니다.
            아래에 개인 작업과 프리랜서로 수행한 작업을 분리해서 정리해 두었습니다.
          </p>
        </header>

        {/* Now */}
        <section className="mb-20">
          <div className="flex items-baseline gap-3 mb-6">
            <span className="font-mono text-[10px] uppercase tracking-[0.18em] text-[var(--ink-3)]">
              § Now
            </span>
            <span className="font-mono text-[10px] text-[var(--ink-3)]">
              현재 작업
            </span>
          </div>
          <ul className="space-y-3">
            {now.map((entry, i) => (
              <li key={i} className="flex gap-4 text-[14px]">
                <span className="font-mono text-[12px] text-[var(--ink-3)] shrink-0 w-24 pt-0.5">
                  {entry.date}
                </span>
                <span className="text-[var(--ink-2)] leading-relaxed">
                  {entry.body}
                </span>
              </li>
            ))}
          </ul>
        </section>

        {/* Selected Work — split into Personal × Freelance, ledger layout */}
        <section className="mb-20">
          <div className="flex items-baseline gap-3 mb-2">
            <span className="font-mono text-[10px] uppercase tracking-[0.18em] text-[var(--ink-3)]">
              § Selected Work
            </span>
            <span className="font-mono text-[10px] text-[var(--ink-3)]">
              주요 작업물
            </span>
          </div>

          {/* Personal */}
          <div className="mt-8">
            <div className="flex items-baseline gap-3 pb-3 border-b border-[var(--rule)]">
              <span className="font-display text-[15px] text-[var(--ink-1)] font-semibold tracking-tight">
                개인 프로젝트
              </span>
              <span className="font-mono text-[10px] text-[var(--ink-3)] tracking-[0.08em]">
                Personal · solo
              </span>
            </div>
            <div className="divide-y divide-[var(--rule)]">
              {personal.map((e) => (
                <ProjectEntry key={e.id} e={e} />
              ))}
            </div>
          </div>

          {/* Freelance @ pinxlab */}
          <div className="mt-12">
            <div className="flex items-baseline gap-3 pb-3 border-b border-[var(--rule)]">
              <span className="font-display text-[15px] text-[var(--ink-1)] font-semibold tracking-tight">
                pinxlab · 프리랜서
              </span>
              <span className="font-mono text-[10px] text-[var(--ink-3)] tracking-[0.08em]">
                Freelance contract · solo IC
              </span>
            </div>
            <div className="divide-y divide-[var(--rule)]">
              {freelance.map((e) => (
                <ProjectEntry key={e.id} e={e} />
              ))}
            </div>
          </div>
        </section>

        {/* Recognition */}
        <section className="mb-20">
          <div className="flex items-baseline gap-3 mb-6">
            <span className="font-mono text-[10px] uppercase tracking-[0.18em] text-[var(--ink-3)]">
              § Recognition
            </span>
            <span className="font-mono text-[10px] text-[var(--ink-3)]">
              수상 / 활동
            </span>
          </div>
          <ul className="space-y-3">
            {recognition.map((r, i) => (
              <li key={i} className="text-[14px] leading-relaxed">
                <div className="text-[var(--ink-1)]">{r.label}</div>
                <div className="text-[13px] text-[var(--ink-3)] mt-0.5">
                  {r.detail}
                </div>
              </li>
            ))}
          </ul>
        </section>

        {/* Influences */}
        <section className="mb-20">
          <div className="flex items-baseline gap-3 mb-6">
            <span className="font-mono text-[10px] uppercase tracking-[0.18em] text-[var(--ink-3)]">
              § Influences
            </span>
            <span className="font-mono text-[10px] text-[var(--ink-3)]">
              참고한 작업
            </span>
          </div>
          <ul className="space-y-3">
            {influences.map((inf, i) => (
              <li key={i} className="text-[14px] leading-relaxed">
                <span className="text-[var(--ink-1)] font-medium">
                  {inf.name}
                </span>
                <span className="text-[var(--ink-3)] mx-2">·</span>
                <span className="text-[var(--ink-2)]">{inf.note}</span>
              </li>
            ))}
          </ul>
        </section>

        {/* Footer */}
        <footer className="pt-8 border-t border-[var(--rule)] flex flex-col gap-5">
          <div className="flex flex-wrap gap-2">
            {[
              { label: "GitHub",   href: "https://github.com/mangowhoiscloud" },
              { label: "Blog",     href: "https://rooftopsnow.tistory.com/category/Harness" },
              { label: "YouTube",  href: "https://youtube.com/@mango_fr" },
              { label: "LinkedIn", href: "https://www.linkedin.com/in/jihwan-ryu-b6b04a202/" },
            ].map((b) => (
              <a
                key={b.label}
                href={b.href}
                target="_blank"
                rel="noreferrer"
                className="inline-flex items-center px-2.5 py-1 rounded border border-[var(--rule)] bg-[var(--paper-2)] font-mono text-[11px] text-[var(--ink-2)] hover:border-[var(--acc-artifact)] hover:text-[var(--acc-artifact)] transition-colors"
              >
                {b.label}
              </a>
            ))}
          </div>

          <div className="text-[11px] font-mono text-[var(--ink-3)]">
            last updated 2026-05-03 · github.com/mangowhoiscloud
          </div>
        </footer>
      </div>
    </main>
  );
}
