import type { Metadata } from "next";
import Link from "next/link";

const updatedAt = "2026-09-14";
const title = "Jihwan Ryu — Backend · Agent Runtime";
const description =
  "류지환의 클라우드 스토리지 개발 경력, Eco²와 GEODE의 런타임·평가 작업, 최근 채용 진행 기록입니다.";

export const metadata: Metadata = {
  title,
  description,
  alternates: { canonical: "https://mangowhoiscloud.github.io/geode/about/" },
  openGraph: {
    title,
    description,
    url: "https://mangowhoiscloud.github.io/geode/about/",
    type: "profile",
  },
};

const linkStyle =
  "inline-flex min-h-10 items-center text-[var(--acc-aqua)] underline decoration-[var(--rule)] underline-offset-4 hover:decoration-current focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-[var(--acc-aqua)]";

const projects = [
  {
    name: "GEODE",
    scope: "개인 오픈소스 · 2026",
    role: "작업을 실행하고 검증하는 에이전트 런타임",
    body: "ReAct의 도구 호출·관측과 Reflexion의 검토·수정 경로를 구현합니다. 세션, 도구 권한, 재시도 경계와 토큰·캐시 회계를 함께 다룹니다. 작업을 수행하는 core 런타임과 평가·스캐폴드 탐색을 분리해, 일반 요청 실행이 곧 자기 수정이 되지 않도록 설계합니다.",
    links: [
      { label: "런타임 구조", href: "/docs/architecture/agentic-loop" },
      { label: "소스 코드", href: "https://github.com/mangowhoiscloud/geode" },
    ],
  },
  {
    name: "Eco² · 이코에코",
    scope: "팀 MVP → 단독 고도화 · 2025.10–2026.02",
    role: "백엔드·인프라 1개월, 이후 제품 고도화 3개월",
    body: "5인 팀의 재활용 서비스에서 백엔드와 인프라를 맡았습니다. 본선 이후에는 혼자 웹·앱을 고도화하며 LangGraph 기반 챗봇, 부하 테스트와 운영 관측을 다뤘습니다. 사용자 요청을 처리하는 서비스부터 배포·운영까지 책임진 경험이 GEODE 개발의 출발점이 됐습니다.",
    links: [{ label: "프로젝트와 설계 기록", href: "https://mangowhoiscloud.github.io/eco2/" }],
  },
  {
    name: "Seed Scenario Generation · SIL",
    scope: "GEODE 평가·탐색 실험",
    role: "평가 시나리오 생성과 스캐폴드 후보 선택",
    body: "AI co-scientist를 참고해 평가 시나리오를 생성하고, Petri로 GEODE의 행동을 평가합니다. autoresearch 방식의 자기개선 실험(SIL)은 이 평가 결과로 프롬프트·행동 정책 후보를 비교합니다. 평가 입력의 생성과 후보 선택을 구분하며, 모델 가중치를 학습하는 작업은 아닙니다.",
    links: [
      { label: "시나리오 생성", href: "/docs/capabilities/seed-pipeline" },
      { label: "SIL 실험 구조", href: "/docs/capabilities/autoresearch" },
    ],
  },
  {
    name: "Crucible",
    scope: "GEODE × tau2 · 외부 탐색 장치",
    role: "동결된 측정 기준으로 후보를 채택하거나 기각",
    body: "후보 생성, GEODE × tau2의 paired 평가, 판정과 private search head 갱신을 연결합니다. 탐색 중인 후보가 평가 기준까지 바꾸지 못하도록 경계를 두고, 실험에서의 후보 채택과 실제 제품 배포 권한을 분리합니다.",
    links: [{ label: "제한형 탐색과 측정 게이트", href: "/docs/capabilities/outer-loop" }],
  },
  {
    name: "Terminal-Bench 2.1",
    scope: "GEODE × Harbor · native Codex 대조",
    role: "같은 모델·effort에서 런타임의 차이 관찰",
    body: "gpt-5.6-sol, max effort와 Harbor를 공통 조건으로 GEODE와 native Codex를 비교했습니다. 성공 여부뿐 아니라 도구 실행, 실패 원인, 사용량·캐시 누락을 분석합니다. 실행 환경의 무효와 에이전트 실패를 구분하며, 일부 유효 실행의 차이를 전체 벤치마크 우위로 일반화하지 않습니다.",
    links: [
      { label: "실험 조건·결과·Replay", href: "/docs/benchmarks/terminal-bench" },
      { label: "공개 평가 아티팩트", href: "https://github.com/mangowhoiscloud/geode-eval-artifacts" },
    ],
  },
];

