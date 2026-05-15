"use client";

import katex from "katex";
import { useMemo } from "react";

/**
 * Math. Render a LaTeX expression to HTML via KaTeX.
 *
 * Usage in TSX pages:
 *   <MathExpr expr="Complexity(f) = \\#\\,\\text{operators} + \\#\\,\\text{variables} + \\text{depth}(f)" />
 *   <MathExpr expr="\\sum_{i=0}^{n} x_i" block />
 *
 * In markdown sources rendered via MarkdownLite, prefer the `$...$` (inline)
 * or `$$...$$` (block) shorthand. MarkdownLite hands the inner expression off
 * to KaTeX through this same component.
 *
 * Errors. If KaTeX throws (malformed LaTeX), the raw source is rendered as
 * plain monospace text in red, matching KaTeX's `throwOnError: false`
 * fallback so a single bad expression does not break the whole page.
 */
export function MathExpr({
  expr,
  block = false,
}: {
  expr: string;
  block?: boolean;
}) {
  const html = useMemo(
    () =>
      katex.renderToString(expr, {
        displayMode: block,
        throwOnError: false,
        strict: "ignore",
        output: "html",
        errorColor: "#f87171",
      }),
    [expr, block],
  );
  if (block) {
    return (
      <div
        className="my-3 overflow-x-auto"
        dangerouslySetInnerHTML={{ __html: html }}
      />
    );
  }
  return <span dangerouslySetInnerHTML={{ __html: html }} />;
}
