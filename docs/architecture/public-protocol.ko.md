# 공개 프로토콜 경계

> [English](public-protocol.md) | **한국어**

GEODE는 서로 다른 공개 envelope 세 개를 명시적으로 유지한다. 내부
`RuntimeEvent`, `HookEvent`, transport SDK object, dataclass에 필드나 enum
member가 추가되어도 자동으로 공개 계약이 되지 않는다.

| 표면 | 현재 버전 | 안정된 권위 | 제한과 상관관계 |
|---|---|---|---|
| CLI IPC | `geode.ipc.v1` | `core/ipc_protocol.py` | JSON 한 줄 1 MiB; stream/event/final response의 request ID |
| Gateway 입력 | `geode.gateway.v1` | `core/messaging/models.py` | content 64 KiB; JSON metadata 32 KiB; 플랫폼 message ID |
| Extension hook | `geode.public-hook.v2` | `core/hooks/public.py` | redacted payload 32 KiB; typed hook correlation; v1 schema 조회 |

## CLI IPC

thin CLI와 `CLIPoller`는 기존 flat line-delimited JSON 형식을 유지한다.
v1 envelope는 additive이며, 세션 모델 설정 적용에는 협상된
`session_model_config` 기능이 필요하다.

```json
{"type":"session","session_id":"cli-1234","version":"1.0.23","protocol_version":"geode.ipc.v1","features":["bounded_json","request_correlation","stable_events","session_model_config"]}
```

client는 `client_capability`에 같은 버전과 지원 feature 목록을 보낸다.
daemon은 자신이 아는 교집합만 선택한다. `protocol_version`이 없는 greeting은
legacy `geode.ipc.v0` 계약이며, 명시된 미지원 버전은 fail-closed한다. codec은
unknown field를 보존하고 권위가 없는 reader는 이를 무시한다. 알 수 없는 client
message type에는 명시적 error를 반환한다. 알 수 없는 streaming event는 client가
무시하며, stable `IPC_EVENT_TYPES`에 추가되기 전에는 server의 public event
writer가 보낼 수 없다.

새 client request마다 opaque `request_id`가 붙는다. server는 같은 ID를 stream
text, approval, structured event, final response에 붙인다. ID가 없는 legacy
response는 계속 읽지만 다른 ID의 응답은 active request에 전달하지 않는다.

socket은 local이며 mode `0600`이다. 따라서 user prompt와 model result는 전송
중 redaction하지 않고 그대로 보존한다. 대신 envelope와 receive buffer를 1
MiB로 제한해 무한 할당을 막는다.

### 세션 모델 설정

새 클라이언트는 `session_model_config` 기능을 협상하고 최초
`client_capability.model_config`에 `core/config/session.py`의 비밀값 없는
`SessionModelConfig`를 전달합니다. 주 모델·native effort·구체적 adapter
source와 reflection/judge 모델·source, reflection 출력 제한, 두 호출의
온도 및 judgment 선택만 포함합니다. 인증 키나 credential-source 정책을
실제 adapter source와 혼동하지 않습니다. 보조 모델/source가 모두 비어
있으면 현재 주 모델의 경로를 상속합니다.

데몬은 전체 후보를 검증·적용한 뒤에만 `status: applied` ACK와 실제 설정,
기존 `workspace` 및 `checkpoint_directory`를 반환합니다. 다른 workspace나
중첩된 별도 프로젝트는 거절하며, 같은 workspace 하위 경로도 데몬의
기존 root에서 실행합니다. 프로세스 cwd를 바꾸지 않습니다. 기능 없는
구버전 peer는 재시작·업그레이드 후 다시 연결해야 합니다. v0 codec을 읽을
수 있다는 사실은 설정을 무시한 실행을 허용한다는 뜻이 아닙니다.

이름 지정·picker·fullscreen `/model`은 같은 command와 bounded patch를
사용합니다. 기존 session lane에서 현재 세션에 적용한 응답을 받은 뒤
클라이언트가 기본값을 저장합니다. 거절 시 저장하지 않으며, 적용 후 저장
실패는 두 결과를 구분해 표시합니다. project/global은 미래 세션의 기본값
범위이며 다른 실행 중 세션을 덮어쓰지 않습니다. Mutator는 기존 다음 실행
소유자를 유지합니다. 취소는 patch를 보내지 않고, 매 prompt의 터미널 크기
갱신에도 모델 설정을 다시 보내지 않습니다.

도구 projection 실패 시 이전 모델 경로와 도구 바인딩을 복원합니다. 그 전에
이전 경로로 유효한 compaction이 완료됐을 수 있으므로 이력이나 외부 효과의
rollback까지 보장하지는 않습니다. 보조 호출은 세션의 불변 설정과 기존 인증
소유자를 사용합니다. 새 checkpoint의 `state.json.model_settings`에는 같은
비밀값 없는 record가 저장됩니다. resume는 이력을 변경하거나 머신을 다시 열기
전에 설정을 승인하고, 실제 `model_config`와 `model_config_origin:
checkpoint|current`를 반환합니다. 클라이언트는 이 값으로 선택을 갱신합니다.
legacy 필드 부재는 현재 검증된 선택을 유지하고, 존재하지만 잘못된 record는
거절합니다. 기존 JSON IPC envelope와 협상 기능은 유지합니다.

## Gateway 입력

Slack, Discord, Telegram receiver는 GEODE가 쓰는 필드만 `InboundMessage`로
선택하며 SDK payload 전체를 전달하지 않는다. envelope는 routing 전에 유한한
timestamp, 제한된 identifier/content, JSON-safe bounded metadata를 검증한다.
upstream message identifier는 `message_id`가 되고 processor metadata까지 전달돼
상관관계를 유지한다. 플랫폼 ID가 없는 direct/internal caller에만 stable hash
fallback을 쓴다.

unknown upstream field는 projection 과정에서 무시한다. message content는 model에
전달할 user input이므로 사전 redaction하지 않는다. token과 플랫폼 credential은
envelope 밖에 있고, durable activity와 public-hook projection은 각자의 redaction
계약을 적용한다.

## Extension event

extension 경계는 계속 `HookName`과 `HookRegistry`다. 자세한 내용은
[Hook architecture](hook-system.ko.md)를 본다. 13개 이름, hook별 JSON Schema,
closed decision, secret redaction, payload 제한, v1/v2 호환성은 이미 공개
extension 계약을 충족한다. 내부 event 증가는 이 ABI를 확장하지 않는다.

## 호환성 증거

golden v0/v1 IPC greeting은 `tests/fixtures/protocol/`에 있다. protocol test는
협상, unknown-field 보존, event 이름, size failure를 고정한다. integration test는
실제 Unix socket에서 미지원 peer 거절, 세션 적용 성공·실패와 정확한 request correlation을
검증한다. Gateway test는 envelope 제한과 processor correlation을, public-hook
test는 exact 이름과 두 schema version을 고정한다.
