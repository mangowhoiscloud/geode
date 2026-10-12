"use client";

import { LandingHeader } from "./landing-header";
import { ResearchSection } from "./landing-research";
import { LocaleProvider, t, useLocale } from "./locale-context";
import { galmuri } from "@/fonts/galmuri";
import "./landing.css";

function ResearchContent() {
  const locale = useLocale();
  return <div className={`geode-landing ${galmuri.variable}`} lang={locale}>
    <a className="landing-skip" href="#main-content">{t(locale, "본문으로 이동", "Skip to content")}</a>
    <LandingHeader current="research" />
    <main id="main-content" tabIndex={-1}><ResearchSection /></main>
  </div>;
}

export function ResearchPage() {
  return <LocaleProvider><ResearchContent /></LocaleProvider>;
}
