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
v1 필드는 additive이므로 구버전 peer는 이를 무시할 수 있다.

```json
{"type":"session","session_id":"cli-1234","version":"1.0.23","protocol_version":"geode.ipc.v1","features":["bounded_json","request_correlation","stable_events"]}
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
실제 Unix socket에서 field-less 구버전 호환과 정확한 request correlation을
검증한다. Gateway test는 envelope 제한과 processor correlation을, public-hook
test는 exact 이름과 두 schema version을 고정한다.
