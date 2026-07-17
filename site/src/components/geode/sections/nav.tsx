"use client";

import { useState, useEffect, useRef } from "react";
import { LocaleToggle } from "../ui/locale-toggle";

type NavItem = { id: string; label: string };

const defaultNavItems: NavItem[] = [
  { id: "hero", label: "Overview" },
  { id: "two-loops", label: "Two loops" },
  { id: "self-evolving", label: "Self-evolving" },
  { id: "audit", label: "Audit" },
  { id: "capabilities", label: "Capabilities" },
  { id: "lineage", label: "Lineage" },
];

export function GeodeNav({
  items = defaultNavItems,
  light = false,
  showLocaleToggle = true,
}: {
  items?: NavItem[];
  /** Light chrome for the white-substrate portfolio surface. */
  light?: boolean;
  /** Hide language controls on surfaces whose copy is intentionally fixed. */
  showLocaleToggle?: boolean;
}) {
  const [activeSection, setActiveSection] = useState(items[0]?.id ?? "hero");
  const [visible, setVisible] = useState(false);
  const observerRef = useRef<IntersectionObserver | null>(null);

  useEffect(() => {
    const handleScroll = () => setVisible(window.scrollY > 400);
    window.addEventListener("scroll", handleScroll, { passive: true });

    observerRef.current = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (entry.isIntersecting) {
            setActiveSection(entry.target.id);
          }
        }
      },
      { rootMargin: "-40% 0px -55% 0px" },
    );

    items.forEach((it) => {
      const el = document.getElementById(it.id);
      if (el) observerRef.current?.observe(el);
    });

    return () => {
      window.removeEventListener("scroll", handleScroll);
      observerRef.current?.disconnect();
    };
  }, [items]);

  function scrollTo(id: string) {
    const el = document.getElementById(id);
    if (el) el.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  if (!visible) return null;

  const chrome = light
    ? { bg: "rgba(244,155,196,0.92)", border: "rgba(255,240,248,0.3)", brand: "rgba(255,240,248,0.8)" }
    : { bg: "color-mix(in srgb, var(--paper) 85%, transparent)", border: "var(--rule)", brand: "var(--ink-3)" };
  return (
    <nav
      className="fixed top-0 left-0 right-0 z-50 backdrop-blur-md border-b"
      style={{ background: chrome.bg, borderColor: chrome.border }}
    >
      <div
        className="max-w-5xl mx-auto px-4 py-2 flex items-center gap-0.5 overflow-x-auto"
        style={{ scrollbarWidth: "none" }}
      >
        <span
          className="font-mono text-[11px] tracking-[0.18em] uppercase shrink-0 mr-4"
          style={{ color: chrome.brand }}
        >
          GEODE
        </span>
        <div className="flex-1 flex items-center gap-0.5">
          {items.map((it) => {
            const isActive = activeSection === it.id;
            return (
              <button
                key={it.id}
                onClick={() => scrollTo(it.id)}
                className="px-2.5 py-1 rounded font-mono text-[11px] transition-colors duration-200 shrink-0"
                style={{
                  color: isActive
                    ? light
                      ? "#FFF0F8"
                      : "var(--acc-artifact)"
                    : light
                      ? "rgba(255,240,248,0.65)"
                      : "var(--ink-3)",
                  background: isActive
                    ? light
                      ? "rgba(255,240,248,0.22)"
                      : "color-mix(in srgb, var(--acc-artifact) 18%, transparent)"
                    : "transparent",
                }}
              >
                {it.label}
              </button>
            );
          })}
        </div>
        {showLocaleToggle ? <LocaleToggle /> : null}
      </div>
    </nav>
  );
}
