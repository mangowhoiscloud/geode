"use client";

interface TabItem {
  id: string;
  label: string;
  sub?: string;
  color?: string;
}

interface TabBarProps {
  tabs: TabItem[];
  activeId: string;
  onSelect: (id: string) => void;
  accentColor?: string;
  variant?: "default" | "pill" | "underline";
}

export function TabBar({ tabs, activeId, onSelect, accentColor, variant = "default" }: TabBarProps) {
  if (variant === "underline") {
    return (
      <div className="flex gap-4 mb-6 border-b border-white/[0.04] pb-px">
        {tabs.map((t) => {
          const color = t.color || accentColor || "#4ECDC4";
          const active = activeId === t.id;
          return (
            <button
              key={t.id}
              onClick={() => onSelect(t.id)}
              className="pb-2.5 text-xs font-mono font-bold transition-all duration-300 relative"
              style={{ color: active ? color : "#5A6A8A" }}
            >
              {t.label}
              {t.sub && <span className="ml-1.5 text-[10px] opacity-40">{t.sub}</span>}
              {active && (
                <span className="absolute bottom-0 left-0 right-0 h-px" style={{ background: color }} />
              )}
            </button>
          );
        })}
      </div>
    );
  }

  if (variant === "pill") {
    return (
      <div className="flex gap-1.5 mb-6 flex-wrap">
        {tabs.map((t) => {
          const color = t.color || accentColor || "#4ECDC4";
          const active = activeId === t.id;
          return (
            <button
              key={t.id}
              onClick={() => onSelect(t.id)}
              className="px-3 py-1.5 rounded-full text-[11px] font-mono font-bold transition-all duration-300"
              style={{
                color: active ? color : "#5A6A8A",
                background: active ? `${color}12` : "transparent",
              }}
            >
              {t.label}
            </button>
          );
        })}
      </div>
    );
  }

  // default (existing pattern, kept for compatibility)
  return (
    <div className="flex gap-2 mb-8 flex-wrap">
      {tabs.map((t) => {
        const color = t.color || accentColor || "#4ECDC4";
        const active = activeId === t.id;
        return (
          <button
            key={t.id}
            onClick={() => onSelect(t.id)}
            className="px-4 py-2 rounded-lg text-xs font-mono font-bold transition-all duration-300"
            style={{
              color: active ? color : "#5A6A8A",
              background: active ? `${color}08` : "transparent",
              border: `1px solid ${active ? `${color}20` : "rgba(255,255,255,0.04)"}`,
            }}
          >
            {t.label}
            {t.sub && <span className="ml-2 text-[10px] opacity-50">{t.sub}</span>}
          </button>
        );
      })}
    </div>
  );
}
