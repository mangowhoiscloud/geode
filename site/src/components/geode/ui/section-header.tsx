"use client";

import { ScrollReveal } from "../scroll-reveal";

type Variant = "default" | "quote" | "minimal" | "side";

interface SectionHeaderProps {
  label?: string;
  labelColor?: string;
  title: string;
  subtitle?: string;
  description?: string;
  variant?: Variant;
  children?: React.ReactNode;
}

export function SectionHeader({
  label,
  labelColor = "#4ECDC4",
  title,
  subtitle,
  description,
  variant = "default",
  children,
}: SectionHeaderProps) {
  if (variant === "quote") {
    return (
      <ScrollReveal>
        <div className="border-l-2 pl-6 mb-10" style={{ borderColor: `${labelColor}40` }}>
          <h2 className="text-2xl sm:text-3xl font-bold tracking-tight text-white/90 mb-2">{title}</h2>
          {subtitle && <p className="text-base text-white/40 font-medium mb-3">{subtitle}</p>}
          {description && <p className="text-sm text-[#A0B4D4] max-w-lg leading-relaxed">{description}</p>}
          {children}
        </div>
      </ScrollReveal>
    );
  }

  if (variant === "minimal") {
    return (
      <ScrollReveal>
        <div className="mb-8">
          <h2 className="text-xl sm:text-2xl font-bold tracking-tight text-white/85">{title}</h2>
          {description && <p className="text-sm text-[#A0B4D4] mt-2 max-w-md leading-relaxed">{description}</p>}
          {children}
        </div>
      </ScrollReveal>
    );
  }

  if (variant === "side") {
    return (
      <ScrollReveal>
        <div className="flex flex-col md:flex-row md:items-end md:justify-between gap-4 mb-10">
          <div>
            {label && (
              <p className="text-xs font-mono font-bold uppercase tracking-[0.2em] mb-2" style={{ color: `${labelColor}90` }}>
                {label}
              </p>
            )}
            <h2 className="text-3xl sm:text-4xl font-bold tracking-tight text-white/90">{title}</h2>
          </div>
          <div className="max-w-sm">
            {description && <p className="text-sm text-[#A0B4D4] leading-relaxed">{description}</p>}
          </div>
          {children}
        </div>
      </ScrollReveal>
    );
  }

  // default
  return (
    <ScrollReveal>
      {label && (
        <p className="text-sm font-mono font-bold uppercase tracking-[0.25em] mb-3" style={{ color: `${labelColor}99` }}>
          {label}
        </p>
      )}
      <h2 className="text-3xl sm:text-4xl font-bold tracking-tight text-white/90 mb-3">{title}</h2>
      {subtitle && <p className="text-lg text-white/40 font-semibold mb-4">{subtitle}</p>}
      {description && <p className="text-sm sm:text-base text-[#A0B4D4] max-w-xl mb-8 leading-relaxed">{description}</p>}
      {children}
    </ScrollReveal>
  );
}