const recruiting = [
  { period: "2026.08–09", company: "리벨리온", role: "SWE DevOps", progress: "서류 합격", outcome: "면접 탈락" },
  { period: "2026.07–08", company: "LG AI연구원", role: "AI 데이터엔지니어 인턴 · 에이전트 워크플로우", progress: "서류 · 인적성 · 코딩테스트 합격", outcome: "면접 탈락" },
  { period: "2026.07–08", company: "퓨리오사AI", role: "SWE, Compiler (AX)", progress: "서류 합격", outcome: "과제 탈락" },
  { period: "2026.05–06", company: "42dot", role: "AI Engineer (Gleo)", progress: "서류 · 코딩테스트 합격", outcome: "면접 탈락" },
  { period: "2026.04–05", company: "베이글코드", role: "AI 개발자", progress: "서류 합격", outcome: "과제 탈락" },
  { period: "2026.04–05", company: "퓨리오사AI", role: "SWE, Agent System Developer", progress: "서류 합격", outcome: "면접 탈락" },
  { period: "2026.01–03", company: "넥슨", role: "AI Engineer", progress: "서류 · 과제 합격", outcome: "면접 탈락" },
  { period: "2026.01–02", company: "무신사", role: "AI Native", progress: "서류 합격", outcome: "이후 진행하지 않음" },
  { period: "2025.10", company: "Datadog", role: "TSE", progress: "DM 제안 · 2차 면접 진행", outcome: "2차 면접 탈락" },
  { period: "2025.10", company: "토스", role: "DevOps", progress: "DM 제안 · 면접 진행", outcome: "면접 탈락" },
];

