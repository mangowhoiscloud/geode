import { DocsShell, Bi } from "@/components/geode-docs/docs-shell";

export const metadata = { title: "Changelog — GEODE Docs" };

export default function Page() {
  return (
    <DocsShell
      slug="reference/changelog"
      title="Changelog"
      titleKo="변경 이력"
      summary="Selected version highlights. The authoritative changelog is CHANGELOG.md in the repository."
      summaryKo="선별된 버전 하이라이트. 정본 changelog는 저장소의 CHANGELOG.md입니다."
    >
      <Bi
        ko={
          <>
            <h2>v0.65.0. 2026-05-02</h2>
            <ul>
              <li>
                Anthropic 4-breakpoint 프롬프트 캐시. <code>apply_messages_cache_control()</code>이
                직전 3개 non-system 메시지에 걸쳐 ephemeral 마커를 굴려, 기존 system 블록 분할
                (Hermes <code>system_and_3</code> 등가)을 보완합니다.
              </li>
              <li>
                <code>manage_login</code> verdict shadowing 수정. 정상 PAYG / OAuth 프로파일이
                더 이상 대시보드에서 <code>provider_mismatch</code>로 표시되지 않습니다.
                verdict 집계가 이제 cross-provider 반복을 건너뜁니다. v0.51.0부터
                <code>credential_breadcrumb</code>이 적용해 온 필터와 일치합니다.
              </li>
            </ul>

            <h2>v0.64.0. 2026-04-29</h2>
            <ul>
              <li>
                <strong>플러그인 네임스페이스 분리.</strong>{" "}
                <code>core/domains/game_ip/</code> →{" "}
                <code>plugins/game_ip/</code>. Hatch wheel이 두 최상위 패키지를 모두 출시합니다.
                36개 파일에 걸쳐 72개 import 문이 재작성되었으며, 품질 게이트가
                <code>plugins/</code>를 포함하도록 확장되었습니다.
              </li>
            </ul>

            <h2>v0.63.0. 2026-04-29</h2>
            <ul>
              <li>
                <strong>라이프사이클 명령어.</strong> <code>/stop</code>,{" "}
                <code>/clean</code>, <code>/uninstall</code>, <code>/status</code>가 기존 슬래시
                명령어와 함께 추가되었습니다.
              </li>
            </ul>

            <h2>v0.62.0. 2026-04-28</h2>
            <ul>
              <li>
                <strong>라이브 테스트 하네스.</strong>{" "}
                <code>tests/test_e2e_live_reasoning_depth.py</code>가 실제 프로바이더 대상으로
                전체 파이프라인을 실행합니다 (5 케이스). 마커는 <code>-m live</code>이며
                기본 deselect됩니다.
              </li>
            </ul>

            <h2>v0.60.0. 2026-04-28</h2>
            <ul>
              <li>
                <strong>R3-mini PAYG OpenAI Responses 등가.</strong>{" "}
                gpt-5.x에 <code>include=[reasoning.encrypted_content]</code> +{" "}
                <code>summary=&quot;auto&quot;</code>.
              </li>
            </ul>

            <h2>v0.56.0. 2026-04-26</h2>
            <ul>
              <li>
                <strong>Opus 4.7의 Anthropic adaptive thinking <code>xhigh</code>.</strong>{" "}
                Opus 4.7에서 <code>output_config.effort=&quot;xhigh&quot;</code> +{" "}
                <code>display=&quot;summarized&quot;</code>. 구형 모델은 <code>max</code>로
                downgrade됩니다.
              </li>
            </ul>

            <h2>v0.50.x. Karpathy P4 ratchet</h2>
            <ul>
              <li>
                <strong>프롬프트 해시 ratchet 도입.</strong> 20개 <code>_PINNED_HASHES</code>
                엔트리. drift 발생 시 CI가 break합니다.
                <a href="/geode/docs/runtime/llm/prompt-hashing">프롬프트 해싱</a>을 참고하세요.
              </li>
            </ul>

            <h2>정본</h2>
            <p>
              <code>github.com/mangowhoiscloud/geode/blob/main/CHANGELOG.md</code>가 진리원입니다.
              이 페이지는 기능별 세부 단위가 아니라 프로젝트 진화의 형태를 보고 싶은 독자를 위한
              선별된 하이라이트 모음입니다.
            </p>
          </>
        }
        en={
          <>
            <h2>v0.65.0 — 2026-05-02</h2>
            <ul>
              <li>
                Anthropic 4-breakpoint prompt cache. <code>apply_messages_cache_control()</code> rolls
                ephemeral markers across the last three non-system messages, complementing the existing
                system block split (Hermes <code>system_and_3</code> parity).
              </li>
              <li>
                <code>manage_login</code> verdict shadowing fix. Healthy PAYG / OAuth profiles no longer
                appear as <code>provider_mismatch</code> in the dashboard; verdict aggregation now skips
                cross-provider iterations, matching the filter <code>credential_breadcrumb</code> has
                applied since v0.51.0.
              </li>
            </ul>

            <h2>v0.64.0 — 2026-04-29</h2>
            <ul>
              <li>
                <strong>Plugin namespace split.</strong>{" "}
                <code>core/domains/game_ip/</code> →{" "}
                <code>plugins/game_ip/</code>. Hatch wheel ships both top-level
                packages. 72 import statements rewritten across 36 files; quality
                gates extended to cover <code>plugins/</code>.
              </li>
            </ul>

            <h2>v0.63.0 — 2026-04-29</h2>
            <ul>
              <li>
                <strong>Lifecycle commands.</strong> <code>/stop</code>,{" "}
                <code>/clean</code>, <code>/uninstall</code>, <code>/status</code>{" "}
                land alongside the existing slash commands.
              </li>
            </ul>

            <h2>v0.62.0 — 2026-04-28</h2>
            <ul>
              <li>
                <strong>Live test harness.</strong>{" "}
                <code>tests/test_e2e_live_reasoning_depth.py</code> runs the
                full pipeline against real providers (5 cases). Marker:{" "}
                <code>-m live</code>; default-deselected.
              </li>
            </ul>

            <h2>v0.60.0 — 2026-04-28</h2>
            <ul>
              <li>
                <strong>R3-mini PAYG OpenAI Responses parity.</strong>{" "}
                <code>include=[reasoning.encrypted_content]</code> +{" "}
                <code>summary=&quot;auto&quot;</code> for gpt-5.x.
              </li>
            </ul>

            <h2>v0.56.0 — 2026-04-26</h2>
            <ul>
              <li>
                <strong>Anthropic adaptive thinking <code>xhigh</code> on Opus 4.7.</strong>{" "}
                <code>output_config.effort=&quot;xhigh&quot;</code> +{" "}
                <code>display=&quot;summarized&quot;</code> on Opus 4.7. Older
                models downgrade to <code>max</code>.
              </li>
            </ul>

            <h2>v0.50.x — Karpathy P4 ratchet</h2>
            <ul>
              <li>
                <strong>Prompt hash ratchet introduced.</strong> 20{" "}
                <code>_PINNED_HASHES</code> entries; CI breaks on drift. See{" "}
                <a href="/geode/docs/runtime/llm/prompt-hashing">Prompt Hashing</a>.
              </li>
            </ul>

            <h2>Authoritative source</h2>
            <p>
              <code>github.com/mangowhoiscloud/geode/blob/main/CHANGELOG.md</code>{" "}
              is the source of truth. This page is a curated highlight reel for
              readers who want the shape of the project&apos;s evolution rather
              than the per-feature granularity.
            </p>
          </>
        }
      />
    </DocsShell>
  );
}
