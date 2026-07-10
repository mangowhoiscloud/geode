/**
 * Geodi pixel sprite — web render of the CLI welcome-screen mascot.
 *
 * The 22x12 grid and 4-color palette are transcribed verbatim from
 * `core/ui/geodi_art.py::GEODI_PIXELS` / `GEODI_PALETTE` (the face-only
 * canon sprite the CLI draws as ANSI half-blocks). If the Python grid
 * changes, this file must change in the same commit.
 *
 * Blink: the only frame delta is the four open-eye pixels on row 6
 * (`e`,`w` pairs). The base render substitutes rose for those pixels
 * (closed-lid look, row 7 keeps the dark lid line) and the open-eye
 * pixels sit in an overlay group that `.geodi-blink-eyes` (defined in
 * `src/app/portfolio/astryx-geode.css`) hides for ~2 frames every 7s.
 */

const GEODI_PIXELS: string[] = [
  "........pppppp........",
  ".rr..pppppppppppp..rr.",
  "....pppppppppppppp....",
  ".rrrpppppppppppppprrr.",
  "....pppppppppppppp....",
  "..rrpppppppppppppprr..",
  "....pppewppppewppp....",
  "....pppeeppppeeppp....",
  "....prrpppppppprrp....",
  "....ppppppeepppppp....",
  ".....pppppppppppp.....",
  "......pppppppppp......",
];

// Sprite-data palette (parity with GEODI_PALETTE, not UI chrome tokens):
// p = Axolotl Rose body, r = deep-rose gills/blush, e = eyes/mouth, w = catchlight.
const GEODI_PALETTE: Record<string, string | undefined> = {
  ".": undefined,
  p: "#F49BC4",
  r: "#E0699F",
  e: "#2B2233",
  w: "#FFFFFF",
};

const EYE_ROW = 6;

type Pixel = { x: number; y: number; fill: string };

const basePixels: Pixel[] = [];
const openEyePixels: Pixel[] = [];

GEODI_PIXELS.forEach((row, y) => {
  [...row].forEach((ch, x) => {
    const fill = GEODI_PALETTE[ch];
    if (!fill) return;
    if (y === EYE_ROW && (ch === "e" || ch === "w")) {
      openEyePixels.push({ x, y, fill });
      basePixels.push({ x, y, fill: GEODI_PALETTE.p as string });
      return;
    }
    basePixels.push({ x, y, fill });
  });
});

export function GeodiSprite({
  scale = 8,
  blink = false,
  silhouette,
  className,
}: {
  /** Rendered size of one sprite pixel, in CSS px. */
  scale?: number;
  /** Enable the 2-frame eye blink (portfolio hero budget only). */
  blink?: boolean;
  /** Render every pixel in one color (stencil mark for color-field bands). */
  silhouette?: string;
  className?: string;
}) {
  return (
    <svg
      width={22 * scale}
      height={12 * scale}
      viewBox="0 0 22 12"
      shapeRendering="crispEdges"
      role="img"
      aria-label="Geodi, the GEODE pixel mascot"
      className={className}
    >
      {basePixels.map((p) => (
        <rect key={`${p.x}-${p.y}`} x={p.x} y={p.y} width={1} height={1} fill={silhouette ?? p.fill} />
      ))}
      <g className={blink && !silhouette ? "geodi-blink-eyes" : undefined}>
        {openEyePixels.map((p) => (
          <rect key={`eye-${p.x}-${p.y}`} x={p.x} y={p.y} width={1} height={1} fill={silhouette ?? p.fill} />
        ))}
      </g>
    </svg>
  );
}
