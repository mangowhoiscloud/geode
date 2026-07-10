"use client";

import Link from "next/link";
import { useLocale } from "../locale-context";

export function GeodeFooter() {
  const locale = useLocale();
  return (
    <footer className="relative py-16 px-4 sm:px-6 border-t border-white/[0.04]">
      <div className="max-w-5xl mx-auto flex flex-col sm:flex-row items-center justify-between gap-6">
        <div>
          <div className="text-sm font-semibold text-white/50">GEODE</div>
          <div className="text-xs text-[var(--ink-2)]">An agentic OS · the loop laboratory.</div>
        </div>

        <div className="flex items-center gap-4">
          <Link
            href="https://github.com/mangowhoiscloud/geode"
            target="_blank"
            className="text-xs font-mono text-[var(--ink-2)] hover:text-[var(--ink)] transition-colors"
          >
            GitHub
          </Link>
          <Link
            href="/"
            className="text-xs font-mono text-[var(--ink-2)] hover:text-[var(--ink)] transition-colors"
          >
            {locale === "en" ? "Portfolio" : "포트폴리오"}
          </Link>
        </div>

        <div className="text-[10px] text-[var(--ink-3)] font-mono">
          © 2025-2026 Jihwan Ryu
        </div>
      </div>
    </footer>
  );
}
