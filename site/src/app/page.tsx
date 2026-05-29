import Link from "next/link";

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
    eyebrow: "Portfolio / 포트폴리오",
    title: "GEODE를 왜 만들었나. 스스로를 고쳐 쓰는 에이전트 하네스.",
    body:
      "비-파라메트릭 계열의 자기 진화 에이전트입니다. 모델 가중치는 건드리지 않고, 자기 자신을 둘러싼 스캐폴드를 직접 바꿔 나아갑니다. 변화의 적합도는 적대적 안전 감사로 검증합니다.",
    accent: "var(--acc-artifact)",
  },
  {
    href: "/docs",
    eyebrow: "Docs / 문서",
    title: "모든 layer, hook, tool에 대한 reference.",
    body:
      "코드베이스에서 생성·정리한 architecture, runtime, harness, plugin, verification 문서입니다. 현재 main branch 기준으로 동기화됩니다.",
    accent: "var(--acc-line)",
  },
];

const secondary = [
  {
    href: "/about",
    label: "About / 소개",
    note: "류지환. 개인 작업과 프리랜서 프로젝트 인덱스.",
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
            스스로를 고쳐 쓰는 자율 에이전트 하네스.
          </p>
          <p className="mt-6 max-w-2xl text-[14px] leading-[1.7] text-[var(--ink-2)]">
            GEODE는 모델 가중치를 건드리지 않습니다. 자기 자신을 둘러싼 스캐폴드,
            즉 시스템 프롬프트와 도구 정책, 작업 분해와 반성 루프를 직접 바꿔
            나아집니다. 그 변화의 적합도는 능력 벤치마크가 아니라 적대적 안전
            감사로 측정합니다.
          </p>
          <p className="mt-2 max-w-2xl text-[14px] leading-[1.7] text-[var(--ink-3)]">
            A self-rewriting agent harness. It never updates model weights; it
            mutates the scaffolding around itself and keeps a change only when an
            adversarial safety audit confirms a real gain.
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
                  {card.eyebrow}
                </div>
                <h2 className="font-display font-semibold text-[var(--ink-1)] text-xl md:text-2xl leading-snug group-hover:text-[var(--ink)] mb-2">
                  {card.title}
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
            More
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
