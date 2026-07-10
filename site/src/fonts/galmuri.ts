import localFont from "next/font/local";

/**
 * Galmuri11 — Korean pixel (bitmap-style) font, SIL OFL 1.1.
 * (c) 2019-2025 Lee Minseo, https://galmuri.quiple.dev
 * Vendored woff2 copied from the `galmuri` npm package (dist/).
 *
 * This is the character-facing display font: it matches the GEODI_PIXELS
 * dot mascot, and loads only on pages that import this module (portfolio,
 * docs shell wordmark). Body text stays Inter for readability.
 */
export const galmuri = localFont({
  src: [
    { path: "./Galmuri11.woff2", weight: "400", style: "normal" },
    { path: "./Galmuri11-Bold.woff2", weight: "700", style: "normal" },
  ],
  variable: "--font-pixel",
  display: "swap",
});
