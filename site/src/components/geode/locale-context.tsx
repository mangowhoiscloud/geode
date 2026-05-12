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

export function LocaleProvider({ children }: { children: ReactNode }) {
  const [locale, setLocale] = useState<Locale>("ko");

  // Read ?lang=en from URL on mount
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const lang = params.get("lang");
    if (lang === "en") setLocale("en");
  }, []);

  // Update html lang attribute + URL param
  useEffect(() => {
    document.documentElement.lang = locale;
    const url = new URL(window.location.href);
    if (locale === "en") {
      url.searchParams.set("lang", "en");
    } else {
      url.searchParams.delete("lang");
    }
    window.history.replaceState({}, "", url.toString());
  }, [locale]);

  return (
    <LocaleContext.Provider value={locale}>
      <SetLocaleContext.Provider value={setLocale}>
        {children}
      </SetLocaleContext.Provider>
    </LocaleContext.Provider>
  );
}
