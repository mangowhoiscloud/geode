import { DocsShell, Bi } from "@/components/geode-docs/docs-shell";

export const metadata = { title: "External References — GEODE Docs" };

export default function Page() {
  return (
    <DocsShell
      slug="reference/external-references"
      title="External References"
      titleKo="외부 참고"
      summary="Frontier agent systems, design standards, and prior work cited by GEODE."
      summaryKo="GEODE가 인용하는 frontier 에이전트 시스템, 디자인 표준, 선행 작업."
    >
      <Bi
        ko={
          <>
            <p>
              <strong>Reference:</strong> GEODE 설계와 docs 구조에 영향을 준 외부 시스템·표준·선행 작업의 인덱스.
              구체 차용 패턴은 본 docs 안의 챕터별로 명시되며, 이 페이지는 그 출처를 한 곳에 모읍니다.
            </p>

            <h2>Frontier 에이전트 시스템</h2>
            <table>
              <thead><tr><th>시스템</th><th>출처</th><th>GEODE가 가져온 것</th></tr></thead>
              <tbody>
                <tr><td><strong>Claude Code</strong></td><td><a href="https://docs.anthropic.com/en/docs/claude-code/overview">docs.anthropic.com</a></td><td>while(tool_use) primitive, CLAUDE.md 스캐폴드 패턴, 4-tier memory, hooks 패턴.</td></tr>
                <tr><td><strong>Codex CLI</strong></td><td>OpenAI Codex</td><td>thin CLI + IPC daemon, OAuth flow, sandbox policy.</td></tr>
                <tr><td><strong>OpenClaw</strong></td><td><a href="https://github.com/openclaw/openclaw">github.com/openclaw/openclaw</a></td><td>Gateway-centric routing, Lane Queue 동시성, Session 격리, Plugin 발견, Policy Chain.</td></tr>
                <tr><td><strong>Karpathy autoresearch</strong></td><td><a href="https://github.com/karpathy/autoresearch">github.com/karpathy/autoresearch</a> (2026-03)</td><td>Fixed wall-budget으로 비교 가능성 보존. Frozen scoreboard 분리. git monotone ratchet. Token-economic loop. Simplicity criterion.</td></tr>
                <tr><td><strong>Karpathy LLM Wiki</strong></td><td>gist (2024+)</td><td>&quot;wiki = compiled artifact&quot; 지식 컴파일 패턴.</td></tr>
                <tr><td><strong>Hermes Agent (NousResearch)</strong></td><td><a href="https://hermes-agent.nousresearch.com/docs/">hermes-agent.nousresearch.com/docs</a></td><td>llms.txt / llms-full.txt 듀얼 인덱스, system_and_3 cache_control 패턴, 멀티채널 personal agent.</td></tr>
                <tr><td><strong>Cursor</strong></td><td>cursor.com</td><td>Composer 패턴 (참조용. GEODE는 별도 구현).</td></tr>
                <tr><td><strong>Aider</strong></td><td>aider.chat</td><td>&quot;AI pair programming in your terminal&quot; 카피 패턴 (간결한 hero 1-line).</td></tr>
                <tr><td><strong>Devin / Cognition</strong></td><td>cognition.ai/devin</td><td>&quot;The AI software engineer&quot; 명사구 정체성. 장기 실행 소프트웨어 에이전트 비교점.</td></tr>
              </tbody>
            </table>

            <h2>Diátaxis 와 docs 디자인 표준</h2>
            <ul>
              <li>
                <strong>Diátaxis 4-quadrant framework</strong>{" "}
                (<a href="https://diataxis.fr">diataxis.fr</a>) — Tutorial / How-to / Reference / Explanation.
                본 docs의 챕터 분할과 페이지별 quadrant chip의 근간.
              </li>
              <li>
                <strong>Anthropic Platform Docs</strong>{" "}
                (<a href="https://platform.claude.com/docs/en/docs/welcome">platform.claude.com</a>) — 분기점 비교 표 1개 강제. CardGroup 패턴.
              </li>
              <li>
                <strong>OpenClaw AGENTS.md</strong>{" "}
                (<a href="https://github.com/openclaw/openclaw/blob/main/AGENTS.md">repo root</a>) — 코드 모듈별 scoped guide. (GEODE 적용은 다음 sprint.)
              </li>
              <li>
                <strong>Hermes llms.txt + llms-full.txt</strong> — LLM-친화 평문 인덱스 듀얼. GEODE도 같은 듀얼을 발행하고 리서치 휴리스틱으로 씁니다. <a href="/geode/docs/runtime/research">리서치·탐색과 llms.txt</a> 참고.
              </li>
              <li>
                <strong>Google Stitch DESIGN.md 9-section spec</strong> — site/DESIGN.md의 포맷 가이드.
              </li>
            </ul>

            <h2>Petri / inspect_ai</h2>
            <ul>
              <li>
                <strong>Anthropic Alignment Science Petri</strong>. alignment audit framework (Auditor·Target·Judge 3-role, seed corpus scored across judge dimensions). 본 docs <a href="/geode/docs/petri/overview">Petri × GEODE</a> 챕터 전체.
              </li>
              <li>
                <strong>inspect_ai (UK AISI)</strong>{" "}
                (<a href="https://inspect.aisi.org.uk/">inspect.aisi.org.uk</a>) — Petri의 기반 프레임워크. transcript viewer v3가 Petri 네이티브 지원 (2026-05-07).
              </li>
              <li>
                <strong>Meridian Labs</strong>{" "}
                (<a href="https://meridianlabs.ai">meridianlabs.ai</a>) — inspect_petri v3 (MIT) maintainer.
              </li>
            </ul>

            <h2>내부 자산 (이 repo에 직접 들어 있지 않음)</h2>
            <p>다음은 GEODE 작업이 의존하는 별도 repo의 SOT 자료입니다.</p>
            <ul>
              <li>
                <strong>mango-wiki/projects/geode/concepts/</strong> (33 narrative 파일) — 시스템별 설계 narrative. agentic-loop, gateway, hook-production-gap, memory-system, prompt-* 5 변형, scaffold-production, session-lane, tool-routing 등. 본 docs의 깊은 본문 보강 시 1차 소스.
              </li>
              <li>
                <strong>mango-wiki/projects/geode/references/</strong> (33 blog hub 파일) — 블로그 글 인덱스, ADR, career hub.
              </li>
              <li>
                <strong>mango-wiki/projects/geode/official-docs/v0.65.0/</strong> — 이전 docs 정식 sitemap (10 section). 현 docs의 부모 구조.
              </li>
              <li>
                <strong>resume/common/GEODE-BULLET-MAP.md</strong>. 시스템별 불릿 카테고리 SSOT 커버리지 매핑. 레주메·인터뷰 인용용.
              </li>
              <li>
                <strong>resume/common/narratives/autoresearch-ratchet-reference.md</strong> — Karpathy autoresearch의 5가지 reusable pattern을 GEODE·Crumb에 매핑.
              </li>
              <li>
                <strong>resume/common/narratives/llm-5-commandments.md</strong> — LLM 시스템 설계 5계명.
              </li>
            </ul>

            <h2>Karpathy autoresearch (2026-03) 의 5 reusable pattern</h2>
            <p>
              GEODE의 핵심 안전 메커니즘은 Karpathy의 autoresearch 패턴을 long-running agent context로 일반화한 것입니다.
              <a href="/geode/docs/explanation/ratchet">왜 ratchet 규율인가</a> 페이지에서 직접 인용합니다.
            </p>
            <ol>
              <li><strong>Fixed wall-budget</strong>으로 비교가능성 보존. 모든 실험이 5분 wall-clock. → GEODE의 StuckDetector 7200s + 30s wrap-up 여유.</li>
              <li><strong>Frozen scoreboard</strong> 분리. 평가 harness가 agent-mutable 영역 밖에 동결. → GEODE의 validator + CourtEval grader 분리.</li>
              <li><strong>git monotone ratchet</strong>. branch HEAD가 절대 안 나빠짐. KEEP만 commit. → GEODE의 transcript-jsonl audit cycle.</li>
              <li><strong>Token-economic loop</strong>. run.log + grep anchor + TSV append-only. → GEODE의 200-turn sliding window.</li>
              <li><strong>Simplicity criterion</strong>. &quot;removing code with equal-or-better metric = great outcome&quot;. → GEODE Runtime 1476→517 라인 분해 (v0.30), Registry 257 라인 제거 (v0.44).</li>
            </ol>

            <p className="text-[var(--ink-3)] text-sm">
              <em>출처:</em> resume/common/narratives/autoresearch-ratchet-reference.md, wiki/.../bagelcode-autoresearch-karpathy-2026.md.
            </p>
          </>
        }
        en={
          <>
            <p>
	              <strong>Reference:</strong> an index of external systems, standards, and prior work that influenced GEODE&apos;s
              design and documentation structure. Specific borrowings are cited inside the relevant chapters; this page
              collects the sources in one place.
            </p>

            <h2>Frontier agent systems</h2>
            <table>
              <thead><tr><th>System</th><th>Source</th><th>What GEODE took</th></tr></thead>
              <tbody>
                <tr><td><strong>Claude Code</strong></td><td><a href="https://docs.anthropic.com/en/docs/claude-code/overview">docs.anthropic.com</a></td><td>while(tool_use) primitive, CLAUDE.md scaffold pattern, 4-tier memory, hook pattern.</td></tr>
                <tr><td><strong>Codex CLI</strong></td><td>OpenAI Codex</td><td>thin CLI plus IPC daemon, OAuth flow, sandbox policy.</td></tr>
                <tr><td><strong>OpenClaw</strong></td><td><a href="https://github.com/openclaw/openclaw">github.com/openclaw/openclaw</a></td><td>Gateway-centric routing, Lane Queue concurrency, Session isolation, plugin discovery, Policy Chain.</td></tr>
                <tr><td><strong>Karpathy autoresearch</strong></td><td><a href="https://github.com/karpathy/autoresearch">github.com/karpathy/autoresearch</a> (2026-03)</td><td>Fixed wall-budget for comparability. Frozen scoreboard. git monotone ratchet. Token-economic loop. Simplicity criterion.</td></tr>
                <tr><td><strong>Karpathy LLM Wiki</strong></td><td>gist (2024+)</td><td>&quot;wiki = compiled artifact&quot; knowledge-compilation pattern.</td></tr>
                <tr><td><strong>Hermes Agent (NousResearch)</strong></td><td><a href="https://hermes-agent.nousresearch.com/docs/">hermes-agent.nousresearch.com/docs</a></td><td>llms.txt and llms-full.txt dual index, system_and_3 cache_control pattern, multi-channel personal agent.</td></tr>
                <tr><td><strong>Cursor</strong></td><td>cursor.com</td><td>Composer pattern (reference; GEODE implements separately).</td></tr>
                <tr><td><strong>Aider</strong></td><td>aider.chat</td><td>&quot;AI pair programming in your terminal&quot; copy pattern (succinct one-line hero).</td></tr>
                <tr><td><strong>Devin / Cognition</strong></td><td>cognition.ai/devin</td><td>&quot;The AI software engineer&quot; noun-anchored identity. Long-running software-agent comparison point.</td></tr>
              </tbody>
            </table>

            <h2>Diátaxis and docs design standards</h2>
            <ul>
              <li>
                <strong>Diátaxis 4-quadrant framework</strong>{" "}
                (<a href="https://diataxis.fr">diataxis.fr</a>) — Tutorial / How-to / Reference / Explanation. The basis
                for chapter division and per-page quadrant chips.
              </li>
              <li>
                <strong>Anthropic Platform Docs</strong>{" "}
                (<a href="https://platform.claude.com/docs/en/docs/welcome">platform.claude.com</a>) — comparison table at every decision point; CardGroup pattern.
              </li>
              <li>
                <strong>OpenClaw AGENTS.md</strong>{" "}
                (<a href="https://github.com/openclaw/openclaw/blob/main/AGENTS.md">repo root</a>) — code-module scoped guides. GEODE adoption deferred to a later sprint.
              </li>
              <li>
                <strong>Hermes llms.txt and llms-full.txt</strong> — dual LLM-friendly flat index. GEODE now publishes the same pair and uses the convention as a research heuristic; see <a href="/geode/docs/runtime/research">Research, search, and llms.txt</a>.
              </li>
              <li>
                <strong>Google Stitch DESIGN.md 9-section spec</strong> — the format guide behind site/DESIGN.md.
              </li>
            </ul>

            <h2>Petri / inspect_ai</h2>
            <ul>
              <li>
                <strong>Anthropic Alignment Science Petri</strong>. Alignment audit framework (Auditor, Target, Judge,
                a seed corpus scored across judge dimensions). Covered in the <a href="/geode/docs/petri/overview">Petri × GEODE</a> chapter.
              </li>
              <li>
                <strong>inspect_ai (UK AISI)</strong>{" "}
                (<a href="https://inspect.aisi.org.uk/">inspect.aisi.org.uk</a>) — the base framework for Petri.
                Transcript viewer v3 supports Petri natively (2026-05-07).
              </li>
              <li>
                <strong>Meridian Labs</strong>{" "}
                (<a href="https://meridianlabs.ai">meridianlabs.ai</a>) — maintainer of inspect_petri v3 (MIT).
              </li>
            </ul>

            <h2>Internal assets (not in this repo)</h2>
            <p>The following SOT material lives in separate repositories that GEODE work depends on.</p>
            <ul>
              <li>
                <strong>mango-wiki/projects/geode/concepts/</strong> (33 narrative files) — per-system design narratives.
                agentic-loop, gateway, hook-production-gap, memory-system, the five prompt-* variants,
                scaffold-production, session-lane, tool-routing, and more. The primary source when filling in this
                site&apos;s deeper page bodies.
              </li>
              <li>
                <strong>mango-wiki/projects/geode/references/</strong> (33 blog hub files) — blog post index, ADR,
                career hub.
              </li>
              <li>
                <strong>mango-wiki/projects/geode/official-docs/v0.65.0/</strong> — the previous official docs sitemap
                (10 sections). The parent structure of the current docs.
              </li>
              <li>
                <strong>resume/common/GEODE-BULLET-MAP.md</strong>. SSOT coverage mapping of systems by bullet
                categories. Used for resume and interview citations.
              </li>
              <li>
                <strong>resume/common/narratives/autoresearch-ratchet-reference.md</strong> — Karpathy autoresearch&apos;s
                five reusable patterns mapped onto GEODE and Crumb.
              </li>
              <li>
                <strong>resume/common/narratives/llm-5-commandments.md</strong> — five commandments for LLM system design.
              </li>
            </ul>

            <h2>Karpathy autoresearch (2026-03): five reusable patterns</h2>
            <p>
              GEODE&apos;s core safety mechanism generalizes Karpathy&apos;s autoresearch patterns to a long-running agent
              context. <a href="/geode/docs/explanation/ratchet">Why Ratchet Discipline</a> cites these directly.
            </p>
            <ol>
	              <li><strong>Fixed wall-budget</strong> preserves comparability. Every experiment is five minutes of wall-clock. GEODE&apos;s StuckDetector at 7200s plus 30s wrap-up headroom is the generalized form.</li>
	              <li><strong>Frozen scoreboard</strong>. The evaluation harness lives outside the agent-mutable region. GEODE&apos;s validator plus CourtEval grader separation is the same idea.</li>
	              <li><strong>git monotone ratchet</strong>. Branch HEAD never gets worse. Only KEEP commits. GEODE&apos;s transcript-jsonl audit cycle is the variant.</li>
	              <li><strong>Token-economic loop</strong>. run.log plus grep anchors plus append-only TSV. GEODE&apos;s 200-turn sliding window is the variant.</li>
	              <li><strong>Simplicity criterion</strong>. &quot;Removing code with equal-or-better metric = great outcome.&quot; GEODE Runtime 1476 → 517 lines (v0.30) and Registry minus 257 lines (v0.44) follow the same rule.</li>
            </ol>

            <p className="text-[var(--ink-3)] text-sm">
              <em>Source:</em> resume/common/narratives/autoresearch-ratchet-reference.md, wiki/.../bagelcode-autoresearch-karpathy-2026.md.
            </p>
          </>
        }
      />
    </DocsShell>
  );
}
