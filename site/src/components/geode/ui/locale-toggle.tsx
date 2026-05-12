"use client";

import { useLocale, useSetLocale, type Locale } from "../locale-context";

export function LocaleToggle() {
  const locale = useLocale();
  const setLocale = useSetLocale();

  return (
    <div className="flex items-center gap-0.5 rounded-full border border-white/[0.06] bg-white/[0.02] p-0.5">
      {(["ko", "en"] as Locale[]).map((l) => (
        <button
          key={l}
          onClick={() => setLocale(l)}
          className="px-2 py-0.5 rounded-full text-[10px] font-mono font-bold uppercase transition-all duration-200"
          style={{
            color: locale === l ? "#4ECDC4" : "#5A6A8A",
            background: locale === l ? "rgba(78,205,196,0.1)" : "transparent",
          }}
        >
          {l}
        </button>
      ))}
    </div>
  );
}
