import { DocsShell, Bi } from "@/components/geode-docs/docs-shell";

export const metadata = { title: "Credential lifecycle — GEODE Docs" };

export default function Page() {
  return (
    <DocsShell
      slug="ops/oauth"
      title="Credential lifecycle"
      titleKo="자격 증명 수명관리"
      summary="Credential ownership, request selection, refresh, failure, and recovery limits."
      summaryKo="자격의 저장 주체, 요청별 선택, 갱신과 실패, 복구 범위를 설명합니다."
    >
      <Bi
        ko={
          <>
            <p>
              GEODE가 등록한 API 키와 ChatGPT 로그인 자격은
              <code>~/.geode/auth.toml</code>에 저장됩니다. 터미널은 키 입력과
              로그인 안내를 맡고, <code>core/auth/</code>가 검증과 저장을 맡습니다.
              모델은 비밀값 없는 상태를 조회하고 허용된 선택을 요청할 수 있습니다.
            </p>
            <h2>저장과 적용</h2>
            <p>
              인증 파일 변경은 프로세스 간 잠금 안에서 최신 파일을 다시 읽고
              후보를 검증한 뒤 교체합니다. 저장이 성공해야 현재 프로세스에
              적용합니다. 다른 프로세스는 <code>/login refresh</code>로 다시 읽습니다.
              제거된 파일 소유 항목도 반영하며, 환경 변수와 외부 관리 자격은
              각각의 소유권을 유지합니다. 저장 후 현재 프로세스의 적용이 충돌하면
              저장 완료와 적용 실패를 구분하여 갱신을 안내합니다.
            </p>
            <h2>요청과 토큰</h2>
            <ul>
              <li>세션이 선택한 프로바이더·과금 소스를 유지하면서 실제 요청의 플랜과 자격을 선택합니다. 키 교체가 진행 중인 요청의 자격을 바꾸지는 않습니다.</li>
              <li>외부 Codex 파일에서 가져온 자격은 그 파일이 소유합니다. 다음 조회·요청에서 교체와 삭제를 반영하며 Codex CLI를 추론에 실행하지 않습니다.</li>
              <li>GEODE의 ChatGPT device-code 로그인은 같은 저장소에서 한 번에 하나만 진행합니다. 실패·취소는 완료로 처리하지 않으며, 저장이 끝나야 로그인 성공을 반환합니다.</li>
              <li>만료된 GEODE 자격은 <code>/login openai</code>로 다시 로그인합니다. 외부 Codex 자격은 해당 클라이언트에서 갱신합니다. 오래된 GEODE <code>auth.json</code> 자동 이관은 제거했으며 파일은 그대로 보존합니다.</li>
            </ul>
            <h2>상태 표시의 범위</h2>
            <p>
              모델 가용성과 시작 준비 상태는 실제 라우팅·정책·자격의 적격성을
              확인합니다. 키 문자열의 존재만으로 성공을 표시하지 않습니다.
              이 검사는 오프라인 선택 가능성이며 공급자 서버의 키 유효성이나
              남은 할당량을 확인하는 네트워크 검사는 아닙니다.
              프로파일의 오류·쿨다운 필드는 선택에 반영되지만, 모든 실제 SDK
              호출의 성공·실패를 연결하는 자동 건강도 추적은 제공하지 않습니다.
              과거 전역 프로파일 추적 코드와 그에 의존한 자동 갱신 주장은 제거했습니다.
            </p>
            <p>
              저장소 전체 복원이나 외부 효과의 exactly-once 실행을 인증 파일의
              원자적 교체만으로 보장하지 않습니다. 복구 후에는 실제 자격 소스와
              세션 선택을 함께 확인합니다.
            </p>
            <ul>
              <li><a href="/geode/docs/runtime/auth">인증과 OAuth</a></li>
              <li><a href="/geode/docs/run/providers">프로바이더 설정</a></li>
            </ul>
          </>
        }
        en={
          <>
            <p>
              GEODE-managed API keys and ChatGPT login credentials live in
              <code>~/.geode/auth.toml</code>. The terminal owns secret input and
              login presentation; <code>core/auth/</code> validates and persists
              credentials. The model can inspect nonsecret state and request permitted choices.
            </p>
            <h2>Persistence and activation</h2>
            <p>
              Auth changes re-read the current file under a cross-process lock,
              validate the candidate, and replace the file before publishing it in
              the current process. Other processes adopt changes through
              <code>/login refresh</code>. Reconciliation includes removed file-owned
              entries; environment and externally managed credentials retain their
              own owners. A conflict after persistence reports the saved file and
              failed local adoption separately and requests refresh.
            </p>
            <h2>Requests and tokens</h2>
            <ul>
              <li>Each request selects an account within the session&apos;s chosen provider and billing source. Replacing a credential preserves already borrowed requests.</li>
              <li>An imported Codex credential remains owned by its external file. Subsequent reads and requests reflect replacement or deletion; Codex CLI is never spawned for inference.</li>
              <li>GEODE allows one ChatGPT device-code login attempt per auth store at a time. Failure or cancellation is not completion; success follows successful file persistence and local publication.</li>
              <li>Use <code>/login openai</code> to replace an expired GEODE credential. Refresh an external Codex credential in its owning client. The retired GEODE <code>auth.json</code> is left untouched; register again with <code>/login openai</code> instead of automatic migration.</li>
            </ul>
            <h2>What status establishes</h2>
            <p>
              Model availability and startup readiness inspect actual routing,
              policy, and credential eligibility instead of key-string presence.
              This is offline route availability, not a network check of provider
              acceptance or remaining quota. Stored error and cooldown fields
              affect eligibility, but active adapters do not attribute every SDK
              success or failure to an automatic profile-health tracker. The retired
              global tracking path and claims based on it have been removed.
            </p>
            <p>
              Atomic auth-file replacement does not establish whole-workspace
              restoration or exactly-once external effects. Recovery must inspect
              the actual credential source and the session&apos;s selection together.
            </p>
            <ul>
              <li><a href="/geode/docs/runtime/auth">Auth and OAuth</a></li>
              <li><a href="/geode/docs/run/providers">Provider setup</a></li>
            </ul>
          </>
        }
      />
    </DocsShell>
  );
}
