import { DocsShell, Bi } from "@/components/geode-docs/docs-shell";

export const metadata = { title: "Prompt Hashing — GEODE Docs" };

export default function Page() {
  return (
    <DocsShell
      slug="runtime/llm/prompt-hashing"
      title="Prompt Hashing"
      titleKo="프롬프트 해싱"
      summary="A SHA-256 hash ratchet (Karpathy P4) that breaks CI on unintended prompt drift. 18 templates pinned, re-pin workflow documented."
      summaryKo="의도치 않은 prompt drift 발생 시 CI를 중단시키는 SHA-256 해시 잠금장치 (Karpathy P4). 18개 템플릿이 핀으로 고정되고, 재핀(re-pin) 절차가 문서화되어 있습니다."
    >
      <Bi
        ko={
          <>
            <h2>두 개의 함수</h2>
            <pre>{`# core/llm/prompts/__init__.py
def _hash_prompt(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:12]

# core/llm/prompts/axes.py
def _hash_axes(data) -> str:
    return hashlib.sha256(
        json.dumps(data, sort_keys=True).encode()
    ).hexdigest()[:12]`}</pre>
            <p>
              12자리 hex = 48비트. 18개 prompt라는 닫힌 집합에서 충돌 확률은
              무시할 수 있습니다. 목표는 탐지이지 암호학적 보안이 아닙니다.
            </p>
            <p>
              axes 해시는 YAML 파서 버전과 Python dict 순서에 걸쳐 JSON 직렬화가
              결정적이도록 <code>sort_keys=True</code>를 사용합니다.
            </p>

            <h2>18개의 고정 엔트리</h2>
            <pre>{`PROMPT_VERSIONS / _PINNED_HASHES (sorted)

  AGENTIC_SUFFIX             5630f3a61683
  ANALYST_SPECIFIC           44136fa355b3
  ANALYST_SYSTEM             b800a57a4599
  ANALYST_TOOLS_SUFFIX       36055d5618f4
  ANALYST_USER               63711de6c099
  COMMENTARY_SYSTEM          488d8916d958
  COMMENTARY_USER            2024ac4eba69
  CROSS_LLM_DUAL_VERIFY      602669128ae2
  CROSS_LLM_RESCORE          163b08e97d66
  CROSS_LLM_SYSTEM           bf303f600fce
  EVALUATOR_AXES             44136fa355b3
  EVALUATOR_SYSTEM           93ecabb14a72
  EVALUATOR_USER             ad832adfadf0
  PROSPECT_EVALUATOR_AXES    44136fa355b3
  ROUTER_SYSTEM              c4220baeb6c0
  SYNTHESIZER_SYSTEM         1cbe199613a1
  SYNTHESIZER_TOOLS_SUFFIX   1fd89d3ece5a
  SYNTHESIZER_USER           e0bb4afab940`}</pre>
            <p>
              두 dict 모두 정확히 18개 key를 가지며, key set이 동일합니다.
            </p>

            <h2>verify_prompt_integrity</h2>
            <pre>{`def verify_prompt_integrity(*, raise_on_drift: bool = False) -> list[str]:
    drifted = []
    for name, pinned in _PINNED_HASHES.items():
        if computed[name] != pinned:
            drifted.append(f"Prompt drift: {name} pin={pinned} now={computed[name]}")
    if drifted and raise_on_drift:
        raise RuntimeError(...)
    return drifted`}</pre>
            <p>
              이 함수는{" "}
              <code>tests/test_karpathy_prompt_hardening.py::TestPromptDriftDetection</code>에서{" "}
              <code>raise_on_drift=False</code> (리스트 반환, 비어 있어야 함) 와{" "}
              <code>raise_on_drift=True</code> (예외가 발생하지 않아야 함) 양쪽
              모드로 호출됩니다.
            </p>

            <h2>재핀(re-pin) 절차</h2>
            <p>의도적으로 prompt를 변경했을 때.</p>
            <ol>
              <li><code>.md</code> 파일을 편집합니다 (예. <code>analyst.md</code>).</li>
              <li>
                새 해시를 계산합니다.
                <pre>{`uv run python -c "
from core.llm.prompts import PROMPT_VERSIONS as V
import json
print(json.dumps(dict(sorted(V.items())), indent=2))
"`}</pre>
              </li>
              <li><code>_PINNED_HASHES</code>의 해당 엔트리를 업데이트합니다.</li>
              <li><code>uv run pytest tests/test_karpathy_prompt_hardening.py</code>를 실행합니다.</li>
              <li>prompt 변경과 핀 업데이트를 <strong>한 커밋</strong>으로 함께 묶어 커밋합니다.</li>
            </ol>
            <p>
              prompt 변경과 핀 업데이트를 두 커밋으로 나누면{" "}
              <code>git history</code>에 CI 실패 상태의 커밋이 남게 됩니다.
              bisect 친화적인 커밋이라면 핀과 prompt가 같은 보폭으로 움직입니다.
            </p>

            <h2>왜 잠금장치인가</h2>
            <p>
              해시 잠금장치는 Karpathy의 P4 원칙을 GEODE 식으로 표현한 것입니다.
              한 번 통과한 품질 게이트는 조용히 후퇴해서는 안 된다는 원칙. prompt
              변경은 우연히도 쉽게 일어납니다. 병합 충돌 해결, 자동 포매터, IDE
              rename 등. 그리고 그 변경이 모델 동작에 미치는 영향을 미리 예측하기는
              어렵습니다. 잠금장치는 모든 prompt 변경을 의식적인 단계를 거치도록
              강제합니다.
            </p>

            <h2>잠금장치가 다루지 않는 것</h2>
            <ul>
              <li>
                <code>.geode/skills/</code> 의 <strong>skill 본문</strong>은{" "}
                <code>PROMPT_ASSEMBLED</code> 훅 페이로드로 관찰되지만 핀으로
                고정되지는 않습니다. prompt 주입된 skill 변경은 CI 실패가
                아닙니다.
              </li>
              <li>
                <strong>렌더링된 prompt</strong> (<code>.format()</code> 변수 치환
                이후) 는 해싱되지 않습니다. <code>hash_rendered_prompt()</code>는
                존재하지만 호출자가 없습니다.{" "}
                <em>geode-prompt-evolution P2 #3</em> 참조.
              </li>
              <li>
                <strong>디스크 무결성</strong>은 런타임에 재검증되지 않습니다.
                해싱은 패키지 import 시점에만 일어납니다.
              </li>
            </ul>
          </>
        }
        en={
          <>
            <h2>The two functions</h2>
            <pre>{`# core/llm/prompts/__init__.py
def _hash_prompt(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:12]

# core/llm/prompts/axes.py
def _hash_axes(data) -> str:
    return hashlib.sha256(
        json.dumps(data, sort_keys=True).encode()
    ).hexdigest()[:12]`}</pre>
            <p>
              Twelve hex characters = 48 bits. Collision probability is negligible
              for the closed set of 18 prompts; the goal is detection, not
              cryptographic security.
            </p>
            <p>
              The axes hash uses <code>sort_keys=True</code> to make the JSON
              serialization deterministic across YAML parser versions and Python
              dict orderings.
            </p>

            <h2>The 18 pinned entries</h2>
            <pre>{`PROMPT_VERSIONS / _PINNED_HASHES (sorted)

  AGENTIC_SUFFIX             5630f3a61683
  ANALYST_SPECIFIC           44136fa355b3
  ANALYST_SYSTEM             b800a57a4599
  ANALYST_TOOLS_SUFFIX       36055d5618f4
  ANALYST_USER               63711de6c099
  COMMENTARY_SYSTEM          488d8916d958
  COMMENTARY_USER            2024ac4eba69
  CROSS_LLM_DUAL_VERIFY      602669128ae2
  CROSS_LLM_RESCORE          163b08e97d66
  CROSS_LLM_SYSTEM           bf303f600fce
  EVALUATOR_AXES             44136fa355b3
  EVALUATOR_SYSTEM           93ecabb14a72
  EVALUATOR_USER             ad832adfadf0
  PROSPECT_EVALUATOR_AXES    44136fa355b3
  ROUTER_SYSTEM              c4220baeb6c0
  SYNTHESIZER_SYSTEM         1cbe199613a1
  SYNTHESIZER_TOOLS_SUFFIX   1fd89d3ece5a
  SYNTHESIZER_USER           e0bb4afab940`}</pre>
            <p>
              Both dictionaries have exactly 18 keys; their key sets are equal.
            </p>

            <h2>verify_prompt_integrity</h2>
            <pre>{`def verify_prompt_integrity(*, raise_on_drift: bool = False) -> list[str]:
    drifted = []
    for name, pinned in _PINNED_HASHES.items():
        if computed[name] != pinned:
            drifted.append(f"Prompt drift: {name} pin={pinned} now={computed[name]}")
    if drifted and raise_on_drift:
        raise RuntimeError(...)
    return drifted`}</pre>
            <p>
              The function is invoked by{" "}
              <code>tests/test_karpathy_prompt_hardening.py::TestPromptDriftDetection</code>{" "}
              with both <code>raise_on_drift=False</code> (returns a list, asserted
              empty) and <code>raise_on_drift=True</code> (asserts no exception).
            </p>

            <h2>Re-pin workflow</h2>
            <p>When a prompt is intentionally changed:</p>
            <ol>
              <li>Edit the <code>.md</code> file (e.g. <code>analyst.md</code>).</li>
              <li>
                Compute new hashes:
                <pre>{`uv run python -c "
from core.llm.prompts import PROMPT_VERSIONS as V
import json
print(json.dumps(dict(sorted(V.items())), indent=2))
"`}</pre>
              </li>
              <li>Update the corresponding entry in <code>_PINNED_HASHES</code>.</li>
              <li>Run <code>uv run pytest tests/test_karpathy_prompt_hardening.py</code>.</li>
              <li>Commit prompt change and pin update <strong>together</strong> in one commit.</li>
            </ol>
            <p>
              Splitting the prompt change and the pin update across two commits
              leaves a CI-broken commit in <code>git history</code>. Bisect-friendly
              commits keep the pin and the prompt in lockstep.
            </p>

            <h2>Why ratchet</h2>
            <p>
              The hash ratchet is the GEODE expression of Karpathy&apos;s P4
              principle: once a quality gate is passed, it should never silently
              regress. Prompt changes are easy to make accidentally — a
              merge-conflict resolution, an autoformatter, an IDE rename — and
              their downstream effects on model behaviour are hard to foresee. The
              ratchet forces every prompt change through a conscious step.
            </p>

            <h2>What the ratchet does not cover</h2>
            <ul>
              <li>
                <strong>Skill bodies</strong> in <code>.geode/skills/</code> are
                observed via the <code>PROMPT_ASSEMBLED</code> hook payload but not
                pinned. A prompt-injected skill change is not a CI failure.
              </li>
              <li>
                <strong>Rendered prompts</strong> (after <code>.format()</code>{" "}
                variable substitution) are not hashed. <code>hash_rendered_prompt()</code>{" "}
                exists but has no callers — see{" "}
                <em>geode-prompt-evolution P2 #3</em>.
              </li>
              <li>
                <strong>Disk integrity</strong> is not re-verified at runtime; the
                hash only fires at import time of the package.
              </li>
            </ul>
          </>
        }
      />
    </DocsShell>
  );
}
