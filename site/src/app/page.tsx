import Link from "next/link";
import { GEODE_CUMULATIVE_KO } from "@/data/geode/sot";

/**
 * GEODE site landing — /geode/
 *
 * Two cards: Portfolio (case-study narrative) and Docs (reference manual).
 * About (the person behind GEODE) and Works (other projects) sit below.
 *
 * Matches the chapter wireframe Sprint 1 landed earlier:
 * the portfolio card leads with the master neologism, the docs card
 * leads with what is generated from the codebase.
 */

const primary = [
  {
    href: "/portfolio",
    eyebrow: "포트폴리오",
    eyebrowEn: "Portfolio",
    title: "Why we built GEODE — a self-hosting agent harness.",
    titleKo: "GEODE는 왜, 무엇인가. 스스로를 빌드하는 자율 에이전트 하네스.",
    body:
      "Karpathy의 LLM-OS 다이어그램을 코드로 옮긴 한 가지 답. 같은 하네스 위에서 두 도메인이 검증됐고, 그 하네스를 빌드하는 라인도 같은 규율을 씁니다.",
    accent: "var(--acc-artifact)",
  },
  {
    href: "/docs",
    eyebrow: "공식 문서",
    eyebrowEn: "Documentation",
    title: "Reference for every layer, hook, and tool.",
    titleKo: "4-계층 · 58 훅 · 57 도구 전수 참조.",
    body:
      "코드베이스에서 추출된 사람이 큐레이팅한 내러티브. 아키텍처, 런타임, 하네스, 플러그인, 검증 — 현재 main 브랜치 기준.",
    accent: "var(--acc-line)",
  },
];

const secondary = [
  {
    href: "/about",
    label: "About",
    note: "Jihwan Ryu. 개인 작업과 프리랜서 작업 인덱스.",
  },
  {
    href: "/works/reode",
    label: "Works · REODE",
    note: "GEODE v0.12 fork. 자율 코드 마이그레이션 사례.",
  },
];

export default function Home() {
  return (
    <main className="min-h-screen bg-[var(--paper)] text-[var(--ink)] px-6 py-24">
      <div className="max-w-3xl mx-auto">
        {/* Header */}
        <header className="mb-16">
          <span className="font-mono text-[11px] tracking-[0.18em] uppercase text-[var(--ink-3)]">
            GEODE
          </span>
          <h1 className="mt-6 font-display tracking-tight text-[clamp(3rem,8vw,5rem)] leading-[1.02] font-semibold text-[var(--ink)]">
            GEODE
          </h1>
          <p className="mt-4 font-display text-[clamp(1.1rem,2vw,1.4rem)] text-[var(--ink-1)] leading-snug">
            스스로를 빌드하는 자율 에이전트 하네스.
          </p>
          <p className="mt-2 font-display text-[clamp(0.95rem,1.6vw,1.1rem)] text-[var(--ink-3)] leading-snug">
            A self-hosting agent harness for autonomous execution.
          </p>
          <p className="mt-6 font-mono text-[12px] text-[var(--ink-3)]">
            {GEODE_CUMULATIVE_KO}
          </p>
        </header>

        {/* Primary cards: Portfolio + Docs */}
        <section className="mb-16">
          <div className="space-y-3">
            {primary.map((card) => (
              <Link
                key={card.href}
                href={card.href}
                className="block rounded-lg border border-[var(--rule)] hover:border-[var(--ink-3)] p-6 transition-colors group"
              >
                <div
                  className="text-[10px] font-mono uppercase tracking-[0.22em] mb-2"
                  style={{ color: card.accent }}
                >
                  {card.eyebrow} · {card.eyebrowEn}
                </div>
                <h2 className="font-display font-semibold text-[var(--ink-1)] text-xl md:text-2xl leading-snug group-hover:text-[var(--ink)] mb-2">
                  {card.titleKo}
                </h2>
                <p className="text-[14px] text-[var(--ink-2)] leading-relaxed">
                  {card.body}
                </p>
              </Link>
            ))}
          </div>
        </section>

        {/* Secondary: About + Works */}
        <section className="mb-20">
          <div className="text-[10px] font-mono uppercase tracking-[0.22em] text-[var(--ink-3)] mb-4">
            그 외
          </div>
          <ul className="divide-y divide-[var(--rule)]">
            {secondary.map((row) => (
              <li key={row.href}>
                <Link
                  href={row.href}
                  className="flex items-baseline gap-4 py-3 group"
                >
                  <span className="font-mono text-[12px] text-[var(--ink-1)] group-hover:text-[var(--acc-artifact)] transition-colors w-40 shrink-0">
                    {row.label}
                  </span>
                  <span className="text-[13px] text-[var(--ink-2)] leading-relaxed">
                    {row.note}
                  </span>
                </Link>
              </li>
            ))}
          </ul>
        </section>

        {/* Footer */}
        <footer className="pt-8 border-t border-[var(--rule)] flex flex-col gap-4">
          <div className="flex flex-wrap gap-2">
            {[
              { label: "GitHub", href: "https://github.com/mangowhoiscloud/geode" },
              { label: "Dev Blog", href: "https://rooftopsnow.tistory.com/category/Harness" },
              { label: "YouTube", href: "https://youtube.com/@mango_fr" },
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
            github.com/mangowhoiscloud
          </div>
        </footer>
      </div>
    </main>
  );
}
