import Link from "next/link";

import { GeodiSprite } from "@/components/geode/geodi-sprite";
import { galmuri } from "@/fonts/galmuri";

/**
 * Site-wide 404 — the mascot-budgeted empty state (DESIGN.md §4).
 * Static bilingual copy (no LocaleProvider: this page renders before any
 * locale context) and no decorative arrows.
 */
export default function NotFound() {
  const pixelFont = { fontFamily: "var(--font-pixel), var(--font-display), sans-serif" };
  return (
    <main
      className={`${galmuri.variable} rose-grid flex min-h-screen flex-col items-center justify-center bg-[var(--paper)] px-6 text-center text-[var(--ink)]`}
    >
      <GeodiSprite scale={7} />
      <h1 className="mt-8 text-[64px] leading-none text-[var(--acc-artifact)]" style={pixelFont}>
        404
      </h1>
      <p className="mt-4 text-[16px] text-[var(--ink-1)]" style={pixelFont}>
        이 경로는 아직 탐사되지 않았습니다.
      </p>
      <p className="mt-1 font-mono text-[12px] text-[var(--ink-3)]">This path has not been explored yet.</p>
      <div className="mt-8 flex gap-6 font-mono text-[13px]">
        <Link href="/" className="text-[var(--ink-2)] transition-colors hover:text-[var(--acc-artifact)]">
          홈 / home
        </Link>
        <Link href="/docs" className="text-[var(--ink-2)] transition-colors hover:text-[var(--acc-artifact)]">
          문서 / docs
        </Link>
      </div>
    </main>
  );
}
