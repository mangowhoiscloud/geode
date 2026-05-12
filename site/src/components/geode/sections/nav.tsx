"use client";

import { useState, useEffect, useRef } from "react";
import { LocaleToggle } from "../ui/locale-toggle";

const navItems = [
  { id: "hero", label: "Overview" },
  { id: "scaffold", label: "Scaffold" },
  { id: "loop", label: "Loop" },
  { id: "architecture", label: "Arch" },
  { id: "hooks", label: "Runtime" },
  { id: "context", label: "Memory" },
  { id: "domain", label: "Domain" },
  { id: "verify", label: "Verify" },
  { id: "timeline", label: "Timeline" },
];

export function GeodeNav() {
  const [activeSection, setActiveSection] = useState("hero");
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

    navItems.forEach((it) => {
      const el = document.getElementById(it.id);
      if (el) observerRef.current?.observe(el);
    });

    return () => {
      window.removeEventListener("scroll", handleScroll);
      observerRef.current?.disconnect();
    };
  }, []);

  function scrollTo(id: string) {
    const el = document.getElementById(id);
    if (el) el.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  if (!visible) return null;

  return (
    <nav className="fixed top-0 left-0 right-0 z-50 bg-[var(--paper)]/85 backdrop-blur-md border-b border-[var(--rule)]">
      <div
        className="max-w-5xl mx-auto px-4 py-2 flex items-center gap-0.5 overflow-x-auto"
        style={{ scrollbarWidth: "none" }}
      >
        <span className="font-mono text-[11px] tracking-[0.18em] uppercase text-[var(--ink-3)] shrink-0 mr-4">
          GEODE
        </span>
        <div className="flex-1 flex items-center gap-0.5">
          {navItems.map((it) => {
            const isActive = activeSection === it.id;
            return (
              <button
                key={it.id}
                onClick={() => scrollTo(it.id)}
                className="px-2.5 py-1 rounded font-mono text-[11px] transition-colors duration-200 shrink-0"
                style={{
                  color: isActive ? "var(--acc-artifact)" : "var(--ink-3)",
                  background: isActive ? "color-mix(in srgb, var(--acc-artifact) 10%, transparent)" : "transparent",
                }}
              >
                {it.label}
              </button>
            );
          })}
        </div>
        <LocaleToggle />
      </div>
    </nav>
  );
}
