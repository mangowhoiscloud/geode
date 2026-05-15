"use client";

import { type ReactNode } from "react";
import { MathExpr } from "./math";

/**
 * MarkdownLite. The minimum subset needed to render CHANGELOG.md entries.
 *
 * Handles:
 *  - `### Section` → h3
 *  - `- bullet` lines (with indented sub-bullets via 2-space leading)
 *  - `**bold**`, `*italic*`
 *  - `` `code` ``
 *  - `[text](url)` links (target=_blank for external)
 *  - `$inline math$` and `$$block math$$` via KaTeX
 *  - HTML tags `<code>x</code>`, `<strong>x</strong>` passed through (text-only)
 *  - fenced code blocks ```...```
 *  - blank line breaks
 *
 * Not handled (CHANGELOG entries do not use these):
 *  - tables (only used in PR bodies, not CHANGELOG)
 *  - images
 *  - HTML other than the inline tags above
 */
export function MarkdownLite({ text }: { text: string }) {
  const blocks = parseBlocks(text);
  return (
    <>
      {blocks.map((b, i) => (
        <Block key={i} node={b} />
      ))}
    </>
  );
}

type Block =
  | { kind: "h3"; text: string }
  | { kind: "p"; text: string }
  | { kind: "ul"; items: { text: string; depth: number }[] }
  | { kind: "pre"; text: string };

function parseBlocks(src: string): Block[] {
  const out: Block[] = [];
  const lines = src.split("\n");
  let i = 0;
  while (i < lines.length) {
    const line = lines[i];

    // Fenced code block
    if (line.startsWith("```")) {
      const collected: string[] = [];
      i++;
      while (i < lines.length && !lines[i].startsWith("```")) {
        collected.push(lines[i]);
        i++;
      }
      i++;
      out.push({ kind: "pre", text: collected.join("\n") });
      continue;
    }

    if (line.startsWith("### ")) {
      out.push({ kind: "h3", text: line.slice(4).trim() });
      i++;
      continue;
    }

    // Unordered list (potentially with continuations + nested 2-space items).
    if (/^[-*] /.test(line)) {
      const items: { text: string; depth: number }[] = [];
      while (
        i < lines.length &&
        (/^[-*] /.test(lines[i]) ||
          /^ {2,}[-*] /.test(lines[i]) ||
          (items.length > 0 && lines[i].startsWith("  ") && lines[i].trim() !== ""))
      ) {
        const raw = lines[i];
        if (/^[-*] /.test(raw)) {
          items.push({ depth: 0, text: raw.slice(2) });
        } else if (/^ {2,}[-*] /.test(raw)) {
          const indent = raw.match(/^ +/)![0].length;
          const depth = Math.min(2, Math.floor(indent / 2));
          items.push({ depth, text: raw.replace(/^ +[-*] /, "") });
        } else {
          items[items.length - 1].text += " " + raw.trim();
        }
        i++;
      }
      out.push({ kind: "ul", items });
      continue;
    }

    if (line.trim() === "") {
      i++;
      continue;
    }

    // Paragraph. Gather until blank or special token.
    const para: string[] = [line];
    i++;
    while (i < lines.length && lines[i].trim() !== "" && !/^([-*] |### |```)/.test(lines[i])) {
      para.push(lines[i]);
      i++;
    }
    out.push({ kind: "p", text: para.join(" ") });
  }
  return out;
}

function Block({ node }: { node: Block }) {
  if (node.kind === "h3") {
    return <h3>{renderInline(node.text)}</h3>;
  }
  if (node.kind === "p") {
    return <p>{renderInline(node.text)}</p>;
  }
  if (node.kind === "pre") {
    return <pre>{node.text}</pre>;
  }
  // Build a nested list. depth 0/1/2.
  return (
    <ul>
      {node.items.map((it, idx) => (
        <li key={idx} style={{ marginLeft: it.depth * 12 }}>
          {renderInline(it.text)}
        </li>
      ))}
    </ul>
  );
}

function renderInline(text: string): ReactNode {
  // Tokenize: split on `code`, **bold**, *italic*, [text](url).
  // Keep it simple. Match each separately in priority order.
  const out: ReactNode[] = [];
  let rest = text;
  let key = 0;

  const patterns: Array<{
    re: RegExp;
    render: (m: RegExpExecArray) => ReactNode;
  }> = [
    {
      // Block math: $$...$$ (must be tried before inline $...$)
      re: /\$\$([^$]+)\$\$/,
      render: (m) => <MathExpr key={`mb${key}`} expr={m[1]} block />,
    },
    {
      // Inline math: $...$ . Disallow whitespace immediately inside the
      // delimiters so a stray "$ price" or "cost $3.00" in prose does not
      // accidentally match. Use a negative class for the first/last char.
      re: /\$([^\s$][^$]*[^\s$]|[^\s$])\$/,
      render: (m) => <MathExpr key={`mi${key}`} expr={m[1]} />,
    },
    {
      re: /`([^`]+)`/,
      render: (m) => <code key={`c${key}`}>{m[1]}</code>,
    },
    {
      re: /\*\*([^*]+)\*\*/,
      render: (m) => <strong key={`b${key}`}>{m[1]}</strong>,
    },
    {
      re: /\[([^\]]+)\]\(([^)]+)\)/,
      render: (m) => {
        const external = /^https?:\/\//.test(m[2]);
        return (
          <a
            key={`a${key}`}
            href={m[2]}
            target={external ? "_blank" : undefined}
            rel={external ? "noreferrer" : undefined}
          >
            {m[1]}
          </a>
        );
      },
    },
  ];

  while (rest.length > 0) {
    let bestIdx = -1;
    let bestMatch: RegExpExecArray | null = null;
    let bestPattern: (typeof patterns)[number] | null = null;
    for (const p of patterns) {
      const m = p.re.exec(rest);
      if (m && (bestIdx < 0 || m.index < bestIdx)) {
        bestIdx = m.index;
        bestMatch = m;
        bestPattern = p;
      }
    }
    if (!bestMatch || !bestPattern || bestIdx < 0) {
      out.push(rest);
      break;
    }
    if (bestIdx > 0) out.push(rest.slice(0, bestIdx));
    out.push(bestPattern.render(bestMatch));
    rest = rest.slice(bestIdx + bestMatch[0].length);
    key++;
  }
  return <>{out}</>;
}
