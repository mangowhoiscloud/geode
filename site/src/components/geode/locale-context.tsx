"use client";

import { createContext, useContext, useState, useEffect, type ReactNode } from "react";

export type Locale = "ko" | "en";

const LocaleContext = createContext<Locale>("ko");
const SetLocaleContext = createContext<(l: Locale) => void>(() => {});

export function useLocale(): Locale {
  return useContext(LocaleContext);
}

export function useSetLocale(): (l: Locale) => void {
  return useContext(SetLocaleContext);
}

/** Helper: pick the right string from a bilingual pair */
export function t(locale: Locale, ko: string, en: string): string {
  return locale === "en" ? en : ko;
}

export function LocaleProvider({
  children,
  defaultLocale = "ko",
}: {
  children: ReactNode;
  defaultLocale?: Locale;
}) {
  const [locale, setLocale] = useState<Locale>(defaultLocale);

  // Explicit ?lang= param only — never the browser locale. The param wins
  // over the surface default (portfolio defaults en, docs defaults ko).
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const lang = params.get("lang");
    if (lang !== "en" && lang !== "ko") return;
    // Defer until after hydration; the server cannot observe the query string.
    const timer = window.setTimeout(() => setLocale(lang), 0);
    return () => window.clearTimeout(timer);
  }, []);

  // Update html lang attribute + URL param (param present only when the
  // locale differs from this surface's default, so default URLs stay clean).
  useEffect(() => {
    document.documentElement.lang = locale;
    const url = new URL(window.location.href);
    if (locale !== defaultLocale) {
      url.searchParams.set("lang", locale);
    } else {
      url.searchParams.delete("lang");
    }
    window.history.replaceState({}, "", url.toString());
  }, [locale, defaultLocale]);

  return (
    <LocaleContext.Provider value={locale}>
      <SetLocaleContext.Provider value={setLocale}>
        {children}
      </SetLocaleContext.Provider>
    </LocaleContext.Provider>
  );
}
