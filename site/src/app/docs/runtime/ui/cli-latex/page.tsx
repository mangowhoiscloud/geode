import { DocsShell, Bi } from "@/components/geode-docs/docs-shell";

export const metadata = { title: "CLI LaTeX Rendering — GEODE Docs" };

export default function Page() {
  return (
    <DocsShell
      slug="runtime/ui/cli-latex"
      title="CLI LaTeX Rendering"
      titleKo="CLI LaTeX 렌더링"
      summary="Five-tier LaTeX rendering stack inside the terminal: detection, Unicode flatten, 2D pretty print, image fallback, and ASCII guard."
      summaryKo="터미널 안 5-tier LaTeX 렌더링 스택. detection, Unicode flatten, 2D pretty print, image fallback, ASCII guard."
    >
      <Bi
        ko={
          <>
            <h2>5-Tier 스택</h2>
            <pre>{`Tier 1  pylatexenc                  inline LaTeX → flat Unicode (5 MB)
Tier 2  latex2sympy2 + sympy.pretty  2D Unicode block (~30 MB)
Tier 3  graphics fallback            terminal image (scaffold)
Tier 4  bracket fallback             [...] 형식의 plain text
Tier 5  ASCII guard                  렌더 실패 시 원문 그대로 출력`}</pre>

            <h2>경로 결정</h2>
            <p>
              `core/ui/latex.py` 의 detector 가 입력 토큰을 분석해 Tier 를 선택합니다. v0.95–v0.96 의 7 PR 묶음 (#1179 Markdown streaming, #1180 CJK redraw, #1181 detector, #1185 Tier 1 unicode, #1193 path-context, #1196 digit-base + nested superscript, #1199 thinking collapse) 으로 detector PASS ≠ render PASS 케이스, `/` path false-positive, nested superscript, thinking collapse-on-end UX 까지 처리합니다.
            </p>

            <h2>토글 + 디버깅</h2>
            <pre>{`# 렌더 토글 (Ctrl+O)
Ctrl+O                    Tier 1↔Tier 2 ↔ raw 순환

# 진단 로그
GEODE_LATEX_DEBUG=1 geode "...$x^2$..."`}</pre>

            <h2>회귀 슈트</h2>
            <p>
              `tests/test_ui_latex.py` + `tests/test_cli_latex_uiux.py` + `tests/test_interactive_loop_latex.py` 가 multi-line collapse, delimiter-less heuristic, path-context, digit-base 케이스를 지킵니다.
            </p>

            <p className="text-white/40 text-sm"><em>참조</em>: `core/ui/latex.py`, CHANGELOG v0.95.1–v0.96.0, Session 60-61 handoff.</p>
          </>
        }
        en={
          <>
            <h2>The five tiers</h2>
            <pre>{`Tier 1  pylatexenc                  inline LaTeX -> flat Unicode (~5 MB)
Tier 2  latex2sympy2 + sympy.pretty  2D Unicode block (~30 MB)
Tier 3  graphics fallback            terminal image (scaffolded)
Tier 4  bracket fallback             plain [...] text
Tier 5  ASCII guard                  fall through to raw text on failure`}</pre>

            <h2>How the tier is chosen</h2>
            <p>
              The detector in `core/ui/latex.py` picks a tier per input token. The seven-PR run in v0.95–v0.96 (#1179 Markdown streaming, #1180 CJK redraw, #1181 detector, #1185 Tier 1 unicode, #1193 path-context, #1196 digit-base + nested superscript, #1199 thinking collapse) handles detector-PASS-but-render-FAIL cases, `/` path false positives, nested superscripts, and thinking-collapse-on-end UX.
            </p>

            <h2>Toggle + debugging</h2>
            <pre>{`# render toggle (Ctrl+O)
Ctrl+O                    cycle Tier 1 -> Tier 2 -> raw

# diagnostic log
GEODE_LATEX_DEBUG=1 geode "...$x^2$..."`}</pre>

            <h2>Regression suite</h2>
            <p>
              `tests/test_ui_latex.py`, `tests/test_cli_latex_uiux.py`, and `tests/test_interactive_loop_latex.py` pin multi-line collapse, the delimiter-less heuristic, path context, and digit-base.
            </p>

            <p className="text-white/40 text-sm"><em>References</em>: `core/ui/latex.py`, CHANGELOG v0.95.1-v0.96.0, Session 60-61 handoff.</p>
          </>
        }
      />
    </DocsShell>
  );
}
