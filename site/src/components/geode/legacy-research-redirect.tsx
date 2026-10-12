"use client";

import { useEffect } from "react";

const legacyPaths: Record<string, string> = {
  "#research": "/geode/research/",
  "#research-geode": "/geode/research/",
  "#research-jev": "/geode/research/",
  "#jevdb-paper-review": "/geode/research/",
  "#roadmap": "/geode/docs/explanation/rsi-roadmap/",
  "#features": "/geode/docs/overview/how-it-runs/",
  "#distill": "/geode/docs/capabilities/outer-loop/",
};

/** Keep submitted homepage links working without adding a redirect history entry. */
export function LegacyResearchRedirect() {
  useEffect(() => {
    const redirect = () => {
      const destination = legacyPaths[window.location.hash];
      if (!destination) return;
      const url = new URL(window.location.href);
      url.pathname = destination;
      // The landing defaults to English; the publication readers default to Korean.
      if (!url.searchParams.has("lang")) url.searchParams.set("lang", "en");
      if (url.hash === "#research" || !destination.endsWith("/research/")) url.hash = "";
      window.location.replace(url.toString());
    };
    redirect();
    window.addEventListener("hashchange", redirect);
    return () => window.removeEventListener("hashchange", redirect);
  }, []);
  return null;
}
