import { DocsShell, Bi } from "@/components/geode-docs/docs-shell";

export const metadata = { title: "Cross-LLM Verification — GEODE Docs" };

export default function Page() {
  return (
    <DocsShell
      slug="verification/cross-llm"
      title="Cross-LLM Verification"
      titleKo="Cross-LLM 검증"
      summary="Independent second-opinion lens. A different provider re-scores the verdict so single-model failure modes do not silently propagate."
      summaryKo="독립된 second-opinion 계층. 다른 프로바이더가 verdict 를 재평가하여 단일 모델 의 실패 패턴이 조용히 전파되지 않도록 차단."
    >
      <Bi
        ko={
          <>
            <h2>왜 cross-LLM 인가</h2>
            <p>
              같은 모델 패밀리 (e.g. Claude Sonnet 두 번) 는 자기 자신의 편향을 검증하지 못합니다. 다른 프로바이더 + 다른 학습 데이터 + 다른 RLHF objective 를 가진 모델이 같은 입력에 대해 같은 verdict 에 도달하는지가 신호.
            </p>

            <h2>위치 + 호출</h2>
            <pre>{`core/verification/cross_llm.py
  └── cross_llm_verify(verdict, evidence, *, primary, second)
        primary  = anthropic/claude-opus-4-7
        second   = openai/gpt-5.5  또는  glm/glm-4.5+`}</pre>

            <p>
              두 verdict 가 일치하면 confidence boost. 어긋나면 BiasBuster 의 cause 분류 + evaluator re-prompt 트리거.
            </p>

            <h2>Codex MCP 보조 lane</h2>
            <p>
              개발 중 verification 단계는 Codex MCP server 를 통해 ChatGPT Plus subscription quota 를 사용하는 second-opinion verifier 로도 사용됩니다. CRITICAL/HIGH 자동 fix 의 lane 이며 GEODE 운영 cross-LLM 과는 독립 (skill: `codex-mcp-verify`).
            </p>

            <h2>비용 고려</h2>
            <p>
              cross-LLM 은 호출 비용을 2 배로 만듭니다. 중요 의사결정 (Tier upgrade, downgrade) 에만 사용. 단순 score 산출에는 G1-G4 + BiasBuster 만으로 충분.
            </p>

            <p className="text-white/40 text-sm"><em>참조</em>: `core/verification/cross_llm.py`, `.claude/skills/geode-verification`, `.claude/skills/codex-mcp-verify`.</p>
          </>
        }
        en={
          <>
            <h2>Why cross-LLM</h2>
            <p>
              The same model family (for example, Claude Sonnet twice) cannot audit its own bias. The signal is whether a different provider, with different training data and a different RLHF objective, reaches the same verdict on the same input.
            </p>

            <h2>Where it lives</h2>
            <pre>{`core/verification/cross_llm.py
  └── cross_llm_verify(verdict, evidence, *, primary, second)
        primary  = anthropic/claude-opus-4-7
        second   = openai/gpt-5.5  or  glm/glm-4.5+`}</pre>

            <p>
              Matching verdicts boost confidence. Diverging verdicts trigger BiasBuster's cause classification and a re-prompt in the evaluator.
            </p>

            <h2>Codex MCP as a build-time helper</h2>
            <p>
              During development the verification step also uses the Codex MCP server as a second-opinion verifier backed by the ChatGPT Plus subscription quota. That lane auto-fixes CRITICAL and HIGH findings and is independent of the runtime cross-LLM (see the `codex-mcp-verify` skill).
            </p>

            <h2>Cost tradeoff</h2>
            <p>
              Cross-LLM doubles call cost. Reserve it for material decisions (Tier upgrade or downgrade). Simple scoring is fine with G1-G4 + BiasBuster alone.
            </p>

            <p className="text-white/40 text-sm"><em>References</em>: `core/verification/cross_llm.py`, `.claude/skills/geode-verification`, `.claude/skills/codex-mcp-verify`.</p>
          </>
        }
      />
    </DocsShell>
  );
}
