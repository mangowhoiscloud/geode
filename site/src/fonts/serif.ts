import { Noto_Serif_KR } from "next/font/google";

/**
 * Editorial serif display — the Hermes-landing register (operator-approved
 * 2026-07-10): hero statements and section titles. Pixel (Galmuri) stays on
 * the wordmark and character-adjacent surfaces; mono stays on labels.
 * KR font loads via next/font unicode-range slices (no full preload).
 */
export const serifDisplay = Noto_Serif_KR({
  weight: ["600", "900"],
  variable: "--font-serif-display",
  display: "swap",
  preload: false,
});
