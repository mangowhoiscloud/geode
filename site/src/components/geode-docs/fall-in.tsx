"use client";

import { useRef } from "react";
import { motion, useInView, useReducedMotion } from "framer-motion";

/**
 * Scroll-entrance drop: the element falls from above and settles with a
 * spring when it first scrolls into view (hermes-agent landing style).
 * The sanctioned scroll motion for the docs surface (DESIGN.md §motion):
 * once per element, spring settle, honors prefers-reduced-motion.
 */
export function FallIn({
  children,
  className,
  delay = 0,
  drop = 36,
  tilt = 0,
}: {
  children: React.ReactNode;
  className?: string;
  delay?: number;
  drop?: number;
  tilt?: number;
}) {
  const ref = useRef(null);
  const inView = useInView(ref, { once: true, margin: "-60px" });
  const reduceMotion = useReducedMotion();

  if (reduceMotion) {
    return <div className={className}>{children}</div>;
  }

  return (
    <motion.div
      ref={ref}
      className={className}
      initial={{ opacity: 0, y: -drop, rotate: tilt }}
      animate={inView ? { opacity: 1, y: 0, rotate: 0 } : undefined}
      transition={{
        type: "spring",
        stiffness: 320,
        damping: 24,
        mass: 0.9,
        delay,
      }}
    >
      {children}
    </motion.div>
  );
}
