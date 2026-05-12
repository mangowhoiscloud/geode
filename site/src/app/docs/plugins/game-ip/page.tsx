import { DocsShell, Bi } from "@/components/geode-docs/docs-shell";

export const metadata = { title: "Game IP Plugin — GEODE Docs" };

export default function Page() {
  return (
    <DocsShell
      slug="plugins/game-ip"
      title="Game IP Plugin"
      titleKo="Game IP 플러그인"
      summary="Closed-domain plugin for evaluating Game/IP market potential. 4 Analysts + 3 Evaluators + Synthesizer + BiasBuster, 14-axis PSM scoring."
      summaryKo="Game/IP 시장 잠재력을 평가하는 폐쇄형 도메인 플러그인. Analyst 4 + Evaluator 3 + Synthesizer + BiasBuster, 14-axis PSM 스코어링."
    >
      <Bi
        ko={
          <>
            <h2>파이프라인 형태</h2>
            <pre>{`Input: { ip_name }
   │
   ▼
load_ip_profile  (from MonoLake / fixtures)
   │
   ├─► Analyst × 4 (parallel)
   │     game_mechanics    →   findings + 1-5 score
   │     player_experience →   findings + 1-5 score
   │     growth_potential  →   findings + 1-5 score
   │     discovery         →   findings + 1-5 score
   │
   ▼
Evaluator × 3 (parallel)
   quality_judge      → 8 axes (a, b, c, b1, c1, c2, m, n)
   hidden_value       → 3 axes
   community_momentum → 3 axes
   │
   ▼
BiasBuster (6 bias checks)
   confirmation, recency, anchoring, position, verbosity, self-enhancement
   │
   ▼
Synthesizer (cause-locked narrative)
   │
   ▼
Output: tier (S/A/B/C/D) + score (0-100) + cause + recommendation`}</pre>

            <h2>픽스처</h2>
            <table>
              <thead><tr><th>IP</th><th>Tier</th><th>Score</th><th>Cause</th></tr></thead>
              <tbody>
                <tr><td>Berserk</td><td><strong>S</strong></td><td>81.2</td><td>conversion_failure</td></tr>
                <tr><td>Cowboy Bebop</td><td><strong>A</strong></td><td>68.4</td><td>undermarketed</td></tr>
                <tr><td>Ghost in the Shell</td><td><strong>B</strong></td><td>51.7</td><td>discovery_failure</td></tr>
              </tbody>
            </table>

            <h2>Configuration SSOT</h2>
            <p>
              <code>plugins/game_ip/config/evaluator_axes.yaml</code>은 다음 항목의 단일 진리원입니다.
            </p>
            <ul>
              <li><strong>4개 analyst 지시문</strong>. analyst 타입별 도메인 특화 포커스</li>
              <li><strong>3개 evaluator axis 집합</strong>. quality_judge (8), hidden_value (3), community_momentum (3)</li>
              <li><strong>한국어 rubric</strong>. axis별 1-5 anchor 설명</li>
              <li><strong>합성 공식</strong>. 예) quality_judge는 <code>(axes_sum - 8) / 32 * 100</code></li>
              <li><strong>Prospect axes</strong>. 비-게임화 IP (소설, 영화)용</li>
            </ul>
            <p>
              이 3개 최상위 키는 <code>PROMPT_VERSIONS</code>의 <code>EVALUATOR_AXES</code>,
              <code>PROSPECT_EVALUATOR_AXES</code>, <code>ANALYST_SPECIFIC</code> 엔트리로 해시됩니다.
              <a href="/geode/docs/runtime/llm/prompt-hashing">프롬프트 해싱</a>을 참고하세요.
            </p>

            <h2>플러그인 계약</h2>
            <p>
              플러그인은 <code>core/domains/port.py</code>의 <code>DomainPort</code> 프로토콜을
              구현합니다.
            </p>
            <ul>
              <li><code>get_pipeline()</code>. LangGraph StateGraph 반환</li>
              <li><code>get_valid_axes_map()</code>. evaluator별 axis 키 노출</li>
              <li><code>load_ip_profile(ip_name)</code>. 도메인 데이터 조회</li>
            </ul>
            <p>
              <code>core/domains/loader.py</code>의 로더가 시작 시점에 <code>plugins/</code>
              네임스페이스에서 플러그인을 발견합니다.
            </p>

            <h2>CLI</h2>
            <pre>{`# Dry-run (no LLM calls, returns fixture-based result)
uv run geode analyze "Cowboy Bebop" --dry-run

# Full run (requires API keys)
uv run geode analyze "Berserk" --verbose`}</pre>
          </>
        }
        en={
          <>
            <h2>Pipeline shape</h2>
            <pre>{`Input: { ip_name }
   │
   ▼
load_ip_profile  (from MonoLake / fixtures)
   │
   ├─► Analyst × 4 (parallel)
   │     game_mechanics    →   findings + 1-5 score
   │     player_experience →   findings + 1-5 score
   │     growth_potential  →   findings + 1-5 score
   │     discovery         →   findings + 1-5 score
   │
   ▼
Evaluator × 3 (parallel)
   quality_judge      → 8 axes (a, b, c, b1, c1, c2, m, n)
   hidden_value       → 3 axes
   community_momentum → 3 axes
   │
   ▼
BiasBuster (6 bias checks)
   confirmation, recency, anchoring, position, verbosity, self-enhancement
   │
   ▼
Synthesizer (cause-locked narrative)
   │
   ▼
Output: tier (S/A/B/C/D) + score (0-100) + cause + recommendation`}</pre>

            <h2>Fixtures</h2>
            <table>
              <thead><tr><th>IP</th><th>Tier</th><th>Score</th><th>Cause</th></tr></thead>
              <tbody>
                <tr><td>Berserk</td><td><strong>S</strong></td><td>81.2</td><td>conversion_failure</td></tr>
                <tr><td>Cowboy Bebop</td><td><strong>A</strong></td><td>68.4</td><td>undermarketed</td></tr>
                <tr><td>Ghost in the Shell</td><td><strong>B</strong></td><td>51.7</td><td>discovery_failure</td></tr>
              </tbody>
            </table>

            <h2>Configuration SSOT</h2>
            <p>
              <code>plugins/game_ip/config/evaluator_axes.yaml</code> is the single
              source of truth for:
            </p>
            <ul>
              <li><strong>4 analyst directives</strong> — domain-specific focus per analyst type</li>
              <li><strong>3 evaluator axis sets</strong> — quality_judge (8), hidden_value (3), community_momentum (3)</li>
              <li><strong>Korean rubrics</strong> — 1-5 anchor descriptions per axis</li>
              <li><strong>Composite formulas</strong> — e.g. <code>(axes_sum - 8) / 32 * 100</code> for quality_judge</li>
              <li><strong>Prospect axes</strong> — for non-gamified IPs (novels, films)</li>
            </ul>
            <p>
              These three top-level keys are hashed into{" "}
              <code>EVALUATOR_AXES</code>, <code>PROSPECT_EVALUATOR_AXES</code>,{" "}
              and <code>ANALYST_SPECIFIC</code> entries in{" "}
              <code>PROMPT_VERSIONS</code>. See{" "}
              <a href="/geode/docs/runtime/llm/prompt-hashing">Prompt Hashing</a>.
            </p>

            <h2>Plugin contract</h2>
            <p>
              The plugin implements the <code>DomainPort</code> protocol from{" "}
              <code>core/domains/port.py</code>:
            </p>
            <ul>
              <li><code>get_pipeline()</code> — returns the LangGraph StateGraph</li>
              <li><code>get_valid_axes_map()</code> — exposes axis keys per evaluator</li>
              <li><code>load_ip_profile(ip_name)</code> — domain data lookup</li>
            </ul>
            <p>
              The loader at <code>core/domains/loader.py</code> discovers plugins
              in the <code>plugins/</code> namespace at startup.
            </p>

            <h2>CLI</h2>
            <pre>{`# Dry-run (no LLM calls, returns fixture-based result)
uv run geode analyze "Cowboy Bebop" --dry-run

# Full run (requires API keys)
uv run geode analyze "Berserk" --verbose`}</pre>
          </>
        }
      />
    </DocsShell>
  );
}
