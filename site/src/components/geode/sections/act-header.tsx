"use client";

import type { ReactNode } from "react";
import { useLocale, t } from "../locale-context";

/**
 * ActHeader. The narrative spine of the portfolio.
 *
 * PR-PORTFOLIO-NARRATIVE (2026-05-30). The portfolio was a flat scroll of
 * co-equal subsystem sections. ActHeader groups them into acts, each opening
 * with a framing line that says WHY the sections under it hang together, so
 * the page reads as a story (what it is, how it runs a task, how it is served,
 * how it improves itself, where it sits, how it was built) instead of a
 * feature checklist. No box card: an accent eyebrow, a display title, and one
 * narrative paragraph, over a hairline.
 */
type ActHeaderProps = {
  id: string;
  eyebrow: string;
  title: string;
  titleKo: string;
  body: string;
  bodyKo: string;
  children?: ReactNode;
};

export function ActHeader({ id, eyebrow, title, titleKo, body, bodyKo, children }: ActHeaderProps) {
  const locale = useLocale();
  return (
    <section id={id} className="px-6 pt-28 pb-4 scroll-mt-16">
      <div className="max-w-3xl mx-auto border-t border-[var(--rule)] pt-10">
        <div className="font-mono text-[11px] tracking-[0.24em] uppercase text-[var(--acc-artifact)]">
          {eyebrow}
        </div>
        <h2 className="mt-3 font-display tracking-tight text-[var(--ink)] text-[clamp(1.7rem,3.6vw,2.4rem)] leading-[1.12] font-semibold">
          {t(locale, titleKo, title)}
        </h2>
        <p className="mt-4 max-w-2xl text-[var(--ink-2)] leading-[1.75] text-[16px]">
          {t(locale, bodyKo, body)}
        </p>
        {children ? <div className="mt-5">{children}</div> : null}
      </div>
    </section>
  );
}