export default function AboutPage() {
  return (
    <main className="min-h-screen bg-[var(--paper)] px-6 py-12 text-[var(--ink)] sm:py-20">
      <div className="mx-auto max-w-4xl">
        <nav aria-label="소개 페이지 탐색" className="mb-12 flex flex-wrap gap-x-6 gap-y-1 text-sm">
          <Link href="/" className={linkStyle}>GEODE 홈</Link>
          <a href="#projects" className={linkStyle}>대표 작업</a>
          <a href="#career" className={linkStyle}>경력·학력</a>
          <a href="#recruiting" className={linkStyle}>채용 기록</a>
        </nav>

        <header className="mb-16">
          <p className="font-mono text-xs tracking-widest text-[var(--ink-2)]">
            ABOUT · <time dateTime={updatedAt}>{updatedAt}</time>
          </p>
          <h1 className="mt-5 font-display text-[clamp(3rem,7vw,4.5rem)] leading-tight font-semibold tracking-tight">
            Jihwan Ryu
          </h1>
          <p className="mt-3 text-lg text-[var(--ink-1)]">류지환 · Backend · Cloud · Agent Runtime</p>
          <p className="mt-6 max-w-3xl text-base leading-relaxed text-[var(--ink-2)]">
            클라우드 스토리지의 서버·게이트웨이를 개발했고, Eco²의 백엔드·인프라를 거쳐
            지금은 GEODE를 만들고 있습니다. 에이전트가 실제 환경에서 작업을 끝내는지,
            실패를 어떻게 드러내고 검증할지를 런타임과 평가 도구로 구현합니다.
          </p>
          <p className="mt-4 text-sm leading-relaxed text-[var(--ink-2)]">
            현재는 주로 2–3년차 주니어 또는 인턴 채용을 살펴보고 있습니다.
            아래에는 만든 것과 맡은 범위, 채용 과정의 결과를 구분해 남겼습니다.
          </p>
        </header>

        <section id="projects" aria-labelledby="projects-title" className="mb-16 scroll-mt-8">
          <h2 id="projects-title" className="font-display text-2xl font-semibold tracking-tight">대표 작업</h2>
          <p className="mt-2 mb-6 text-sm text-[var(--ink-2)]">서비스 개발 → 런타임 구현 → 실행 결과의 측정과 개선</p>
          <div className="divide-y divide-[var(--rule)] border-y border-[var(--rule)]">
            {projects.map((project) => (
              <article key={project.name} className="grid gap-3 py-7 sm:grid-cols-[220px_1fr] sm:gap-8">
                <div>
                  <h3 className="font-display text-xl font-semibold text-[var(--acc-artifact)]">{project.name}</h3>
                  <p className="mt-2 text-xs leading-relaxed text-[var(--ink-2)]">{project.scope}</p>
                </div>
                <div>
                  <p className="font-medium text-[var(--ink-1)]">{project.role}</p>
                  <p className="mt-2 text-sm leading-7 text-[var(--ink-2)]">{project.body}</p>
                  <div className="mt-2 flex flex-wrap gap-x-5 text-sm">
                    {project.links.map((link) => (
                      <Link key={link.href} href={link.href} className={linkStyle}>{link.label}</Link>
                    ))}
                  </div>
                </div>
              </article>
            ))}
          </div>
        </section>

        <section id="career" aria-labelledby="career-title" className="mb-16 scroll-mt-8">
          <h2 id="career-title" className="font-display text-2xl font-semibold tracking-tight">경력·학력</h2>
          <div className="mt-6 border-l-2 border-[var(--acc-artifact)] pl-5">
            <p className="font-mono text-xs text-[var(--ink-2)]">2024.12.09–2025.08.31</p>
            <h3 className="mt-2 text-lg font-semibold">Rakuten Symphony Korea</h3>
            <p className="mt-1 text-sm text-[var(--ink-1)]">SWE @ Cloud · 정규직</p>
            <p className="mt-3 text-sm leading-7 text-[var(--ink-2)]">
              Rakuten CNP / Rakuten Object Storage v1.0.0의 스토리지 서버·게이트웨이를 개발했습니다.
              Go 게이트웨이와 내부 gRPC·데이터베이스 경로, 사용자·접근 자격 증명의 생명주기를 다뤘습니다.
            </p>
          </div>
          <dl className="mt-8 grid gap-x-8 gap-y-3 text-sm leading-7 sm:grid-cols-[120px_1fr]">
            <dt className="font-medium">학력</dt>
            <dd className="text-[var(--ink-2)]">부산대학교 정보컴퓨터공학전공 학사 · 2017학번 · 2023.08 졸업</dd>
            <dt className="font-medium">교육</dt>
            <dd className="text-[var(--ink-2)]">카카오테크 부트캠프 · 2024.06–11</dd>
            <dt className="font-medium">자격</dt>
            <dd className="text-[var(--ink-2)]">OPIc IH · 정보처리기사</dd>
            <dt className="font-medium">수상</dt>
            <dd className="text-[var(--ink-2)]">2025 AI 새싹톤 우수상 · Eco² · 181팀 중 4위</dd>
          </dl>
          <details className="mt-8 border-y border-[var(--rule)] py-4">
            <summary className="cursor-pointer py-2 font-medium focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-[var(--acc-aqua)]">
              이전 프리랜서 작업 · pinxlab
            </summary>
            <div className="mt-4 space-y-4 text-sm leading-7 text-[var(--ink-2)]">
              <p className="font-mono text-xs">2026년 상반기 · 프리랜서</p>
              <p><strong className="text-[var(--ink-1)]">Kiki.</strong> 레거시 시스템 유지보수와 Slack 시그널 기반 작업 지시를 연결하는 에이전트 오케스트레이션을 다뤘습니다. Paperclip 기반 역할 분담, 스킬·이벤트 처리와 실행 가드레일을 구성했습니다.</p>
              <p><strong className="text-[var(--ink-1)]">Kiki AppMaker.</strong> 요구사항에서 설계·구현·검증·배포로 이어지는 앱 제작 워크플로우를 구성했습니다. 단계별 산출물과 재작업 판정, 에이전트 작업 환경 설치를 다룬 별도 프로젝트입니다.</p>
              <p>당시 수행한 작업을 요약한 기록이며, 현재 서비스 운영 상태를 뜻하지 않습니다.</p>
            </div>
          </details>
        </section>

        <section id="recruiting" aria-labelledby="recruiting-title" className="mb-16 scroll-mt-8">
          <h2 id="recruiting-title" className="font-display text-2xl font-semibold tracking-tight">채용 진행 기록</h2>
          <p className="mt-3 text-sm leading-7 text-[var(--ink-2)]">
            공개한 재취업 준비 기록을 최근 순으로 정리했습니다. 같은 회사라도 직무가 다르면 별도 전형입니다.
            합격한 중간 단계와 최종 결과를 나누고, 진행하지 않은 전형은 탈락으로 적지 않았습니다.
          </p>
          <p id="recruiting-scroll" className="mt-3 text-xs text-[var(--ink-2)] sm:hidden">표가 화면보다 넓으면 좌우로 스크롤할 수 있습니다.</p>
          <div role="region" aria-label="회사·직무별 채용 진행 결과" aria-describedby="recruiting-scroll" tabIndex={0} className="mt-6 overflow-x-auto focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-[var(--acc-aqua)]">
            <table className="w-full min-w-[720px] border-collapse text-left text-sm leading-6">
              <caption className="pb-3 text-left text-xs text-[var(--ink-2)]">{updatedAt} 기준 · 2025.10–2026.09의 주요 10개 전형</caption>
              <thead className="border-y border-[var(--rule)] bg-[var(--paper-2)] text-[var(--ink-1)]">
                <tr>
                  <th scope="col" className="py-3 pr-4 pl-3 font-medium">기간</th>
                  <th scope="col" className="px-4 py-3 font-medium">회사 · 직무</th>
                  <th scope="col" className="px-4 py-3 font-medium">진행 단계</th>
                  <th scope="col" className="px-4 py-3 font-medium">결과</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[var(--rule)]">
                {recruiting.map((entry) => (
                  <tr key={`${entry.company}-${entry.role}`} className="align-top">
                    <td className="py-4 pr-4 pl-3 font-mono text-xs whitespace-nowrap text-[var(--ink-2)]">{entry.period}</td>
                    <th scope="row" className="max-w-64 px-4 py-4 font-normal">
                      <span className="block font-medium">{entry.company}</span>
                      <span className="mt-1 block text-xs text-[var(--ink-2)]">{entry.role}</span>
                    </th>
                    <td className="px-4 py-4 text-[var(--ink-2)]">{entry.progress}</td>
                    <td className="px-4 py-4 whitespace-nowrap text-[var(--ink-1)]">{entry.outcome}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="mt-4 text-sm leading-7 text-[var(--ink-2)]">
            이 외에도 중소·중견·대기업 SWE 직무에서 서류 탈락을 경험했습니다.
            이 표는 전체 지원 목록이 아니므로 합격률이나 시장 전체의 채용 경향을 계산하는 자료로 쓰지 않습니다.
          </p>
          <div className="mt-2 flex flex-wrap gap-x-5 text-sm">
            <a href="https://www.threads.com/@mangowhois/post/DdLsJuwGX_0" className={linkStyle}>공개 원문 · 경력과 프로젝트</a>
            <a href="https://www.threads.com/@mangowhois/post/DdLsJtnmQWT" className={linkStyle}>공개 원문 · 채용 기록</a>
          </div>
        </section>

        <aside aria-label="설계 참고 자료" className="mb-12 text-sm leading-7 text-[var(--ink-2)]">
          <p>Claude Code의 작업 실행과 스캐폴드, OpenClaw의 세션·큐, Hermes의 컨텍스트 관리,
            Karpathy의 autoresearch를 참고하되 GEODE의 구현·측정 결과와 구분합니다.</p>
          <a href="/geode/docs/reference/external-references" className={linkStyle}>설계 참고 자료와 적용 범위</a>
        </aside>

        <footer className="border-t border-[var(--rule)] pt-6">
          <div className="flex flex-wrap gap-x-6 gap-y-1 text-sm">
            {[
              { label: "GitHub", href: "https://github.com/mangowhoiscloud" },
              { label: "Threads · @mangowhois", href: "https://www.threads.com/@mangowhois" },
              { label: "YouTube", href: "https://youtube.com/@mango_fr" },
              { label: "LinkedIn", href: "https://www.linkedin.com/in/jihwan-ryu-b6b04a202/" },
            ].map((link) => (
              <a key={link.href} href={link.href} className={linkStyle}>{link.label}</a>
            ))}
          </div>
          <p className="mt-5 font-mono text-xs text-[var(--ink-2)]">last updated <time dateTime={updatedAt}>{updatedAt}</time></p>
        </footer>
      </div>
    </main>
  );
}
