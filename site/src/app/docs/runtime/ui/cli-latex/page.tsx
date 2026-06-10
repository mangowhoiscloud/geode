import { DocsShell, Bi } from "@/components/geode-docs/docs-shell";

export const metadata = { title: "CLI LaTeX rendering — GEODE Docs" };

export default function Page() {
  return (
    <DocsShell
      slug="runtime/ui/cli-latex"
      title="CLI LaTeX rendering"
      titleKo="CLI LaTeX 렌더링"
      summary="Two-tier math rendering in the terminal: Unicode flatten for inline, 2D pretty print for blocks, raw text as the final fallback."
      summaryKo="터미널의 2단 수식 렌더링입니다. 인라인은 Unicode 평탄화, 블록은 2D pretty print, 최종 폴백은 원문입니다."
    >
      <Bi
        ko={
          <>
            <p>
              LLM 응답의 수식을 터미널에서 읽을 수 있게 렌더링합니다. 구현은{" "}
              <code>core/ui/latex.py</code> 한 모듈이고, 진입점은{" "}
              <code>render_latex(src, block=...)</code>와 스트리밍 본문에서
              수식 구간을 찾아내는 <code>extract_and_render_inline</code>입니다.
              호출자는 대화형 루프(<code>core/cli/interactive_loop.py</code>)입니다.
            </p>

            <h2>2단 구조</h2>
            <pre>{`Tier 1  pylatexenc LatexNodes2Text   인라인/블록 공통. LaTeX → 평탄한 Unicode 한 줄
Tier 2  latex2sympy2 + sympy.pretty  블록 전용. 분수·적분을 2D Unicode 블록으로
폴백    원문 그대로                   양쪽 모두 실패 시. 절대 raise하지 않음`}</pre>
            <p>
              인라인(<code>block=False</code>)은 Tier 2를 아예 건너뜁니다.
              한 줄 흐름이 예측 가능해야 하기 때문입니다. 블록은{" "}
              <code>_has_tier2_construct</code>가 분수 같은 2D 가치가 있는
              토큰을 발견했을 때만 Tier 2를 시도하고, 파싱이나 pretty가
              실패하면 조용히 Tier 1로 내려갑니다. Tier 1마저 실패하면 입력
              원문을 그대로 반환합니다.
            </p>

            <h2>감지 휴리스틱</h2>
            <p>
              <code>extract_and_render_inline</code>은 구분자 있는 수식
              (<code>$...$</code>, <code>$$...$$</code>)과 구분자 없는 후보를
              모두 다루면서 오탐을 막는 가드를 둡니다. 마크다운 코드 스팬은
              건너뛰고, <code>/</code>가 파일 경로 문맥인지 판별하고
              (<code>_looks_like_path_context</code>), 숫자 밑 첨자와 중첩 윗
              첨자도 처리합니다. 수식 출력 계약 자체는 프롬프트 쪽에서{" "}
              <code>with_math_output_formatting</code>
              (<code>core/llm/prompt_assembler.py</code>)이 모델에 지시합니다.
            </p>

            <h2>실패 모드</h2>
            <table>
              <thead>
                <tr><th>증상</th><th>원인</th><th>해법</th></tr>
              </thead>
              <tbody>
                <tr><td>수식이 원문 LaTeX로 보임</td><td>pylatexenc 미설치 또는 Tier 1 예외</td><td>의존성은 pyproject에 선언되어 있습니다. 재설치 후에도 같으면 입력이 LaTeX가 아닌 경우입니다.</td></tr>
                <tr><td>블록 수식이 한 줄로 나옴</td><td>Tier 2 파싱 실패 후 Tier 1 폴백</td><td>의도된 동작입니다. latex2sympy2가 다루지 못하는 구문은 평탄화됩니다.</td></tr>
                <tr><td>경로가 수식으로 렌더링</td><td>구분자 없는 후보 오탐</td><td>경로 문맥 가드가 회귀 테스트로 고정되어 있습니다. 사례를 발견하면 테스트에 추가합니다.</td></tr>
              </tbody>
            </table>

            <h2>회귀 테스트</h2>
            <p>
              <code>tests/core/ui/test_ui_latex.py</code>,{" "}
              <code>tests/core/ui/test_cli_latex_uiux.py</code>,{" "}
              <code>tests/core/cli/test_interactive_loop_latex.py</code>가
              멀티라인 collapse, 구분자 없는 휴리스틱, 경로 문맥, 숫자 밑 첨자
              케이스를 고정합니다.
            </p>
          </>
        }
        en={
          <>
            <p>
              GEODE renders math in LLM replies readably in the terminal. The
              implementation is one module, <code>core/ui/latex.py</code>; the
              entry points are <code>render_latex(src, block=...)</code> and{" "}
              <code>extract_and_render_inline</code>, which finds math spans in
              streaming text. The caller is the interactive loop
              (<code>core/cli/interactive_loop.py</code>).
            </p>

            <h2>The two tiers</h2>
            <pre>{`Tier 1   pylatexenc LatexNodes2Text   inline + block. LaTeX → flat Unicode, one line
Tier 2   latex2sympy2 + sympy.pretty  block only. fractions/integrals as a 2D Unicode block
fallback raw source                   when both fail. never raises`}</pre>
            <p>
              Inline (<code>block=False</code>) skips Tier 2 entirely so
              one-line flow stays predictable. Blocks try Tier 2 only when{" "}
              <code>_has_tier2_construct</code> spots a token worth 2D
              treatment, and fall back silently to Tier 1 when parsing or
              pretty-printing fails. If Tier 1 fails too, the raw input comes
              back unchanged.
            </p>

            <h2>Detection heuristics</h2>
            <p>
              <code>extract_and_render_inline</code> handles both delimited math
              (<code>$...$</code>, <code>$$...$$</code>) and delimiter-less
              candidates, with guards against false positives: markdown code
              spans are skipped, <code>/</code> in a file-path context is left
              alone (<code>_looks_like_path_context</code>), and digit-base
              subscripts plus nested superscripts are handled. The output
              contract itself is instructed to the model by{" "}
              <code>with_math_output_formatting</code> in{" "}
              <code>core/llm/prompt_assembler.py</code>.
            </p>

            <h2>Failure modes</h2>
            <table>
              <thead>
                <tr><th>Symptom</th><th>Cause</th><th>Fix</th></tr>
              </thead>
              <tbody>
                <tr><td>Math shows as raw LaTeX</td><td>pylatexenc missing or a Tier 1 exception</td><td>The dependency ships in pyproject. If it persists after a reinstall, the input was not LaTeX.</td></tr>
                <tr><td>A block renders on one line</td><td>Tier 2 parse failed, Tier 1 took over</td><td>Intended: constructs latex2sympy2 cannot handle get flattened.</td></tr>
                <tr><td>A path renders as math</td><td>Delimiter-less false positive</td><td>The path-context guard is pinned by regression tests; add the case when found.</td></tr>
              </tbody>
            </table>

            <h2>Regression suite</h2>
            <p>
              <code>tests/core/ui/test_ui_latex.py</code>,{" "}
              <code>tests/core/ui/test_cli_latex_uiux.py</code>, and{" "}
              <code>tests/core/cli/test_interactive_loop_latex.py</code> pin
              multi-line collapse, the delimiter-less heuristic, path context,
              and digit-base cases.
            </p>
          </>
        }
      />
    </DocsShell>
  );
}
