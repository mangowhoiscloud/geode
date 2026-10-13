"use client";

import { useEffect } from "react";
import { normalizeResearchSelection } from "@/lib/research-selection";

const legacyPaths: Record<string, string> = {
  "#research": "/geode/research/",
  "#research-geode": "/geode/research/",
  "#research-jev": "/geode/research/",
  "#jevdb-paper-review": "/geode/research/",
};

/** Keep submitted homepage links working without adding a redirect history entry. */
export function LegacyResearchRedirect() {
  useEffect(() => {
    const redirect = () => {
      const destination = legacyPaths[window.location.hash];
      if (!destination) return;
      const url = normalizeResearchSelection(new URL(window.location.href));
      url.pathname = destination;
      // The landing defaults to English; the publication readers default to Korean.
      if (!url.searchParams.has("lang")) url.searchParams.set("lang", "en");
      window.location.replace(url.toString());
    };
    redirect();
    window.addEventListener("hashchange", redirect);
    return () => window.removeEventListener("hashchange", redirect);
  }, []);
  return null;
}
