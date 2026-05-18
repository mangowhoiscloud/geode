import { DocsShell, Bi } from "@/components/geode-docs/docs-shell";

export const metadata = { title: "System Prompt Modes — GEODE Docs" };

export default function Page() {
  return (
    <DocsShell
      slug="runtime/llm/system-prompt-modes"
      title="System Prompt Modes"
      titleKo="시스템 프롬프트 모드"
      summary="GEODE_PERSONA opt-in plus audit-mode strip. The two ways the system prompt can be reshaped."
      summaryKo="GEODE_PERSONA opt-in과 audit-mode strip. 시스템 프롬프트가 변형되는 두 가지 방식."
    >
      <Bi
        ko={
          <>
            <p>
              <strong>Reference:</strong> GEODE는 같은 사용자 메시지를 두 가지 모드의 시스템 프롬프트로 흘릴 수 있습니다.
              일반 운영용 (default), Petri audit용 (`audit-mode`). 이 페이지는 두 모드의 차이와 활성화 방법을 정리합니다.
            </p>

            <h2>두 모드</h2>
            <table>
              <thead><tr><th>모드</th><th>활성화 시점</th><th>시스템 프롬프트에 포함</th></tr></thead>
              <tbody>
                <tr><td><strong>Default (운영)</strong></td><td>일반 호출</td><td>5계층 prompt assembly + <code>GEODE_PERSONA</code> opt-in 시 추가</td></tr>
                <tr><td><strong>audit-mode</strong></td><td>Petri audit 실행 (`geode audit ...`)</td><td>5계층 어셈블리에서 GEODE 정체성/페르소나 strip. base agent behavior만 노출.</td></tr>
              </tbody>
            </table>

            <h2>GEODE_PERSONA (opt-in)</h2>
            <p>
              `GEODE_PERSONA` 환경 변수 또는 config 플래그가 활성화되면 시스템 프롬프트 최상단에 GEODE 정체성 블록이 추가됩니다.
              기본은 off. Petri audit 시에는 강제 off로 떨어집니다.
            </p>
            <pre>{`# 활성화
export GEODE_PERSONA=on
# 또는 ~/.geode/config.toml 의 [prompt] persona = "on"`}</pre>

            <h2>audit-mode</h2>
            <p>
              <code>geode audit</code> CLI가 활성화하면 Petri 평가가 측정하려는 "base agent behavior"가 GEODE 정체성에 묻히지 않습니다.
              평가자(Auditor·Judge)는 vanilla LLM과 비교 가능한 transcript를 받습니다.
            </p>
            <ul>
              <li><a href="/geode/docs/petri/run">Petri audit 실행</a> 가이드 참조.</li>
              <li>strip 대상: GEODE_PERSONA 블록 + <code>&lt;dynamic_context&gt;</code> 일부.</li>
              <li>유지 대상: 도구 정의, MCP 설명, 기본 안전 가드.</li>
            </ul>

            <h2>변경 출처</h2>
            <ul>
              <li>v0.93.0 — <code>GEODE_PERSONA</code> opt-in 도입, audit-mode strip 정합화.</li>
              <li>v0.92.0 — Petri audit 도입과 함께 audit-mode 분기 신설.</li>
            </ul>

            <p className="text-white/40 text-sm">
              <em>참조:</em> <a href="/geode/docs/runtime/llm/prompt-system">Prompt System</a>, <a href="/geode/docs/petri/overview">Petri × GEODE</a>, CHANGELOG v0.92~0.93.
            </p>
          </>
        }
        en={
          <>
            <p>
              <strong>Reference:</strong> GEODE can route the same user message through two system-prompt modes:
              default operation and Petri audit (<code>audit-mode</code>). This page lists what each mode includes
              and how to activate it.
            </p>

            <h2>The two modes</h2>
            <table>
              <thead><tr><th>Mode</th><th>Activated by</th><th>Included in system prompt</th></tr></thead>
              <tbody>
                <tr><td><strong>Default (operation)</strong></td><td>Normal invocation.</td><td>5-layer prompt assembly plus <code>GEODE_PERSONA</code> block when opted in.</td></tr>
                <tr><td><strong>audit-mode</strong></td><td>Petri audit (<code>geode audit ...</code>).</td><td>5-layer assembly with GEODE identity stripped. Only base agent behavior is exposed.</td></tr>
              </tbody>
            </table>

            <h2>GEODE_PERSONA (opt-in)</h2>
            <p>
              When the <code>GEODE_PERSONA</code> environment variable or config flag is on, a GEODE identity block is
              prepended to the system prompt. Default is off. During Petri audits this is forced off.
            </p>
            <pre>{`# Enable
export GEODE_PERSONA=on
# Or in ~/.geode/config.toml: [prompt] persona = "on"`}</pre>

            <h2>audit-mode</h2>
            <p>
              The <code>geode audit</code> CLI activates this mode so that the base agent behavior Petri measures is
              not buried under GEODE identity. The auditor and judge receive a transcript comparable to a vanilla LLM.
            </p>
            <ul>
              <li>See <a href="/geode/docs/petri/run">Run an Audit</a>.</li>
              <li>Stripped: the GEODE_PERSONA block plus part of <code>&lt;dynamic_context&gt;</code>.</li>
              <li>Kept: tool definitions, MCP descriptions, baseline safety guards.</li>
            </ul>

            <h2>Source</h2>
            <ul>
              <li>v0.93.0: <code>GEODE_PERSONA</code> opt-in introduced; audit-mode strip aligned.</li>
              <li>v0.92.0: audit-mode branch added together with Petri audit integration.</li>
            </ul>

            <p className="text-white/40 text-sm">
              <em>See:</em> <a href="/geode/docs/runtime/llm/prompt-system">Prompt System</a>, <a href="/geode/docs/petri/overview">Petri × GEODE</a>, CHANGELOG v0.92-0.93.
            </p>
          </>
        }
      />
    </DocsShell>
  );
}
